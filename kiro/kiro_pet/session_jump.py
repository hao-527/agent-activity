"""Jump straight to one Kiro chat session.

Kiro exposes no per-session deep link: its ``kiro://`` handler only serves
OAuth callbacks, and ``kiroAgent.viewSession`` can not be invoked from
outside the IDE. What Kiro does persist per workspace is the exact chat tab
order (``sessionPanels.entries``) plus the focused tab
(``sessionPanels.focused``), and it ships keybindings for next/previous chat
tab. So a jump is: focus the right window, then walk the tab strip by the
precomputed number of steps, then verify against the same store.
"""
from __future__ import annotations

from dataclasses import dataclass
import glob
import json
from pathlib import Path
import shlex
import sqlite3
import subprocess
import threading
import time
from urllib.parse import unquote, urlparse

from . import presence
from .config import AppConfig, KIRO_BUNDLE_ID, KIRO_WORKSPACE_STORAGE_DIR
from .keys import FLAG_COMMAND, FLAG_OPTION, KeyPoster

_KIRO_APP_CANDIDATES = (
    Path("/Applications/Kiro.app"),
    Path.home() / "Applications" / "Kiro.app",
)


def _find_kiro_cli() -> Path | None:
    """Locate Kiro's bundled ``code`` CLI wherever the app is installed.

    Hardcoding /Applications breaks jumps for anyone who installed Kiro into
    their own ~/Applications, so ask the running app first and fall back to the
    usual locations.
    """
    candidates = []
    try:
        from AppKit import NSWorkspace

        url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(
            KIRO_BUNDLE_ID
        )
        if url is not None and url.path():
            candidates.append(Path(str(url.path())))
    except Exception:
        pass
    candidates.extend(_KIRO_APP_CANDIDATES)
    for bundle in candidates:
        cli = bundle / "Contents" / "Resources" / "app" / "bin" / "code"
        if cli.exists():
            return cli
    return None


KIRO_CLI = _find_kiro_cli()
KIRO_PROCESS_NAME = "Kiro"
STATE_KEY = "kiro.kiroAgent"
ENTRIES_KEY = "sessionPanels.entries"
FOCUSED_KEY = "sessionPanels.focused"
KEY_CODE_L = 37
KEY_CODE_RIGHT = 124
KEY_CODE_LEFT = 123
MAX_STEPS = 40
_PERMISSION_MARKERS = (
    "not allowed assistive access",
    "not authorized",
    "-1743",
    "-25211",
    "osascript is not allowed",
)


@dataclass(frozen=True)
class Panels:
    db_path: str
    workspace: str
    entries: tuple[dict, ...]
    focused: str


@dataclass(frozen=True)
class JumpPlan:
    session_id: str
    found: bool = False
    title: str = ""
    workspace: str = ""
    location: str = "sidebar"
    index: int = -1
    focused_index: int = -1
    steps: int = 0
    can_walk: bool = False
    reason: str = ""


def tab_steps(
    entries: list[dict] | tuple[dict, ...], focused: str, target: str
) -> tuple[int, int, int]:
    """Steps along the tab strip from ``focused`` to ``target``.

    Only tabs sharing the target's location participate, because the chat tab
    shortcuts cycle within one panel. Returns ``(steps, index, focused_index)``
    where indices are ``-1`` when unknown.
    """
    items = [item for item in entries if isinstance(item, dict)]
    target_entry = next((item for item in items if item.get("id") == target), None)
    if target_entry is None:
        return 0, -1, -1
    location = target_entry.get("location", "sidebar")
    same = [item for item in items if item.get("location", "sidebar") == location]
    ids = [str(item.get("id", "")) for item in same]
    index = ids.index(target)
    focused_index = ids.index(focused) if focused in ids else -1
    if focused_index < 0:
        return 0, index, -1
    return index - focused_index, index, focused_index


