"""Automatically resume a Kiro session whose model stream was interrupted.

Kiro reports a dropped stream as ``userFacingSessionErrorMessage: "Your
connection was interrupted."`` and then just sits there: the turn is over, the
answer is missing, and nothing continues until a human comes back and asks it
to. That wait is exactly what this pet exists to remove, so an interrupt is
retried by doing what the human would do: jump to that session and send a short
"continue" prompt.

Retrying is deliberately narrow:

* only interrupt-flavoured errors, never real execution failures or cancels
* only while Kiro is running, and only for the session that was interrupted
* any sign of progress in that session cancels the remaining attempts
* a hard attempt cap, after which the user is notified instead
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time

import json

from . import presence
from .config import RETRY_REQUEST_FILE
from .events import EventType
from .keys import FLAG_COMMAND, KeyPoster

KEY_CODE_RETURN = 36
KEY_CODE_V = 9
KEY_CODE_A = 0
KEY_CODE_L = 37


@dataclass
class RetryState:
    session_id: str
    title: str
    attempts: int = 0
    next_at: float = 0.0
    last_attempt_at: float = 0.0
    interrupted_at: float = 0.0
    recovered: bool = False
    held_since: float = 0.0
    history: list[float] = field(default_factory=list)


def input_idle_seconds() -> float:
    """Seconds since the user last touched keyboard or mouse.

    Grabbing focus in the middle of someone typing in a browser sends their
    keystrokes to Kiro, so a retry waits for a gap instead."""
    try:
        import Quartz

        return float(
            Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateCombinedSessionState,
                Quartz.kCGAnyInputEventType,
            )
        )
    except Exception:
        return 1e9  # unknown: never block a retry on a missing API


class _FrontmostApp:
    """Remember who owned the front so it can be handed back."""

    def __init__(self, logger=None) -> None:
        self.logger = logger
        self._app = None

    def remember(self) -> str:
        try:
            from AppKit import NSWorkspace

            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return ""
            name = str(app.localizedName() or "")
            self._app = None if name == "Kiro" else app
            return name
        except Exception as exc:
            if self.logger is not None:
                self.logger.debug("读取前台 App 失败：%s", exc)
            return ""

    def restore(self) -> str:
        app, self._app = self._app, None
        if app is None:
            return ""
        try:
            from AppKit import NSApplicationActivateIgnoringOtherApps

            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            return str(app.localizedName() or "")
        except Exception as exc:
            if self.logger is not None:
                self.logger.debug("归还前台失败：%s", exc)
            return ""


class RetryCoordinator:
    """Schedule and perform continue-prompts for interrupted sessions."""

    def __init__(
        self,
        config,
        settings,
        logger,
        jumper,
        notifier=None,
        poster: KeyPoster | None = None,
        clipboard=None,
        clock=None,
        activity_probe=None,
    ) -> None:
        self.config = config
        self.settings = settings
        self.logger = logger
        self.jumper = jumper
        self.notifier = notifier
        self.poster = poster or KeyPoster(logger)
        self.clipboard = clipboard or _Clipboard(logger)
        self.frontmost = _FrontmostApp(logger)
        # Kiro's own archive is the authority on whether a turn is still open.
        self.activity_probe = activity_probe
        self.idle_probe = input_idle_seconds
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._pending: dict[str, RetryState] = {}
        self._recent_success: list[tuple[str, float, int]] = []

    # -- inputs ---------------------------------------------------------------
    def will_handle(self, event) -> bool:
        """Auto-retry has been removed. Always return False so interrupts
        are handled by the notifier (alert the user, never auto-send)."""
        return False

    def note_event(self, event) -> None:
        """Feed every live event: interrupts schedule, progress cancels."""
        if event.kind == EventType.ERROR and getattr(event, "interrupt", False):
            self._schedule(event)
            return
        # Only a genuinely new turn counts as recovery. Trailing ACTIVITY lines
        # (yield/resume, tool output) keep arriving after a stream drops, and
        # treating those as recovery silently cancelled the pending retry.
        if event.kind in (EventType.START, EventType.REQUEST, EventType.SUCCESS):
            self._note_progress(event)

    def _schedule(self, event) -> None:
        """Auto-retry removed: do nothing, let notifier alert the user."""
        return

    def _note_progress(self, event) -> None:
        with self._lock:
            state = self._pending.get(event.session_id)
            if state is None:
                return
            if state.attempts == 0:
                # A new turn before we even tried means it resumed on its own.
                # Never drop this silently: a lost retry used to be invisible.
                if event.timestamp > state.interrupted_at:
                    self._pending.pop(event.session_id, None)
                    self.logger.info(
                        "会话已自行继续，取消待执行的重试：%s",
                        state.title or state.session_id,
                    )
                return
            # The session moved again after a retry: treat it as recovered.
            self._pending.pop(event.session_id, None)
            self.logger.info(
                "会话已恢复运行，停止自动重试（共重试 %d 次）：%s",
                state.attempts,
                state.title or state.session_id,
            )
            self._recent_success.append((state.title or state.session_id, self._clock(), state.attempts))
            del self._recent_success[:-10]
            if self.notifier is not None:
                self.notifier.notify_retry_recovered(
                    state.title or state.session_id, state.attempts
                )

    # -- scheduling -----------------------------------------------------------
    def consume_request(self) -> bool:
        """Run a retry asked for by scripts/test-retry.sh.

        Key posting only works from a process the user granted Accessibility
        to, which in practice is this launchd-started pet and not a shell. So
        the channel can only be exercised from in here, and dry runs fill the
        chat box without sending so nothing is posted to a live chat."""
        try:
            raw = RETRY_REQUEST_FILE.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return False
        try:
            RETRY_REQUEST_FILE.unlink()
        except OSError:
            pass
        try:
            payload = json.loads(raw)
        except ValueError:
            return False
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            return False
        send = bool(payload.get("send"))
        prompt = str(payload.get("prompt") or "") or self.config.retry_prompt
        self.logger.info(
            "收到重试测试请求：会话 %s，%s",
            session_id,
            "填入并发送" if send else "只填入不发送（演练）",
        )
        ok = self.send_continue(session_id, prompt=prompt, send=send)
        self.logger.info("重试测试请求执行结果：%s", "成功" if ok else "失败")
        return ok

    def tick(self, now: float | None = None) -> None:
        self.consume_request()
        now = now if now is not None else self._clock()
        if not self.enabled:
            with self._lock:
                self._pending.clear()
            return
        with self._lock:
            due = [
                state
                for state in self._pending.values()
                if state.next_at and now >= state.next_at
            ]
        for state in due:
            self._attempt(state, now)

    def _attempt(self, state: RetryState, now: float) -> None:
        if self.activity_probe is not None:
            probe = self.activity_probe.sample(state.session_id)
            if probe is not None and probe.running:
                with self._lock:
                    self._pending.pop(state.session_id, None)
                self.logger.info("会话存档显示已在运行，取消重试：%s", state.title or state.session_id)
                if state.attempts and self.notifier is not None:
                    self.notifier.notify_retry_recovered(state.title or state.session_id, state.attempts)
                return
        guard = float(getattr(self.config, "retry_idle_guard", 0.0) or 0.0)
        if guard > 0 and not getattr(self.config, "retry_background", False):
            idle = self.idle_probe()
            if idle < guard:
                if not state.held_since:
                    state.held_since = now
                    self.logger.info(
                        "你正在操作，暂缓自动重试：%s", state.title or state.session_id
                    )
                waited = now - state.held_since
                if waited < float(getattr(self.config, "retry_idle_max_wait", 120.0)):
                    with self._lock:
                        state.next_at = now + 1.0
                    return
                self.logger.info(
                    "已等待 %.0f 秒仍在操作，仍然执行重试：%s",
                    waited,
                    state.title or state.session_id,
                )
            state.held_since = 0.0
        if not presence.kiro_running():
            # Nothing to talk to; wait instead of burning an attempt.
            with self._lock:
                state.next_at = now + self.config.retry_delay
            return
        with self._lock:
            if state.attempts >= self.config.retry_max_attempts:
                self._pending.pop(state.session_id, None)
                self.logger.warning(
                    "自动重试 %d 次仍未恢复，交回人工：%s",
                    state.attempts,
                    state.title or state.session_id,
                )
                if self.notifier is not None:
                    self.notifier.notify_retry_exhausted(
                        state.title or state.session_id,
                        state.attempts,
                        state.session_id,
                    )
                return
            state.attempts += 1
            state.last_attempt_at = now
            state.next_at = now + self.config.retry_delay
            attempt = state.attempts
            state.history.append(now)
            del state.history[:-20]

        label = state.title or state.session_id
        self.logger.info("自动重试第 %d/%d 次：%s", attempt, self.config.retry_max_attempts, label)
        # Deliberately silent while retrying: only the outcome is worth a
        # notification, and the menu already shows progress live.
        if not self.send_continue(state.session_id):
            self.logger.warning("自动重试第 %d 次未能投递：%s", attempt, label)

    # -- the actual keystrokes ------------------------------------------------
    def send_continue(self, session_id: str, prompt: str = "", send: bool = True) -> bool:
        """Focus the session and send the continue prompt. Returns False on setup failure.

        The text goes through the clipboard: CGEvent keystrokes cannot type CJK
        reliably, and the original clipboard is put back afterwards.
        """
        text = prompt or self.config.retry_prompt
        background = bool(getattr(self.config, "retry_background", False))
        restore_focus = bool(getattr(self.config, "retry_restore_focus", True)) and not background
        previous = self.frontmost.remember() if restore_focus else ""
        if not self.jumper.jump(session_id, activate=not background):
            if background and getattr(self.config, "retry_activate_fallback", False):
                self.logger.info("后台切换失败，改用激活 Kiro 的方式重试：%s", session_id)
                if not self.jumper.jump(session_id, activate=True):
                    self.logger.warning("自动重试无法定位会话，放弃本次投递：%s", session_id)
                    return False
            else:
                self.logger.warning("自动重试无法定位会话，放弃本次投递：%s", session_id)
                return False
        pid = presence.kiro_pid()
        if not pid or not self.poster.available:
            return False
        restored = self.clipboard.replace(text)
        try:
            # No ⌘L here: the jump already focused this tab's chat input, and a
            # second ⌘L walks the focus to a neighbouring chat, which would send
            # the continue prompt to the wrong session.
            # Select first so leftover text in the box is replaced rather than
            # appended: otherwise a half-typed draft would be sent along with it.
            if not self.poster.post(pid, KEY_CODE_A, FLAG_COMMAND):
                return False
            time.sleep(0.15)
            if not self.poster.post(pid, KEY_CODE_V, FLAG_COMMAND):
                return False
            time.sleep(0.25)
            if send and not self.poster.post(pid, KEY_CODE_RETURN):
                return False
        finally:
            if restored:
                time.sleep(0.4)
                self.clipboard.restore()
            if restore_focus and previous and previous != "Kiro":
                back = self.frontmost.restore()
                if back:
                    self.logger.info("已把前台还给「%s」", back)
        return True

    # -- status ---------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(
            getattr(self.settings.settings, "auto_retry", True)
            and self.config.retry_on_interrupt
        )

    def status_line(self, now: float | None = None) -> str:
        now = now if now is not None else self._clock()
        with self._lock:
            pending = [
                (state.title or state.session_id, state.attempts, max(0.0, state.next_at - now))
                for state in self._pending.values()
            ]
            recent = list(self._recent_success)
        if pending:
            label, attempts, wait = pending[0]
            return f"自动重试中：{label}（第 {attempts}/{self.config.retry_max_attempts} 次，{wait:.0f} 秒后）"
        for label, when, attempts in reversed(recent):
            if now - when <= 600:
                return f"已自动重试 {attempts} 次并恢复：{label}"
        return ""


class _Clipboard:
    """Save/replace/restore the general pasteboard as plain text."""

    def __init__(self, logger=None) -> None:
        self.logger = logger
        self._saved: str | None = None

    def replace(self, text: str) -> bool:
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString

            board = NSPasteboard.generalPasteboard()
            self._saved = board.stringForType_(NSPasteboardTypeString)
            board.clearContents()
            board.setString_forType_(text, NSPasteboardTypeString)
            return True
        except Exception as exc:  # never let clipboard trouble block a retry
            if self.logger is not None:
                self.logger.debug("剪贴板写入失败：%s", exc)
            return False

    def restore(self) -> None:
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString

            board = NSPasteboard.generalPasteboard()
            board.clearContents()
            if self._saved:
                board.setString_forType_(self._saved, NSPasteboardTypeString)
        except Exception as exc:
            if self.logger is not None:
                self.logger.debug("剪贴板恢复失败：%s", exc)
        finally:
            self._saved = None
