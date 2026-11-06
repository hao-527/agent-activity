"""Authoritative per-session activity probe backed by Kiro's own archives.

Kiro's ``Execution began/succeeded`` log lines carry only an ``executionId``,
so a session's running state is inferred from nearby hints. Any missed or
misattributed terminal line leaves a finished session stuck in ``running``
until the stale timeout fires. Kiro also appends ``turn_start`` / ``turn_end``
payloads to ``~/.kiro/sessions/<workspace>/<session_id>/messages.jsonl``, which
names the session directly. Reading the tail of that file tells us whether the
last turn is still open, and is used here purely as a repair signal: it can
retire a session the log missed, never promote one.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path

from .config import KIRO_SESSION_ARCHIVE_DIR

TURN_START = "turn_start"
TURN_END = "turn_end"
# Cheap byte prefilter so huge assistant messages are never JSON parsed.
_MARKERS = (TURN_START.encode(), TURN_END.encode())
# Growing tail windows: the newest turn marker is normally within a few KB.
_WINDOWS = (128 * 1024, 1024 * 1024, 8 * 1024 * 1024)


@dataclass(frozen=True)
class ActivitySample:
    """What Kiro's archive says about one session."""

    session_id: str
    running: bool
    observed_at: float


class SessionActivityProbe:
    def __init__(
        self,
        archive_dir: str | Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.archive_dir = Path(archive_dir or KIRO_SESSION_ARCHIVE_DIR).expanduser()
        self.logger = logger or logging.getLogger(__name__)
        self._paths: dict[str, Path] = {}
        self._cache: dict[str, tuple[tuple[int, int], ActivitySample]] = {}

    def probe(self, session_ids) -> dict[str, ActivitySample]:
        """Sample every requested session, skipping ones without an archive."""
        samples: dict[str, ActivitySample] = {}
        for session_id in session_ids:
            sample = self.sample(session_id)
            if sample is not None:
                samples[session_id] = sample
        return samples

    def sample(self, session_id: str) -> ActivitySample | None:
        path = self._archive_path(session_id)
        if path is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            self._paths.pop(session_id, None)
            return None
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        cached = self._cache.get(session_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        state = self._last_turn(path, stat.st_size)
        if state is None:
            return None
        sample = ActivitySample(
            session_id=session_id,
            running=state == TURN_START,
            observed_at=stat.st_mtime,
        )
        self._cache[session_id] = (fingerprint, sample)
        return sample

    def _archive_path(self, session_id: str) -> Path | None:
        cached = self._paths.get(session_id)
        if cached is not None and cached.exists():
            return cached
        canonical = session_id if session_id.startswith("sess_") else f"sess_{session_id}"
        try:
            # Archive directory names keep the ``sess_`` prefix.
            for candidate in self.archive_dir.glob(f"*/{canonical}/messages.jsonl"):
                self._paths[session_id] = candidate
                return candidate
        except OSError as exc:
            self.logger.debug("查找会话存档失败 %s: %s", session_id, exc)
        return None

    def _last_turn(self, path: Path, size: int) -> str | None:
        """Return the newest ``turn_start`` / ``turn_end`` type, if any."""
        for window in _WINDOWS:
            start = max(0, size - window)
            try:
                with open(path, "rb") as handle:
                    handle.seek(start)
                    data = handle.read()
            except OSError as exc:
                self.logger.debug("读取会话存档失败 %s: %s", path, exc)
                return None
            lines = data.split(b"\n")
            if start > 0 and lines:
                # Drop the partial first line produced by the seek.
                lines.pop(0)
            state = self._scan_backwards(lines)
            if state is not None:
                return state
            if start == 0 or window >= size:
                return None
        return None

    @staticmethod
    def _scan_backwards(lines: list[bytes]) -> str | None:
        for raw in reversed(lines):
            if not raw or not any(marker in raw for marker in _MARKERS):
                continue
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace")).get("payload")
            except (json.JSONDecodeError, AttributeError, UnicodeError):
                continue
            kind = payload.get("type") if isinstance(payload, dict) else None
            if kind in (TURN_START, TURN_END):
                return kind
        return None
