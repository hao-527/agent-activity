"""Thread-safe multi-session state machine and JSON status publisher."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import threading
import time
from typing import Iterable

from .config import AppConfig, STATUS_FILE, atomic_write_json
from .events import EventType, LogEvent

# A false negative from the Kiro presence probe must never blank out a pet that
# is clearly still receiving log activity.
PRESENCE_GRACE = 60.0


class SessionPhase(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


ACTIVE_PHASES = frozenset((SessionPhase.RUNNING, SessionPhase.WAITING))


class OverallState(str, Enum):
    OFFLINE = "offline"
    IDLE = "idle"
    RUNNING = "running"
    MULTI = "multi"
    WAITING = "waiting"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class SessionRecord:
    session_id: str
    phase: SessionPhase = SessionPhase.IDLE
    started_at: float = 0.0
    updated_at: float = 0.0
    completed_at: float = 0.0
    model: str = ""
    mode: str = ""
    workspace: str = ""
    title: str = ""
    detail: str = ""
    log_path: str = ""
    turns: int = 0
    errors: int = 0

    @property
    def short_id(self) -> str:
        return self.session_id.removeprefix("sess_")[:8]


@dataclass(frozen=True)
class SessionView:
    session_id: str
    short_id: str
    phase: str
    started_at: float
    updated_at: float
    completed_at: float
    model: str
    mode: str
    workspace: str
    title: str
    detail: str
    turns: int
    errors: int


@dataclass(frozen=True)
class PetSnapshot:
    sequence: int
    generated_at: float
    overall: str
    active_count: int
    total_sessions: int
    log_count: int
    kiro_running: bool
    headline: str
    subline: str
    flash: str
    flash_title: str
    sessions: tuple[SessionView, ...]

    def to_dict(self) -> dict:
        value = asdict(self)
        value["sessions"] = [asdict(item) for item in self.sessions]
        return value


class SessionAggregator:
    def __init__(self, config: AppConfig):
        self.config = config
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionRecord] = {}
        self._sequence = 0
        self._log_count = 0
        self._kiro_running = True

    def process(self, event: LogEvent) -> bool:
        with self._lock:
            record = self._sessions.get(event.session_id)
            if record is None:
                record = SessionRecord(session_id=event.session_id, log_path=event.log_path)
                self._sessions[event.session_id] = record
            before = self._record_signature(record)
            record.updated_at = max(record.updated_at, event.timestamp)
            record.log_path = event.log_path or record.log_path
            record.model = event.model or record.model
            record.mode = event.mode or record.mode
            record.workspace = event.workspace or record.workspace
            record.title = event.title or record.title

            if event.kind == EventType.START:
                self._begin(record, event.timestamp, "正在处理新任务")
            elif event.kind == EventType.REQUEST:
                self._begin(record, event.timestamp, "模型正在思考")
            elif event.kind == EventType.ACTIVITY:
                record.phase = SessionPhase.RUNNING
                record.completed_at = 0.0
                record.detail = event.detail or "Kiro 正在工作"
            elif event.kind == EventType.SUCCESS:
                record.phase = SessionPhase.SUCCESS
                record.completed_at = event.timestamp
                record.detail = event.detail or "任务已完成"
            elif event.kind == EventType.TOOL_START:
                record.phase = SessionPhase.RUNNING
                record.completed_at = 0.0
                record.detail = event.detail or "正在执行工具"
            elif event.kind == EventType.TOOL_END:
                record.phase = SessionPhase.RUNNING
                record.completed_at = 0.0
                record.detail = event.detail or "工具执行完成，等待模型"
            elif event.kind == EventType.ERROR:
                duplicate = (
                    record.phase == SessionPhase.ERROR
                    and record.detail == event.detail
                    and abs(event.timestamp - record.completed_at) < 3.0
                )
                record.phase = SessionPhase.ERROR
                record.completed_at = event.timestamp
                record.detail = event.detail or "Kiro 执行出现异常"
                if not duplicate:
                    record.errors += 1
            elif event.kind == EventType.CANCEL:
                record.phase = SessionPhase.CANCELLED
                record.completed_at = event.timestamp
                record.detail = "执行已取消"
            elif event.kind == EventType.SESSION_LOAD:
                record.detail = record.detail or "会话已载入"
            elif event.kind == EventType.APPROVAL:
                record.phase = SessionPhase.WAITING
                record.completed_at = 0.0
                record.detail = event.detail or "等待用户批准"

            changed = before != self._record_signature(record)
            if changed:
                self._sequence += 1
            return changed

    def update_titles(self, titles: dict[str, str]) -> bool:
        """Apply non-empty titles, accepting ids with or without ``sess_``."""
        normalized: dict[str, str] = {}
        for session_id, value in titles.items():
            canonical = session_id if session_id.startswith("sess_") else f"sess_{session_id}"
            title = " ".join(str(value or "").split())[:100]
            if canonical != "sess_" and title:
                normalized[canonical] = title
        changed = False
        with self._lock:
            for record in self._sessions.values():
                canonical = (
                    record.session_id
                    if record.session_id.startswith("sess_")
                    else f"sess_{record.session_id}"
                )
                title = normalized.get(canonical, "")
                if title and title != record.title:
                    record.title = title
                    changed = True
            if changed:
                self._sequence += 1
        return changed

    def set_kiro_running(self, running: bool) -> bool:
        with self._lock:
            changed = bool(running) != self._kiro_running
            self._kiro_running = bool(running)
            if not running:
                # Kiro cannot be mid-execution while its process is gone. The
                # presence probe can report false negatives, so only sessions
                # whose logs already went quiet are retired here.
                changed = (
                    self._retire(
                        self._sessions.values(),
                        reason="Kiro 已退出，状态已重置",
                        min_quiet=PRESENCE_GRACE,
                    )
                    or changed
                )
            if changed:
                self._sequence += 1
            return changed

    def running_session_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                record.session_id
                for record in self._sessions.values()
                if record.phase in ACTIVE_PHASES
            )

    def retire_finished(
        self,
        finished: dict[str, float],
        now: float | None = None,
        min_quiet: float = 0.0,
        reason: str = "会话已结束",
    ) -> tuple[SessionView, ...]:
        """Retire running sessions an authoritative source reports as finished.

        ``finished`` maps a session id to the time that evidence was observed.
        Evidence newer than our last log line is trusted immediately; older
        evidence has to wait for the log to go quiet for ``min_quiet`` seconds
        so a live session is never cut off mid-turn.

        Returns a view of every session actually retired, so the caller can
        notify: these are exactly the completions whose log line was missed, and
        staying silent about them is the whole problem this repair path exists
        for. An empty tuple is falsy, so callers can still treat it as "changed".
        """
        now = now or time.time()
        retired: list[SessionView] = []
        with self._lock:
            for session_id, observed_at in finished.items():
                record = self._sessions.get(session_id)
                if record is None or record.phase not in ACTIVE_PHASES:
                    continue
                fresh_evidence = observed_at >= record.updated_at
                quiet_enough = now - record.updated_at >= min_quiet
                if not fresh_evidence and not quiet_enough:
                    continue
                if self._retire([record], reason=reason, now=now):
                    retired.append(self._view(record))
            if retired:
                self._sequence += 1
            return tuple(retired)

    def retire_log_path(self, log_path: str, reason: str = "Kiro 日志已轮转，状态已重置") -> bool:
        """Retire running sessions whose log file vanished (restart or rotation)."""
        if not log_path:
            return False
        with self._lock:
            targets = [
                record
                for record in self._sessions.values()
                if record.log_path == log_path
            ]
            changed = self._retire(targets, reason=reason)
            if changed:
                self._sequence += 1
            return changed

    def _retire(
        self,
        records: Iterable[SessionRecord],
        reason: str,
        now: float | None = None,
        min_quiet: float = 0.0,
    ) -> bool:
        """Move running records to idle. Caller must hold the lock."""
        now = now or time.time()
        changed = False
        for record in records:
            if record.phase not in ACTIVE_PHASES:
                continue
            if min_quiet and record.updated_at and now - record.updated_at < min_quiet:
                continue
            record.phase = SessionPhase.IDLE
            record.completed_at = record.updated_at or now
            record.detail = reason
            changed = True
        return changed

    @property
    def kiro_running(self) -> bool:
        with self._lock:
            return self._kiro_running

    def long_running(self, threshold: float, now: float | None = None) -> tuple[SessionView, ...]:
        """Running sessions that started at least ``threshold`` seconds ago."""
        now = now or time.time()
        with self._lock:
            return tuple(
                self._view(record)
                for record in self._sessions.values()
                if record.phase in ACTIVE_PHASES
                and record.started_at
                and now - record.started_at >= threshold
            )

    def _begin(self, record: SessionRecord, timestamp: float, detail: str) -> None:
        if record.phase not in ACTIVE_PHASES:
            record.started_at = timestamp
            record.turns += 1
        record.phase = SessionPhase.RUNNING
        record.completed_at = 0.0
        record.detail = detail

    def tick(self, now: float | None = None) -> bool:
        now = now or time.time()
        changed = False
        with self._lock:
            stale = [
                record
                for record in self._sessions.values()
                if record.phase == SessionPhase.RUNNING and record.updated_at > 0
            ]
            changed = (
                self._retire(
                    stale,
                    reason="长时间无新日志，已转为待命",
                    now=now,
                    min_quiet=self.config.running_stale_timeout,
                )
                or changed
            )
            expired = [
                sid
                for sid, record in self._sessions.items()
                if record.updated_at and now - record.updated_at > self.config.session_retention
            ]
            for sid in expired:
                del self._sessions[sid]
                changed = True
            if changed:
                self._sequence += 1
        return changed

    def set_log_count(self, count: int) -> bool:
        with self._lock:
            if count == self._log_count:
                return False
            self._log_count = count
            self._sequence += 1
            return True

    def snapshot(self, now: float | None = None) -> PetSnapshot:
        now = now or time.time()
        with self._lock:
            records = sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)
            active = [item for item in records if item.phase in ACTIVE_PHASES]
            waiting = [item for item in active if item.phase == SessionPhase.WAITING]
            recent_error = self._recent(records, SessionPhase.ERROR, now, self.config.error_hold)
            recent_success = self._recent(records, SessionPhase.SUCCESS, now, self.config.success_hold)
            recent_cancel = self._recent(records, SessionPhase.CANCELLED, now, self.config.cancelled_hold)
            fresh_activity = any(
                item.updated_at and now - item.updated_at <= PRESENCE_GRACE for item in records
            )

            if self._log_count == 0:
                overall = OverallState.OFFLINE
                headline, subline = "等待 Kiro", "尚未发现活动日志"
            elif not self._kiro_running and not active and not fresh_activity:
                overall = OverallState.OFFLINE
                headline, subline = "Kiro 未运行", "启动 Kiro 我就醒过来"
            elif recent_error:
                overall = OverallState.ERROR
                headline = "Kiro 出现异常"
                subline = recent_error.detail or "请回到 Kiro 查看"
            elif waiting:
                overall = OverallState.WAITING
                headline = "Kiro 等待确认"
                subline = waiting[0].detail or self._session_label(waiting[0])
            elif len(active) >= 2:
                overall = OverallState.MULTI
                headline = f"{len(active)} 个任务并行运行"
                subline = self._active_subline(active)
            elif len(active) == 1:
                overall = OverallState.RUNNING
                headline = "Kiro 正在工作"
                subline = self._session_label(active[0])
            elif recent_success:
                overall = OverallState.SUCCESS
                headline = "任务完成啦！"
                subline = self._session_label(recent_success)
            elif recent_cancel:
                overall = OverallState.CANCELLED
                headline = "执行已取消"
                subline = self._session_label(recent_cancel)
            else:
                overall = OverallState.IDLE
                headline, subline = "Kiro 在待命", "有任务时我会动起来"

            flash, flash_title = "", ""
            if overall in (OverallState.RUNNING, OverallState.MULTI, OverallState.WAITING):
                # A finished session must still be celebrated while other
                # sessions keep the pet in its running animation.
                for phase, name in (
                    (SessionPhase.ERROR, "error"),
                    (SessionPhase.SUCCESS, "success"),
                    (SessionPhase.CANCELLED, "cancelled"),
                ):
                    recent = self._recent(records, phase, now, self.config.flash_hold)
                    if recent is not None:
                        flash, flash_title = name, self._session_label(recent)
                        break

            visible = tuple(self._view(item) for item in records[: self.config.max_visible_sessions])
            return PetSnapshot(
                sequence=self._sequence,
                generated_at=now,
                overall=overall.value,
                active_count=len(active),
                total_sessions=len(records),
                log_count=self._log_count,
                kiro_running=self._kiro_running,
                headline=headline,
                subline=subline[:120],
                flash=flash,
                flash_title=flash_title[:100],
                sessions=visible,
            )

    @staticmethod
    def _recent(
        records: Iterable[SessionRecord], phase: SessionPhase, now: float, hold: float
    ) -> SessionRecord | None:
        for item in records:
            anchor = item.completed_at or item.updated_at
            if item.phase == phase and anchor and now - anchor <= hold:
                return item
        return None

    @staticmethod
    def _session_label(record: SessionRecord) -> str:
        if record.title:
            return record.title
        parts = [value for value in (record.workspace, record.model) if value]
        return " · ".join(parts) if parts else f"会话 {record.short_id}"

    def _active_subline(self, records: list[SessionRecord]) -> str:
        numbers = ("①", "②", "③", "④")
        return "  ".join(
            f"{numbers[index]} {self._session_label(item)}"
            for index, item in enumerate(records[:4])
        )

    @staticmethod
    def _record_signature(record: SessionRecord) -> tuple:
        return (
            record.phase,
            record.started_at,
            record.updated_at,
            record.completed_at,
            record.model,
            record.mode,
            record.workspace,
            record.title,
            record.detail,
            record.turns,
            record.errors,
        )

    @staticmethod
    def _view(record: SessionRecord) -> SessionView:
        return SessionView(
            session_id=record.session_id,
            short_id=record.short_id,
            phase=record.phase.value,
            started_at=record.started_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
            model=record.model,
            mode=record.mode,
            workspace=record.workspace,
            title=record.title,
            detail=record.detail,
            turns=record.turns,
            errors=record.errors,
        )


def session_label(view: SessionView) -> str:
    """Best available human label for a session view."""
    if view.title:
        return view.title
    parts = [value for value in (view.workspace, view.model) if value]
    return " · ".join(parts) if parts else f"会话 {view.short_id}"


class StatusPublisher:
    def __init__(self) -> None:
        self._last_sequence = -1

    def publish(self, snapshot: PetSnapshot, force: bool = False) -> None:
        if not force and snapshot.sequence == self._last_sequence:
            return
        atomic_write_json(STATUS_FILE, snapshot.to_dict())
        self._last_sequence = snapshot.sequence
