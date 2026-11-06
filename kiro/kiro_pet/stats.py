"""Rolling daily usage statistics for the Kiro desktop pet."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from .config import STATS_FILE, atomic_write_json
from .events import EventType
from .layout import format_duration

_KIND_BUCKETS = {
    EventType.SUCCESS: "success",
    EventType.ERROR: "error",
    EventType.CANCEL: "cancelled",
}
RETAIN_DAYS = 14


def _empty_day() -> dict:
    return {"success": 0, "error": 0, "cancelled": 0, "seconds": 0.0}


class UsageStats:
    """Count finished executions per day and accumulate active work time."""

    def __init__(self, path=STATS_FILE, clock=time.time, dedupe: float = 8.0) -> None:
        self.path = path
        self._clock = clock
        self._dedupe = float(dedupe)
        self._lock = threading.RLock()
        self._last: dict[tuple[str, str], float] = {}
        self._dirty = False
        self._days = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            days = payload.get("days", {}) if isinstance(payload, dict) else {}
            result: dict[str, dict] = {}
            for day, value in days.items() if isinstance(days, dict) else []:
                if not isinstance(value, dict):
                    continue
                bucket = _empty_day()
                for key in bucket:
                    raw = value.get(key, 0)
                    if isinstance(raw, (int, float)):
                        bucket[key] = type(bucket[key])(raw)
                result[str(day)] = bucket
            return result
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _day_key(now: float) -> str:
        return datetime.fromtimestamp(now).strftime("%Y-%m-%d")

    def record(self, event, now: float | None = None) -> bool:
        """Count one finished execution; ignores replayed and duplicate lines."""
        bucket_name = _KIND_BUCKETS.get(event.kind)
        if bucket_name is None:
            return False
        now = self._clock() if now is None else now
        key = (event.session_id, bucket_name)
        with self._lock:
            if now - self._last.get(key, 0.0) < self._dedupe:
                return False
            self._last[key] = now
            day = self._days.setdefault(self._day_key(now), _empty_day())
            day[bucket_name] = int(day[bucket_name]) + 1
            self._dirty = True
        return True

    def add_work_seconds(self, seconds: float, now: float | None = None) -> None:
        if seconds <= 0:
            return
        now = self._clock() if now is None else now
        with self._lock:
            day = self._days.setdefault(self._day_key(now), _empty_day())
            day["seconds"] = float(day["seconds"]) + float(seconds)
            self._dirty = True

    def today(self, now: float | None = None) -> dict:
        now = self._clock() if now is None else now
        with self._lock:
            return dict(self._days.get(self._day_key(now), _empty_day()))

    def summary_line(self, now: float | None = None) -> str:
        day = self.today(now)
        return (
            f"今日 完成 {int(day['success'])} · 异常 {int(day['error'])}"
            f" · 取消 {int(day['cancelled'])} · 工作 {format_duration(day['seconds'])}"
        )

    def flush(self, force: bool = False) -> bool:
        with self._lock:
            if not self._dirty and not force:
                return False
            for stale in sorted(self._days)[:-RETAIN_DAYS]:
                self._days.pop(stale, None)
            payload = {"days": {day: dict(value) for day, value in self._days.items()}}
            self._dirty = False
        try:
            atomic_write_json(self.path, payload)
        except OSError:
            return False
        return True
