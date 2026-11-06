"""Parse Kiro extension logs into normalized lifecycle events."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class EventType(str, Enum):
    START = "start"
    REQUEST = "request"
    ACTIVITY = "activity"
    SUCCESS = "success"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    ERROR = "error"
    CANCEL = "cancel"
    SESSION_LOAD = "session_load"
    APPROVAL = "approval"


@dataclass(frozen=True)
class LogEvent:
    kind: EventType
    timestamp: float
    session_id: str
    log_path: str
    model: str = ""
    mode: str = ""
    detail: str = ""
    workspace: str = ""
    title: str = ""
    execution_id: str = ""
    interrupt: bool = False


# Strict envelope parsing prevents marker text inside logged terminal commands from
# being mistaken for real Kiro lifecycle events.
_ENVELOPE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.\d+)? "
    r"\[([^\]]+)\] \[([^\]]+)\] (.*)$"
)
_SESSION_RE = re.compile(r"sessionId=(sess_[A-Za-z0-9-]+)")
_CONVERSATION_RE = re.compile(r"conversationId=(sess_[A-Za-z0-9-]+)")
_PERSISTED_SESSION_RE = re.compile(r"\bsession (sess_[A-Za-z0-9-]+)")
_EXECUTION_ID_RE = re.compile(r'"executionId"\s*:\s*"([A-Za-z0-9-]+)"')
_MODEL_RE = re.compile(r"modelId=([^\s]+)")
_MODE_RE = re.compile(r"agentMode=([^\s]+)")
_CWD_RE = re.compile(r'"cwd"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')
_SESSION_HINT_TTL = 4.0
# "Completed with error/abort" carries no executionId. Kiro emits the matching
# "Execution failed/aborted" (which does carry one) in the same millisecond, so a
# short window is enough to hand the detail over to the precisely-attributed event.
_PENDING_OUTCOME_TTL = 2.0

# ACP ToolApproval: Kiro弹出授权确认弹窗时写入，effect=ask 表示需要人工批准。
_APPROVAL_TOOLID_RE = re.compile(r'toolId=([^\s,]+)')
_APPROVAL_SESSION_RE = re.compile(r'sessionId=(sess_[A-Za-z0-9-]+)')
_APPROVAL_OPERATION_RE = re.compile(r'operationId=([^\s,]+)')


class LogClassifier:
    """Associate interleaved execution ids with their exact Kiro sessions."""

    def __init__(self) -> None:
        self._current_by_path: dict[str, str] = {}
        self._session_hint_by_path: dict[str, tuple[str, float]] = {}
        self._session_by_execution: dict[tuple[str, str], str] = {}
        self._pending_outcome: dict[str, tuple[float, str, bool]] = {}

    def parse(self, line: str, log_path: str) -> LogEvent | None:
        envelope = _ENVELOPE_RE.match(line)
        if not envelope:
            return None
        timestamp = self._timestamp(envelope.group(1))
        source = envelope.group(3)
        message = envelope.group(4)
        session_id = self._match(_SESSION_RE, message)
        current = self._current_by_path.get(log_path)

        # SessionPersistence is emitted immediately around an execution boundary and
        # contains the exact parent session even when multiple chats share one log.
        if source == "SessionPersistence":
            persisted = self._match(_PERSISTED_SESSION_RE, message)
            if persisted:
                self._remember_hint(log_path, persisted, timestamp)
            return None

        if source == "KiroAgent" and message.startswith("ACP session/prompt sessionId="):
            sid = session_id or current or self._fallback_id(log_path)
            self._current_by_path[log_path] = sid
            self._remember_hint(log_path, sid, timestamp)
            return LogEvent(EventType.START, timestamp, sid, log_path)

        if source == "KiroAgent" and message.startswith("ACP session/cancel sessionId="):
            sid = session_id or current or self._fallback_id(log_path)
            return LogEvent(EventType.CANCEL, timestamp, sid, log_path)

        if source == "KiroAgent" and message.startswith("ACP session/load complete sessionId="):
            sid = session_id or current or self._fallback_id(log_path)
            self._current_by_path[log_path] = sid
            self._remember_hint(log_path, sid, timestamp)
            return LogEvent(EventType.SESSION_LOAD, timestamp, sid, log_path)

        if source == "q-developer-converse" and message.startswith("Sending GenerateAssistantResponse"):
            sid = (
                self._match(_CONVERSATION_RE, message)
                or session_id
                or current
                or self._fallback_id(log_path)
            )
            self._current_by_path[log_path] = sid
            self._remember_hint(log_path, sid, timestamp)
            return LogEvent(
                EventType.REQUEST,
                timestamp,
                sid,
                log_path,
                model=self._match(_MODEL_RE, message),
                mode=self._match(_MODE_RE, message),
            )

        if source == "ACPEventAdapter":
            event = self._parse_execution_event(message, log_path, timestamp)
            if event is not None:
                return event

        if source == "Terminal" and (
            message.startswith("Executing command") or message.startswith("Running command")
        ):
            sid = self._recent_hint(log_path, timestamp) or current
            if not sid:
                return None
            return LogEvent(
                EventType.TOOL_START,
                timestamp,
                sid,
                log_path,
                detail="正在执行工具",
                workspace=self._workspace(message),
            )

        if source == "Terminal" and (
            message.startswith("Command execution completed")
            or message.startswith("execute terminal command done")
        ):
            sid = self._recent_hint(log_path, timestamp) or current
            if not sid:
                return None
            return LogEvent(
                EventType.TOOL_END,
                timestamp,
                sid,
                log_path,
                detail="工具执行完成，等待模型",
                workspace=self._workspace(message),
            )

        # These lines carry the human readable reason but neither a sessionId nor
        # an executionId, so they can never be attributed on their own. A recent
        # hint is not good enough: while one chat fails, a parallel chat writing
        # to the same log becomes the hint and gets the red dot instead. Kiro
        # emits the matching "Execution failed/aborted" (which does carry an
        # executionId) in the same millisecond, so always let that line decide.
        if source == "Execution" and message.startswith("Completed with error"):
            self._pending_outcome[log_path] = (
                timestamp,
                self._error_detail(message),
                self._is_connection_interrupt(message),
            )
            return None

        if source == "Execution" and message.startswith("Completed with abort"):
            self._pending_outcome[log_path] = (timestamp, "", False)
            return None

        # This is a stream-processing heartbeat, not a completion signal.
        if source == "ChatAgent" and message.startswith("Processing model response stream"):
            sid = self._recent_hint(log_path, timestamp) or current
            if not sid:
                return None
            return LogEvent(
                EventType.ACTIVITY,
                timestamp,
                sid,
                log_path,
                detail="正在处理模型响应",
            )

        # ACP ToolApproval: Kiro 需要用户手动批准一个工具调用时写入。
        # 日志格式:
        #   [ACP ToolApproval] Requesting permission for toolId=xxx, operationId=xxx, sessionId=sess_xxx
        # 只在 Kiro 确定弹窗的瞬间出现，不会误判。
        if source == "ACP ToolApproval" and message.startswith("Requesting permission"):
            sid = self._match(_APPROVAL_SESSION_RE, message) or current
            if not sid:
                return None
            tool_id = self._match(_APPROVAL_TOOLID_RE, message)
            # 把 mcp_github_getissue 这类 id 转为更友好的显示
            tool_label = tool_id.replace("mcp_", "").replace("_", "/") if tool_id else "未知工具"
            self._remember_hint(log_path, sid, timestamp)
            return LogEvent(
                EventType.APPROVAL,
                timestamp,
                sid,
                log_path,
                detail=f"等待批准：{tool_label}",
            )

        return None

    def _parse_execution_event(
        self, message: str, log_path: str, timestamp: float
    ) -> LogEvent | None:
        execution_id = self._match(_EXECUTION_ID_RE, message)
        if not execution_id:
            return None
        key = (log_path, execution_id)
        hint = self._recent_hint(log_path, timestamp)
        mapped = self._session_by_execution.get(key)
        current = self._current_by_path.get(log_path)

        if message.startswith("Execution began"):
            sid = hint or current
            if not sid:
                return None
            self._session_by_execution[key] = sid
            return LogEvent(
                EventType.ACTIVITY,
                timestamp,
                sid,
                log_path,
                detail="执行已开始",
                execution_id=execution_id,
            )

        if message.startswith("Execution yielded") or message.startswith("Execution resumed"):
            sid = hint or mapped or current
            if not sid:
                return None
            self._session_by_execution[key] = sid
            detail = "执行已恢复" if message.startswith("Execution resumed") else "正在等待工具结果"
            return LogEvent(
                EventType.ACTIVITY,
                timestamp,
                sid,
                log_path,
                detail=detail,
                execution_id=execution_id,
            )

        if message.startswith("Execution succeeded"):
            # The executionId mapping is exact; the hint is only a heuristic and can
            # point at a parallel chat, so it must never outrank the mapping.
            sid = mapped or hint or current
            self._session_by_execution.pop(key, None)
            if not sid:
                return None
            return LogEvent(
                EventType.SUCCESS,
                timestamp,
                sid,
                log_path,
                detail="任务已完成",
                execution_id=execution_id,
            )

        if message.startswith("Execution failed"):
            sid = mapped or hint or current or self._fallback_id(log_path)
            self._session_by_execution.pop(key, None)
            detail, interrupt = self._take_pending_outcome(log_path, timestamp)
            return LogEvent(
                EventType.ERROR,
                timestamp,
                sid,
                log_path,
                detail=detail or "Kiro 执行失败",
                execution_id=execution_id,
                interrupt=interrupt,
            )

        if message.startswith("Execution aborted"):
            sid = mapped or hint or current or self._fallback_id(log_path)
            self._session_by_execution.pop(key, None)
            self._take_pending_outcome(log_path, timestamp)
            return LogEvent(
                EventType.CANCEL,
                timestamp,
                sid,
                log_path,
                execution_id=execution_id,
            )
        return None

    def drain_unpaired_outcomes(self, now: float) -> list[LogEvent]:
        """Report buffered reasons whose ACPEventAdapter partner never arrived.

        Attribution is only safe while the log has exactly one live execution.
        With several running there is no way to tell whose failure it was, and a
        red dot on an innocent session costs more trust than a missed alert."""
        events: list[LogEvent] = []
        for log_path, (seen_at, detail, interrupt) in list(self._pending_outcome.items()):
            if now - seen_at <= _PENDING_OUTCOME_TTL:
                continue
            self._pending_outcome.pop(log_path, None)
            owners = {
                sid
                for (path, _), sid in self._session_by_execution.items()
                if path == log_path
            }
            if len(owners) != 1:
                continue
            kind = EventType.ERROR if detail else EventType.CANCEL
            events.append(
                LogEvent(
                    kind,
                    seen_at,
                    owners.pop(),
                    log_path,
                    detail=detail,
                    interrupt=interrupt,
                )
            )
        return events

    def _take_pending_outcome(self, log_path: str, timestamp: float) -> tuple[str, bool]:
        """Consume the detail stashed by a "Completed with ..." line, if still fresh."""
        pending = self._pending_outcome.pop(log_path, None)
        if pending is None:
            return "", False
        seen_at, detail, interrupt = pending
        if 0 <= timestamp - seen_at <= _PENDING_OUTCOME_TTL:
            return detail, interrupt
        return "", False

    def _remember_hint(self, log_path: str, session_id: str, timestamp: float) -> None:
        self._session_hint_by_path[log_path] = (session_id, timestamp)

    def _recent_hint(self, log_path: str, timestamp: float) -> str | None:
        value = self._session_hint_by_path.get(log_path)
        if value is None:
            return None
        session_id, seen_at = value
        if 0 <= timestamp - seen_at <= _SESSION_HINT_TTL:
            return session_id
        return None

    @staticmethod
    def _timestamp(value: str) -> float:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return datetime.now().timestamp()

    @staticmethod
    def _match(pattern: re.Pattern[str], value: str) -> str:
        match = pattern.search(value)
        return match.group(1) if match else ""

    @staticmethod
    def _fallback_id(log_path: str) -> str:
        path = Path(log_path)
        try:
            window = path.parents[2].name
            run = path.parents[3].name
            return f"log_{run}_{window}"
        except IndexError:
            return f"log_{abs(hash(log_path))}"

    @staticmethod
    def _workspace(message: str) -> str:
        match = _CWD_RE.search(message)
        if not match:
            return ""
        raw = match.group(1)
        try:
            decoded = json.loads(f'"{raw}"')
        except (json.JSONDecodeError, ValueError):
            decoded = raw
        return Path(decoded).name

    @staticmethod
    def _is_connection_interrupt(message: str) -> bool:
        return "connection was interrupted" in message.lower()

    @staticmethod
    def _error_detail(message: str) -> str:
        brace = message.find("{")
        if brace >= 0:
            try:
                payload = json.loads(message[brace:])
                detail = payload.get("userFacingSessionErrorMessage") or payload.get("message")
                if detail:
                    return str(detail)[:220]
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        lowered = message.lower()
        if "connection was interrupted" in lowered:
            return "连接已中断，请重试"
        if "high volume of traffic" in lowered or "overloaded" in lowered:
            return "模型繁忙或过载"
        if "timed out" in lowered or "timeout" in lowered:
            return "请求超时"
        return "Kiro 执行出现异常"
