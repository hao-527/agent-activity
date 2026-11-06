"""Configuration, paths, settings persistence and logging for Kiro Desktop Pet."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .layout import DEFAULT_SCALE, SCALE_PRESETS, VALID_EDGES

HOME = Path.home()
# Derived from this file so the pet works from any install directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_SUPPORT_DIR = HOME / "Library" / "Application Support" / "Kiro Desktop Pet"
LOG_DIR = HOME / "Library" / "Logs" / "Kiro Desktop Pet"
SETTINGS_FILE = APP_SUPPORT_DIR / "settings.json"
STATUS_FILE = APP_SUPPORT_DIR / "status.json"
STATS_FILE = APP_SUPPORT_DIR / "stats.json"
SKINS_DIR = APP_SUPPORT_DIR / "pets"
LOCK_FILE = APP_SUPPORT_DIR / "pet.lock"
JUMP_REQUEST_FILE = APP_SUPPORT_DIR / "jump-request.json"
JUMP_REQUEST_SCRIPT = PROJECT_DIR / "scripts" / "request-jump.sh"
RETRY_REQUEST_FILE = APP_SUPPORT_DIR / "retry-request.json"
APP_LOG_FILE = LOG_DIR / "pet.log"
KIRO_LOG_GLOB = str(
    HOME
    / "Library"
    / "Application Support"
    / "Kiro"
    / "logs"
    / "*"
    / "window*"
    / "exthost"
    / "kiro.kiroAgent"
    / "Kiro Logs.log"
)

# Kiro CLI writes logs to ~/.kiro/logs/<timestamp>/kiro.log with the same format
# as the IDE extension logs, so the same LogClassifier can parse both.
KIRO_CLI_LOG_GLOB = str(HOME / ".kiro" / "logs" / "*" / "kiro.log")

KIRO_WORKSPACE_STORAGE_DIR = (
    HOME / "Library" / "Application Support" / "Kiro" / "User" / "workspaceStorage"
)
KIRO_LEGACY_SESSIONS_DIR = (
    HOME
    / "Library"
    / "Application Support"
    / "Kiro"
    / "User"
    / "globalStorage"
    / "kiro.kiroagent"
    / "workspace-sessions"
)
# Kiro appends turn_start/turn_end payloads per session here; used as the
# authoritative "is this session still running" repair signal.
KIRO_SESSION_ARCHIVE_DIR = HOME / ".kiro" / "sessions"
KIRO_BUNDLE_ID = "dev.kiro.desktop"
LAUNCHD_LABEL = "com.kiro-desktop-pet"
# Older personal labels to clean up on install; empty for public builds.
LEGACY_LAUNCHD_LABELS: tuple[str, ...] = ()
LAUNCHD_PLIST = HOME / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
APPEARANCE_MODES = ("auto", "dark", "light")


@dataclass(frozen=True)
class AppConfig:
    poll_interval: float = 0.65
    rescan_interval: float = 5.0
    bootstrap_max_age: float = 30.0 * 60.0
    bootstrap_bytes: int = 768 * 1024
    success_hold: float = 28.0
    error_hold: float = 180.0
    cancelled_hold: float = 25.0
    flash_hold: float = 7.0
    # The session archive probe now retires finished sessions within seconds,
    # so this is only a backstop for sessions Kiro never archived.
    running_stale_timeout: float = 5.0 * 60.0
    activity_probe_interval: float = 4.0
    # A running session is only retired on archive evidence once its log has
    # been quiet this long, unless the archive itself is newer than the log.
    activity_confirm_delay: float = 20.0
    session_retention: float = 24.0 * 60.0 * 60.0
    max_visible_sessions: int = 8
    animation_interval: float = 0.14
    idle_animation_interval: float = 0.26
    docked_animation_interval: float = 0.6
    compact_rows: int = 3
    detail_rows: int = 8
    collapsed_rows: int = 3
    auto_peek_seconds: float = 4.5
    notify_success: bool = True
    # 只保留任务完成通知（success/finished）；异常、连接中断、取消、
    # 待确认、长时运行这类非完成通知全部关闭。
    notify_error: bool = False
    # 只在"任务真正执行完毕"(success)时提醒；Kiro 会话存档推断出的
    # "会话已结束"(finished/inferred-finish) 通知关闭，避免多余的收尾提醒。
    notify_inferred_finish: bool = False
    notify_interrupt: bool = False
    notify_cancel: bool = False
    notify_approval: bool = False
    notify_long_run: bool = False
    notify_max_age: float = 90.0
    notify_debounce: float = 8.0
    # Completions are one per turn, so a session you keep talking to would
    # otherwise ping on every answer. Longer gap plus a frontmost check.
    notify_completion_debounce: float = 20.0
    # Last resort against floods: no more than this many in the window.
    notify_flood_window: float = 180.0
    notify_flood_max: int = 6
    # Connection interrupts used to nag every 25s up to 8 times, ignoring
    # quiet hours. That is the "same error keeps yelling at me" complaint.
    # Now a single interrupt fires exactly once (max_repeats=1, so service()
    # never re-sends), and the same session is silenced for a long rearm
    # window so a session that keeps dropping does not spam.
    notify_repeat_interval: float = 25.0
    notify_max_repeats: int = 1
    notify_rearm: float = 600.0
    notify_frontmost_check: bool = False
    notify_quiet_start: int = -1
    notify_quiet_end: int = -1
    notify_success_sound: str = "Glass"
    notify_error_sound: str = "Basso"
    notify_interrupt_sound: str = "Sosumi"
    notify_cancel_sound: str = "Pop"
    notify_approval_sound: str = "Funk"
    notify_long_run_sound: str = "Tink"
    long_run_threshold: float = 15.0 * 60.0
    title_rescan_interval: float = 3.0
    stats_flush_interval: float = 30.0
    edge_snap_distance: float = 48.0
    drag_settle_delay: float = 0.32
    edge_tab_visible: float = 36.0
    status_refresh_interval: float = 0.7
    jump_direct_keys: bool = True
    # Auto-resume a session whose model stream dropped: Kiro stops dead on
    # "Your connection was interrupted" and waits for a human to say continue.
    # 关闭：不再对连接中断做任何提醒或自动重试，避免中断/重试类通知。
    retry_on_interrupt: bool = False
    retry_delay: float = 3.0
    retry_max_attempts: int = 10
    retry_prompt: str = "继续"
    # Kiro is Electron and ignores keys posted to it while it is not frontmost:
    # ten background attempts appended nothing to the session archive. So the
    # retry has to activate Kiro, and the cost is paid back two ways: wait for a
    # pause in the user's typing, and hand the front back afterwards.
    retry_background: bool = False
    retry_activate_fallback: bool = True
    # Don't grab focus mid-keystroke: postpone until input has been idle.
    retry_idle_guard: float = 4.0
    # How long the guard may hold a retry back before giving up on politeness.
    retry_idle_max_wait: float = 120.0
    retry_restore_focus: bool = True
    jump_global_fallback: bool = True
    presence_refresh_interval: float = 2.5


@dataclass
class UserSettings:
    x: float | None = None
    y: float | None = None
    always_on_top: bool = True
    show_bubble: bool = True
    monitor_paused: bool = False
    notifications_enabled: bool = True
    pet_visible: bool = True
    docked_edge: str = ""
    pet_scale: str = DEFAULT_SCALE
    skin: str = "pixel"
    detail_expanded: bool = False
    dock_offset: float | None = None
    auto_peek: bool = True
    hotkey_enabled: bool = False
    auto_retry: bool = True
    notify_sound_enabled: bool = True
    appearance: str = "auto"


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = path
        self.settings = self._load()

    def _load(self) -> UserSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            known = {key: raw[key] for key in UserSettings.__dataclass_fields__ if key in raw}
            for flag in (
                "always_on_top",
                "show_bubble",
                "monitor_paused",
                "notifications_enabled",
                "pet_visible",
                "detail_expanded",
                "hotkey_enabled",
                "auto_peek",
                "auto_retry",
                "notify_sound_enabled",
            ):
                if flag in known:
                    known[flag] = bool(known[flag])
            if known.get("docked_edge", "") not in ("",) + tuple(VALID_EDGES):
                known["docked_edge"] = ""
            if known.get("pet_scale", DEFAULT_SCALE) not in SCALE_PRESETS:
                known["pet_scale"] = DEFAULT_SCALE
            if known.get("appearance", "auto") not in APPEARANCE_MODES:
                known["appearance"] = "auto"
            return UserSettings(**known)
        except (OSError, ValueError, TypeError):
            return UserSettings()

    def save(self) -> None:
        atomic_write_json(self.path, asdict(self.settings))


def ensure_runtime_dirs() -> None:
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SKINS_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def configure_logging() -> logging.Logger:
    ensure_runtime_dirs()
    logger = logging.getLogger("kiro_pet")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = RotatingFileHandler(
        APP_LOG_FILE, maxBytes=1_500_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger
