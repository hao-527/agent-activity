"""macOS lifecycle notifications for Kiro Desktop Pet.

The pet only reads Kiro logs locally; this module turns the reliable
lifecycle events emitted by :mod:`kiro_pet.events` into native macOS
notifications. Every collaborator (sender, frontmost probe, clock) is
injectable so the behaviour can be exercised without touching the system.
"""
from __future__ import annotations
from collections import deque

import logging
import os
import re
import shlex
import subprocess
import time
from datetime import datetime

from .config import JUMP_REQUEST_SCRIPT, KIRO_BUNDLE_ID, AppConfig, SettingsStore
from .events import EventType, LogEvent
from .layout import format_duration

# category -> (title, notification group)
_CATEGORY_META = {
    "success": ("✅ Kiro 执行完毕", "kiro-pet-success"),
    "error": ("❗️ Kiro 执行异常", "kiro-pet-error"),
    "cancel": ("⏹️ Kiro 已取消", "kiro-pet-cancel"),
    "approval": ("⚠️ Kiro 需要确认", "kiro-pet-approval"),
    "long_run": ("⏳ Kiro 仍在执行", "kiro-pet-longrun"),
    "finished": ("🏁 Kiro 会话已结束", "kiro-pet-finished"),
    "retry": ("🔁 Kiro 连接中断，正在自动重试", "kiro-pet-retry"),
    "retry_done": ("✅ Kiro 已自动恢复", "kiro-pet-retry"),
    "retry_failed": ("❗️ Kiro 自动重试未成功", "kiro-pet-retry"),
}
# One completion per turn is normal, so these are throttled harder and stay
# quiet while the user is already looking at Kiro.
_COMPLETION_CATEGORIES = ("success", "finished")
# Losing these to a flood guard would defeat the point of the pet.
_FLOOD_EXEMPT = ("error", "retry_failed", "approval")
_QUIET_EXEMPT = ()

_TERMINAL_NOTIFIER_PATHS = (
    "/opt/homebrew/bin/terminal-notifier",
    "/usr/local/bin/terminal-notifier",
)
_SESSION_ID_RE = re.compile(r"^sess_[A-Za-z0-9-]{4,80}$")


