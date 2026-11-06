"""Detect whether Kiro itself is running.
Called from the Cocoa main thread only, so AppKit stays single-threaded.
Without this the pet could never show a real offline state: log files stay
on disk after Kiro quits, so the log count alone never drops to zero.
"""
from __future__ import annotations
import time
from AppKit import NSRunningApplication, NSWorkspace
from .config import KIRO_BUNDLE_ID

_FALLBACK_NAMES = ("Kiro",)

# Simple TTL cache to avoid hammering NSRunningApplication every 0.65s
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 1.0  # seconds


def _cached(key: str, ttl: float = _CACHE_TTL):
    """Return cached value if fresh, else None."""
    entry = _cache.get(key)
    if entry is not None and time.time() - entry[0] < ttl:
        return entry[1]
    return None


def _store(key: str, value):
    _cache[key] = (time.time(), value)
    return value


def kiro_running(bundle_id: str = KIRO_BUNDLE_ID) -> bool:
    cached = _cached("running")
    if cached is not None:
        return cached
    try:
        if NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id):
            return _store("running", True)
    except Exception:
        pass
    try:
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if (app.bundleIdentifier() or "") == bundle_id:
                return _store("running", True)
            if (app.localizedName() or "") in _FALLBACK_NAMES:
                return _store("running", True)
    except Exception:
        pass
    return _store("running", False)


def kiro_pid(bundle_id: str = KIRO_BUNDLE_ID) -> int:
    """Pid of the running Kiro app, or 0. NSRunningApplication is thread-safe."""
    cached = _cached("pid")
    if cached is not None:
        return cached
    try:
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if apps:
            return _store("pid", int(apps[0].processIdentifier()))
    except Exception:
        pass
    try:
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if (app.bundleIdentifier() or "") == bundle_id or (
                app.localizedName() or ""
            ) in _FALLBACK_NAMES:
                return _store("pid", int(app.processIdentifier()))
    except Exception:
        pass
    return _store("pid", 0)


def kiro_frontmost(bundle_id: str = KIRO_BUNDLE_ID) -> bool:
    cached = _cached("frontmost", ttl=0.5)
    if cached is not None:
        return cached
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
    except Exception:
        return _store("frontmost", False)
    if app is None:
        return _store("frontmost", False)
    return _store("frontmost", (app.bundleIdentifier() or "") == bundle_id)
