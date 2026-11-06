"""Post keystrokes to a single process instead of the whole system.

System-wide keystrokes (osascript / System Events) are visible to every global
event monitor. Input methods use exactly those monitors for their voice
shortcut — 豆包输入法 registers modifier chords such as ⌘⌥ — so sending the
chat-tab shortcut globally would start a voice recording. Events created here
are posted straight to one pid with ``CGEventPostToPid``, so other listeners
never see them. Only CoreGraphics via ctypes is required, no new dependency.
"""
from __future__ import annotations

import ctypes
import time

FLAG_SHIFT = 1 << 17
FLAG_CONTROL = 1 << 18
FLAG_OPTION = 1 << 19
FLAG_COMMAND = 1 << 20

_APPLICATION_SERVICES = (
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)
_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"


class KeyPoster:
    """Send key-down/key-up pairs to one process."""

    def __init__(self, logger=None) -> None:
        self.logger = logger
        self._services = None
        self._foundation = None
        self._load()

    def _load(self) -> None:
        try:
            services = ctypes.CDLL(_APPLICATION_SERVICES)
            foundation = ctypes.CDLL(_CORE_FOUNDATION)
            services.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
            services.CGEventCreateKeyboardEvent.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint16,
                ctypes.c_bool,
            ]
            services.CGEventSetFlags.restype = None
            services.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
            services.CGEventPostToPid.restype = None
            services.CGEventPostToPid.argtypes = [ctypes.c_int32, ctypes.c_void_p]
            foundation.CFRelease.restype = None
            foundation.CFRelease.argtypes = [ctypes.c_void_p]
        except (OSError, AttributeError) as exc:
            if self.logger is not None:
                self.logger.debug("CoreGraphics 键盘事件不可用：%s", exc)
            return
        self._services = services
        self._foundation = foundation

    @property
    def available(self) -> bool:
        return self._services is not None

    def post(self, pid: int, key_code: int, flags: int = 0, hold: float = 0.02) -> bool:
        """Post one key press to ``pid``; False when the API is unusable."""
        if not self.available or not pid or pid <= 0:
            return False
        services = self._services
        for is_down in (True, False):
            event = services.CGEventCreateKeyboardEvent(None, int(key_code), is_down)
            if not event:
                return False
            try:
                services.CGEventSetFlags(event, ctypes.c_uint64(int(flags)))
                services.CGEventPostToPid(ctypes.c_int32(int(pid)), event)
            finally:
                self._foundation.CFRelease(event)
            if is_down and hold > 0:
                time.sleep(hold)
        return True