class Notifier:
    """Route lifecycle events to macOS notifications with sane throttling."""

    def __init__(self, config, settings, logger, sender=None, frontmost=None, clock=None):
        self.config = config
        self.settings = settings
        self.logger = logger
        self._sender = sender or self._default_send
        self._frontmost = frontmost or self._kiro_frontmost
        self._clock = clock or time.time
        self._armed = False
        # de-bounce map keyed by (session_id, category) -> last-send time
        self._last: dict[tuple[str, str], float] = {}
        # Timestamps of everything sent, for the flood guard.
        self._sent: deque[float] = deque(maxlen=30)
        # one long-run reminder per session run
        self._long_seen: set[tuple[str, int]] = set()
        self._long_seen_cleanup: float = 0.0

    # -- lifecycle -----------------------------------------------------------
    def arm(self) -> None:
        """Enable notifications once the bootstrap replay has finished."""
        self._armed = True

    def handle(self, event, now=None) -> None:
        """Process a single lifecycle event and maybe emit a notification."""
        now = now if now is not None else self._clock()
        if not self.settings.settings.notifications_enabled or not self._armed:
            return

        # Freshness gate: drop startup replay and historical lines that a new
        # Kiro window replays, and guard against clock skew from the future.
        ts = event.timestamp
        if ts == 0 or (now - ts) > self.config.notify_max_age or (now - ts) < -5:
            return

        if event.kind == EventType.SUCCESS and self.config.notify_success:
            category = "success"
        elif event.kind == EventType.ERROR and not event.interrupt and self.config.notify_error:
            category = "error"
        elif event.kind == EventType.CANCEL and self.config.notify_cancel:
            category = "cancel"
        elif event.kind == EventType.APPROVAL and self.config.notify_approval:
            category = "approval"
        else:
            return

        if self.in_quiet_hours(now) and category not in _QUIET_EXEMPT:
            return

        # No point announcing a finished turn to someone already watching it.
        if (
            category in _COMPLETION_CATEGORIES
            and self.config.notify_frontmost_check
            and self._frontmost()
        ):
            return

        # Merge the repeated log lines a single failure/success can produce.
        key = (event.session_id, category)
        gap = (
            self.config.notify_completion_debounce
            if category in _COMPLETION_CATEGORIES
            else self.config.notify_debounce
        )
        if now - self._last.get(key, 0.0) < gap:
            return
        self._last[key] = now
        # A success notification makes the later inferred-finish redundant;
        # stamp the "finished" key so notify_inferred_finish() won't double-fire.
        if category == "success":
            self._last[(event.session_id, "finished")] = now
        self._dispatch(category, self._time_label(event.timestamp, now), event)

    def notify_long_run(self, view, now=None) -> bool:
        """Remind once that a single execution has been running for a long time."""
        now = now if now is not None else self._clock()
        if (
            not self.settings.settings.notifications_enabled
            or not self._armed
            or not self.config.notify_long_run
        ):
            return False
        key = (view.session_id, int(view.started_at or 0))
        if key in self._long_seen:
            return False
        self._long_seen.add(key)
        if self.in_quiet_hours(now):
            return False
        if self.config.notify_frontmost_check and self._frontmost():
            return False
        label = view.title or view.workspace or view.model or f"会话 {view.short_id}"
        elapsed = format_duration(max(0.0, now - (view.started_at or now)))
        self._dispatch(
            "long_run",
            self._time_label(now, now),
            None,
            f"{label} 已运行 {elapsed}",
            session_id=view.session_id,
        )
        return True

    def notify_inferred_finish(self, view, now=None) -> bool:
        """Announce a completion whose terminal log line never arrived.

        Kiro's ``Execution succeeded`` line carries no session id, so it can be
        missed or attributed elsewhere. The session archive still says the turn
        ended, and that repair must be user visible: otherwise the one run the
        pet failed to report is also the one run nobody gets told about. The
        outcome is unknown here, so the wording stays neutral instead of
        claiming success.
        """
        now = now if now is not None else self._clock()
        if (
            not self.settings.settings.notifications_enabled
            or not self._armed
            or not self.config.notify_inferred_finish
        ):
            return False
        anchor = view.completed_at or view.updated_at or 0.0
        # Never fire for backfilled history: same freshness rule as log events.
        if anchor == 0 or (now - anchor) > self.config.notify_max_age:
            return False
        if self.in_quiet_hours(now):
            return False
        if self.config.notify_frontmost_check and self._frontmost():
            return False
        key = (view.session_id, "finished")
        if now - self._last.get(key, 0.0) < self.config.notify_completion_debounce:
            return False
        self._last[key] = now
        label = view.title or view.workspace or view.model or f"会话 {view.short_id}"
        self._dispatch(
            "finished",
            self._time_label(anchor, now),
            None,
            label,
            session_id=view.session_id,
        )
        return True

    def notify_retry_started(self, label: str, session_id: str = "") -> bool:
        """Tell the user a dropped stream is being resumed automatically."""
        return self._retry_notice("retry", label, session_id)

    def notify_retry_recovered(self, label: str, attempts: int) -> bool:
        return self._retry_notice("retry_done", f"{label} · 重试 {attempts} 次后恢复")

    def notify_retry_exhausted(self, label: str, attempts: int, session_id: str = "") -> bool:
        return self._retry_notice(
            "retry_failed", f"{label} · 已重试 {attempts} 次仍未恢复", session_id
        )

    def _retry_notice(self, category: str, subtitle: str, session_id: str = "") -> bool:
        now = self._clock()
        if not self.settings.settings.notifications_enabled or not self._armed:
            return False
        if category != "retry_failed" and self.in_quiet_hours(now):
            return False
        key = (session_id or subtitle, category)
        if now - self._last.get(key, 0.0) < self.config.notify_debounce:
            return False
        self._last[key] = now
        self._dispatch(
            category,
            self._time_label(now, now),
            None,
            subtitle,
            session_id=session_id,
        )
        return True

    def service(self, now=None) -> None:
        """Drive the persistent CRITICAL reminder from the monitor loop."""
        now = now if now is not None else self._clock()
        # Periodically prune _long_seen to avoid unbounded growth (every 30 min)
        if now - self._long_seen_cleanup > 1800:
            self._long_seen_cleanup = now
            cutoff = int(now - 7200)  # drop entries older than 2 hours
            self._long_seen = {k for k in self._long_seen if k[1] > cutoff}
        return

    def send_hint(self, subtitle: str, message: str) -> None:
        """A one-off UI hint, unrelated to any session event."""
        # 尊重"通知提示音"开关：关闭时以空 sound 静音发送。
        sound = self.config.notify_success_sound
        if not getattr(self.settings.settings, "notify_sound_enabled", True):
            sound = ""
        try:
            self._sender(
                "Kiro 桌宠",
                subtitle,
                message,
                sound,
                "kiro-pet-hint",
                KIRO_BUNDLE_ID,
                "",
            )
            self.logger.info("已发送提示通知：%s", subtitle)
        except Exception as exc:
            self.logger.warning("发送提示通知失败：%s", exc)

    def send_test(self, category="success") -> None:
        """Send one notification immediately, ignoring armed / enabled state."""
        now = self._clock()
        self._dispatch(category, self._time_label(now, now), None)

    def in_quiet_hours(self, now=None) -> bool:
        """True inside the configured do-not-disturb window."""
        start = int(self.config.notify_quiet_start)
        end = int(self.config.notify_quiet_end)
        if start < 0 or end < 0 or start == end:
            return False
        now = now if now is not None else self._clock()
        hour = datetime.fromtimestamp(now).hour
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    # -- composition & sending ----------------------------------------------
    def _flooding(self, category: str, now: float) -> bool:
        """True when this notification would exceed the burst budget."""
        window = self.config.notify_flood_window
        while self._sent and now - self._sent[0] > window:
            self._sent.popleft()
        if category in _FLOOD_EXEMPT:
            return False
        if len(self._sent) >= self.config.notify_flood_max:
            self.logger.info(
                "%.0f 秒内已发 %d 条通知，合并掉这条 %s",
                window,
                len(self._sent),
                category,
            )
            return True
        return False

    def _dispatch(
        self,
        category,
        when_label,
        event,
        subtitle_override: str = "",
        session_id: str = "",
    ) -> None:
        if self._flooding(category, self._clock()):
            return
        self._sent.append(self._clock())
        title, group = _CATEGORY_META[category]
        subtitle, sound = self._subtitle_sound(category, event)
        # 通知提示音开关：关闭时静音发送（空 sound 即无声），通知本身照发。
        if not getattr(self.settings.settings, "notify_sound_enabled", True):
            sound = ""
        if subtitle_override:
            subtitle = subtitle_override
        if not session_id and event is not None:
            session_id = getattr(event, "session_id", "") or ""
        jumpable = bool(self._jump_command(session_id))
        message = f"时间 {when_label}，点我" + ("跳到这个会话" if jumpable else "跳回 Kiro")
        try:
            self._sender(title, subtitle, message, sound, group, KIRO_BUNDLE_ID, session_id)
            self.logger.info("已发送 %s 通知：%s", category, subtitle)
        except Exception as exc:  # never let a notification kill the monitor
            self.logger.warning("发送 %s 通知失败：%s", category, exc)

    def _subtitle_sound(self, category, event) -> tuple[str, str]:
        if category == "success":
            subtitle = ""
            if event is not None:
                subtitle = event.title or event.workspace or event.model
            return subtitle or "当前任务已结束", self.config.notify_success_sound
        if category == "error":
            detail = event.detail if event is not None else ""
            return detail or "执行出现异常", self.config.notify_error_sound
        if category == "cancel":
            return "本次执行已中止", self.config.notify_cancel_sound
        if category == "long_run":
            return "任务仍在执行中", self.config.notify_long_run_sound
        if category == "approval":
            detail = event.detail if event is not None else ""
            return detail or "有操作待批准", self.config.notify_approval_sound
        return "有敏感操作待批准", self.config.notify_approval_sound

    @staticmethod
    def _time_label(timestamp, now) -> str:
        value = timestamp if timestamp else now
        return datetime.fromtimestamp(value).strftime("%H:%M:%S")

    # -- default system integrations ----------------------------------------
    @staticmethod
    def _jump_command(session_id: str) -> str:
        """Click action that asks the pet to jump to this exact session."""
        if not _SESSION_ID_RE.match(str(session_id or "")):
            return ""
        if not JUMP_REQUEST_SCRIPT.exists():
            return ""
        return f"{shlex.quote(str(JUMP_REQUEST_SCRIPT))} {shlex.quote(str(session_id))}"

    def _default_send(
        self, title, subtitle, message, sound, group, activate_bundle, session_id=""
    ) -> None:
        binary = self._terminal_notifier_path()
        if binary:
            args = [
                binary,
                "-title", title,
                "-subtitle", subtitle,
                "-message", message,
                "-group", group,
                "-ignoreDnD",
            ]
            # sound 为空表示静音：不传 -sound 才是可靠静音，
            # 传 -sound "" 是未定义行为，部分版本会退回默认提示音。
            if sound:
                args += ["-sound", sound]
            command = self._jump_command(session_id)
            # -execute replaces -activate: the helper writes a jump request and
            # the pet process performs the tab walk with its own permission.
            args += ["-execute", command] if command else ["-activate", activate_bundle]
            try:
                subprocess.run(args, check=False)
                return
            except OSError as exc:
                self.logger.debug("terminal-notifier 调用失败，回退 osascript：%s", exc)
        self._osascript_notify(title, subtitle, message, sound)

    @staticmethod
    def _terminal_notifier_path():
        for path in _TERMINAL_NOTIFIER_PATHS:
            if os.path.exists(path):
                return path
        return None

    def _osascript_notify(self, title, subtitle, message, sound) -> None:
        def esc(value: str) -> str:
            return str(value).replace("\\", "\\\\").replace('"', '\\"')

        script = (
            f'display notification "{esc(message)}" '
            f'with title "{esc(title)}" '
            f'subtitle "{esc(subtitle)}"'
        )
        # sound 为空表示静音：省略 sound name 子句，避免 osascript 回退到默认提示音。
        if sound:
            script += f' sound name "{esc(sound)}"' 
        try:
            subprocess.run(["/usr/bin/osascript", "-e", script], check=False)
        except OSError as exc:
            self.logger.debug("osascript 通知失败：%s", exc)

    def _kiro_frontmost(self) -> bool:
        script = (
            'tell application "System Events" to get bundle identifier of first '
            "application process whose frontmost is true"
        )
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.stdout.strip() == KIRO_BUNDLE_ID