def _workspace_folder(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    folder = payload.get("folder", "") if isinstance(payload, dict) else ""
    if not isinstance(folder, str) or not folder:
        return ""
    parsed = urlparse(folder)
    if parsed.scheme == "file":
        value = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            value = f"//{parsed.netloc}{value}"
        return value
    return unquote(folder)


def read_panels(db_path: str | Path) -> Panels | None:
    """Read one workspace's chat tab strip, read-only."""
    path = Path(db_path)
    connection = None
    try:
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=0.2
        )
        row = connection.execute(
            "SELECT value FROM ItemTable WHERE key = ?", (STATE_KEY,)
        ).fetchone()
    except (OSError, sqlite3.Error, ValueError):
        return None
    finally:
        if connection is not None:
            connection.close()
    if not row:
        return None
    raw = row[0]
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    entries = payload.get(ENTRIES_KEY)
    if not isinstance(entries, list):
        return None
    focused = payload.get(FOCUSED_KEY)
    return Panels(
        db_path=str(path),
        workspace=_workspace_folder(path.parent / "workspace.json"),
        entries=tuple(item for item in entries if isinstance(item, dict)),
        focused=str(focused or ""),
    )


class SessionJumper:
    """Focus a Kiro window and walk its chat tabs to one session."""

    def __init__(
        self,
        logger,
        workspace_storage_dir=KIRO_WORKSPACE_STORAGE_DIR,
        runner=None,
        sleeper=time.sleep,
        config: AppConfig | None = None,
        poster=None,
        pid_lookup=None,
    ) -> None:
        self.logger = logger
        self.workspace_storage_dir = Path(workspace_storage_dir)
        self.config = config or AppConfig()
        self._run = runner or self._default_runner
        self._sleep = sleeper
        self._poster = poster if poster is not None else KeyPoster(logger)
        self._pid_lookup = pid_lookup or presence.kiro_pid
        self._permission_warned = False

    # -- planning ------------------------------------------------------------
    def _all_panels(self) -> list[Panels]:
        found = []
        for db in sorted(glob.glob(str(self.workspace_storage_dir / "*" / "state.vscdb"))):
            panels = read_panels(db)
            if panels is not None:
                found.append(panels)
        return found

    def plan(self, session_id: str) -> JumpPlan:
        session_id = str(session_id or "").strip()
        if not session_id:
            return JumpPlan(session_id="", reason="缺少会话 ID")
        for panels in self._all_panels():
            entry = next(
                (item for item in panels.entries if item.get("id") == session_id), None
            )
            if entry is None:
                continue
            steps, index, focused_index = tab_steps(panels.entries, panels.focused, session_id)
            can_walk = focused_index >= 0 and abs(steps) <= MAX_STEPS
            return JumpPlan(
                session_id=session_id,
                found=True,
                title=str(entry.get("title", "")),
                workspace=panels.workspace,
                location=str(entry.get("location", "sidebar")),
                index=index,
                focused_index=focused_index,
                steps=steps,
                can_walk=can_walk,
                reason="" if can_walk else "无法定位当前标签，只能激活 Kiro",
            )
        return JumpPlan(session_id=session_id, reason="本地状态库中没有这个会话标签")

    # -- execution -----------------------------------------------------------
    def jump_async(self, session_id: str) -> None:
        """Run the jump off the Cocoa main thread; it shells out and waits."""
        threading.Thread(
            target=self.jump, args=(session_id,), name="kiro-session-jump", daemon=True
        ).start()

    def jump(self, session_id: str, activate: bool = True) -> bool:
        """Switch Kiro to one chat tab.

        ``activate=False`` keeps Kiro in the background: keys are posted to its
        pid, which needs no frontmost app, so whatever the user is typing in
        stays focused. Only used by auto-retry."""
        plan = self.plan(session_id)
        if activate:
            self._focus_window(plan.workspace)
        if not plan.found:
            self.logger.info("会话跳转降级为仅激活 Kiro：%s", plan.reason)
            return False
        if plan.steps == 0 and plan.focused_index >= 0:
            if activate:
                self.logger.info("会话「%s」已是当前标签，直接激活 Kiro", plan.title)
            else:
                self.logger.info("会话「%s」已是当前标签，无需切换（后台）", plan.title)
            return True
        if not plan.can_walk:
            self.logger.info("会话「%s」无法走位：%s", plan.title, plan.reason)
            return False
        self._sleep(0.45)
        # Quiet path first: keys posted to Kiro's pid are invisible to global
        # listeners such as an input method's voice shortcut.
        if self._walk_direct(plan.steps):
            if self._confirm(session_id):
                self.logger.info(
                    "已跳转到会话「%s」（%+d 个标签，直投 Kiro 进程）",
                    plan.title,
                    plan.steps,
                )
                return True
            # Kiro persists the focused tab lazily, so an unconfirmed jump is
            # usually just a lagging write. Never escalate to system-wide keys
            # here: those would be caught by input-method voice shortcuts.
            self.logger.info(
                "已向 Kiro 直投 %+d 个标签切换，但持久化状态暂未确认", plan.steps
            )
            return False
        if not activate:
            # System-wide keys would land in whatever the user is actually
            # typing in, so a background jump never escalates.
            self.logger.info("会话「%s」后台切换未成功，放弃（不使用系统级按键）", plan.title)
            return False
        if not self.config.jump_global_fallback:
            self.logger.info("会话「%s」无法直投按键，已按配置跳过全局按键", plan.title)
            return False
        self.logger.info("无法直投按键，改用系统级按键 %+d", plan.steps)
        if not self._walk(plan.steps):
            return False
        if self._confirm(session_id):
            self.logger.info("已跳转到会话「%s」（%+d 个标签）", plan.title, plan.steps)
            return True
        self.logger.info("会话「%s」跳转结果未能确认，请回到 Kiro 查看", plan.title)
        return False

    def _focus_window(self, workspace: str) -> None:
        """Bring the window that already hosts this workspace to the front."""
        if workspace and Path(workspace).exists():
            if KIRO_CLI is not None and KIRO_CLI.exists():
                code, _, err = self._run([str(KIRO_CLI), workspace])
                if code == 0:
                    return
                self.logger.debug("Kiro CLI 聚焦窗口失败：%s", err)
            code, _, err = self._run(["/usr/bin/open", "-b", KIRO_BUNDLE_ID, workspace])
            if code == 0:
                return
            self.logger.debug("open 聚焦工作区失败：%s", err)
        self._run(["/usr/bin/open", "-b", KIRO_BUNDLE_ID])

    def _walk_direct(self, steps: int) -> bool:
        """Send ⌘L and the tab shortcut to Kiro's process only."""
        if not self.config.jump_direct_keys or not self._poster.available:
            return False
        pid = self._pid_lookup()
        if not pid:
            return False
        key_code = KEY_CODE_RIGHT if steps > 0 else KEY_CODE_LEFT
        if not self._poster.post(pid, KEY_CODE_L, FLAG_COMMAND):
            return False
        self._sleep(0.18)
        for _ in range(abs(steps)):
            if not self._poster.post(pid, key_code, FLAG_COMMAND | FLAG_OPTION):
                return False
            self._sleep(0.07)
        return True

    def _walk(self, steps: int) -> bool:
        key_code = KEY_CODE_RIGHT if steps > 0 else KEY_CODE_LEFT
        script = "\n".join(
            [
                'tell application "System Events"',
                f'  tell process "{KIRO_PROCESS_NAME}" to set frontmost to true',
                "  delay 0.2",
                f"  key code {KEY_CODE_L} using {{command down}}",
                "  delay 0.15",
                f"  repeat {abs(steps)} times",
                f"    key code {key_code} using {{command down, option down}}",
                "    delay 0.08",
                "  end repeat",
                "end tell",
            ]
        )
        code, _, err = self._run(["/usr/bin/osascript", "-e", script], timeout=15)
        if code == 0:
            return True
        lowered = (err or "").lower()
        if any(marker in lowered for marker in _PERMISSION_MARKERS):
            if not self._permission_warned:
                self._permission_warned = True
                self.logger.warning(
                    "会话跳转需要辅助功能权限：请在 系统设置 > 隐私与安全性 > 辅助功能 "
                    "中允许桌宠使用的 Python 解释器，并在自动化中允许控制 Kiro"
                )
        else:
            self.logger.warning("会话标签走位失败：%s", (err or "").strip()[:200])
        return False

    def _confirm(self, session_id: str, attempts: int = 14, interval: float = 0.25) -> bool:
        for _ in range(attempts):
            self._sleep(interval)
            for panels in self._all_panels():
                if panels.focused == session_id:
                    return True
        return False

    def _default_runner(self, args: list[str], timeout: float = 10.0):
        try:
            result = subprocess.run(
                args, check=False, capture_output=True, text=True, timeout=timeout
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.logger.debug("执行失败 %s: %s", shlex.join(args), exc)
            return 1, "", str(exc)
        return result.returncode, result.stdout, result.stderr
