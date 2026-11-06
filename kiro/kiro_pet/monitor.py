"""Reliable incremental tailer for all Kiro logs (IDE windows + CLI)."""
from __future__ import annotations

from dataclasses import dataclass, replace
import glob
import logging
import os
import threading
import time

from .config import (
    AppConfig,
    KIRO_LEGACY_SESSIONS_DIR,
    KIRO_CLI_LOG_GLOB,
    KIRO_LOG_GLOB,
    KIRO_WORKSPACE_STORAGE_DIR,
    SettingsStore,
)
from .events import LogClassifier
from .notify import Notifier
from .session_activity import SessionActivityProbe
from .retry import RetryCoordinator
from .session_jump import SessionJumper
from .session_titles import SessionTitleResolver
from .state import SessionAggregator, StatusPublisher
from .stats import UsageStats


@dataclass
class TailCursor:
    inode: int
    offset: int
    partial: bytes = b""


class KiroLogMonitor:
    def __init__(
        self,
        config: AppConfig,
        aggregator: SessionAggregator,
        settings: SettingsStore,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.aggregator = aggregator
        self.settings = settings
        self.logger = logger
        self.classifier = LogClassifier()
        self.publisher = StatusPublisher()
        self.notifier = Notifier(config, settings, logger)
        self.stats = UsageStats()
        self.title_resolver = SessionTitleResolver(
            KIRO_WORKSPACE_STORAGE_DIR, KIRO_LEGACY_SESSIONS_DIR, logger
        )
        self.activity_probe = SessionActivityProbe(logger=logger)
        # Its own jumper: retrying happens on this thread, independent of the UI.
        self.retry = RetryCoordinator(
            config,
            settings,
            logger,
            SessionJumper(logger, config=config),
            notifier=self.notifier,
            activity_probe=self.activity_probe,
        )
        self._cursors: dict[str, TailCursor] = {}
        self._stop = threading.Event()
        self._rescan = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="kiro-log-monitor", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self.stats.flush()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
            self._rescan.set()
        self.logger.info("日志监控%s", "已暂停" if paused else "已恢复")

    def request_rescan(self) -> None:
        self._rescan.set()

    def _run(self) -> None:
        self.logger.info("Kiro 日志监控线程启动")
        self._refresh_titles(force=True)
        self._scan(bootstrap=True)
        last_scan = time.monotonic()
        last_title_scan = last_scan
        last_stats_flush = last_scan
        last_work_tick = last_scan
        last_activity_probe = last_scan
        self.publisher.publish(self.aggregator.snapshot(), force=True)
        self.notifier.arm()
        while not self._stop.wait(self.config.poll_interval):
            now_mono = time.monotonic()
            if self._paused.is_set():
                last_work_tick = now_mono
                continue
            needs_scan = (
                self._rescan.is_set() or now_mono - last_scan >= self.config.rescan_interval
            )
            changed = False
            if needs_scan:
                self._rescan.clear()
                changed = self._refresh_titles() or changed
                self._scan(bootstrap=True)
                last_scan = now_mono
                last_title_scan = now_mono
            elif now_mono - last_title_scan >= self.config.title_rescan_interval:
                changed = self._refresh_titles() or changed
                last_title_scan = now_mono
            for path in list(self._cursors):
                changed = self._read_new(path) or changed
            changed = self._drain_unpaired_outcomes() or changed
            self.retry.tick()
            if now_mono - last_activity_probe >= self.config.activity_probe_interval:
                changed = self._probe_activity() or changed
                last_activity_probe = now_mono
            changed = self.aggregator.tick() or changed
            self.notifier.service()

            snapshot = self.aggregator.snapshot()
            elapsed = max(0.0, now_mono - last_work_tick)
            last_work_tick = now_mono
            if snapshot.active_count > 0:
                self.stats.add_work_seconds(elapsed)
                self._check_long_running()
            if now_mono - last_stats_flush >= self.config.stats_flush_interval:
                self.stats.flush()
                last_stats_flush = now_mono
            if changed:
                self.publisher.publish(snapshot)
        self.publisher.publish(self.aggregator.snapshot(), force=True)
        self.stats.flush(force=True)
        self.logger.info("Kiro 日志监控线程停止")

    def _probe_activity(self) -> bool:
        """Retire sessions Kiro's own archive reports as finished.

        Terminal log lines only carry an executionId, so a missed or
        misattributed one would otherwise leave a finished session showing as
        running until the stale timeout.
        """
        session_ids = self.aggregator.running_session_ids()
        if not session_ids:
            return False
        finished = {
            session_id: sample.observed_at
            for session_id, sample in self.activity_probe.probe(session_ids).items()
            if not sample.running
        }
        if not finished:
            return False
        retired = self.aggregator.retire_finished(
            finished,
            min_quiet=self.config.activity_confirm_delay,
            reason="会话已结束",
        )
        if retired:
            self.logger.info(
                "按会话存档校正状态，已结束: %s",
                ", ".join(sorted(view.session_id for view in retired)),
            )
            for view in retired:
                self.notifier.notify_inferred_finish(view)
        return bool(retired)

    def _check_long_running(self) -> None:
        threshold = self.config.long_run_threshold
        if threshold <= 0:
            return
        for view in self.aggregator.long_running(threshold):
            self.notifier.notify_long_run(view)

    def _refresh_titles(self, force: bool = False) -> bool:
        self.title_resolver.refresh(force=force)
        changed = self.aggregator.update_titles(self.title_resolver.titles())
        if changed:
            self.publisher.publish(self.aggregator.snapshot())
        return changed

    def _scan(self, bootstrap: bool) -> None:
        try:
            paths = set(glob.glob(KIRO_LOG_GLOB)) | set(glob.glob(KIRO_CLI_LOG_GLOB))
        except OSError as exc:
            self.logger.warning("扫描 Kiro 日志失败: %s", exc)
            return
        for stale in set(self._cursors) - paths:
            self._cursors.pop(stale, None)
            # Kiro restarted or rotated its logs: no execution can still be live
            # in a file that no longer exists.
            self.aggregator.retire_log_path(stale)
        for path in sorted(paths):
            if path in self._cursors:
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            self._cursors[path] = TailCursor(inode=stat.st_ino, offset=stat.st_size)
            if bootstrap and time.time() - stat.st_mtime <= self.config.bootstrap_max_age:
                self._bootstrap(path, stat.st_size)
        if self.aggregator.set_log_count(len(self._cursors)):
            self.publisher.publish(self.aggregator.snapshot())
        self.logger.debug("当前追踪 %d 个 Kiro 日志", len(self._cursors))

    def _bootstrap(self, path: str, size: int) -> None:
        cursor = self._cursors[path]
        start = max(0, size - self.config.bootstrap_bytes)
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                data = handle.read()
                cursor.offset = handle.tell()
        except OSError as exc:
            self.logger.debug("启动回放读取失败 %s: %s", path, exc)
            return
        if start > 0:
            newline = data.find(b"\n")
            data = data[newline + 1 :] if newline >= 0 else b""
        self._consume(path, data, final_chunk=True, notify=False)

    def _read_new(self, path: str) -> bool:
        cursor = self._cursors.get(path)
        if cursor is None:
            return False
        try:
            stat = os.stat(path)
        except OSError:
            self._cursors.pop(path, None)
            self.aggregator.retire_log_path(path)
            self.aggregator.set_log_count(len(self._cursors))
            return True
        if stat.st_ino != cursor.inode or stat.st_size < cursor.offset:
            cursor.inode = stat.st_ino
            cursor.offset = 0
            cursor.partial = b""
        if stat.st_size == cursor.offset:
            return False
        try:
            with open(path, "rb") as handle:
                handle.seek(cursor.offset)
                data = handle.read()
                cursor.offset = handle.tell()
        except OSError as exc:
            self.logger.debug("增量读取失败 %s: %s", path, exc)
            return False
        return self._consume(path, data, final_chunk=False, notify=True)

    def _consume(self, path: str, data: bytes, final_chunk: bool, notify: bool = False) -> bool:
        cursor = self._cursors[path]
        combined = cursor.partial + data
        lines = combined.split(b"\n")
        if final_chunk or combined.endswith(b"\n"):
            cursor.partial = b""
        else:
            cursor.partial = lines.pop() if lines else combined
        changed = False
        for raw in lines:
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            event = self.classifier.parse(line, path)
            if event is not None:
                changed = self._handle_event(event, notify) or changed
        return changed

    def _handle_event(self, event, notify: bool) -> bool:
        """Enrich one event with title and workspace, then apply it."""
        workspace = event.workspace
        if not workspace:
            resolved = self.title_resolver.workspace_for(event.session_id)
            if resolved:
                workspace = os.path.basename(resolved.rstrip(os.sep)) or resolved
        event = replace(
            event,
            title=event.title or self.title_resolver.title_for(event.session_id),
            workspace=workspace,
        )
        changed = self.aggregator.process(event)
        if notify:
            # Only live lines count; the bootstrap replay must not
            # inflate today's statistics or fire notifications.
            self.notifier.handle(event)
            self.stats.record(event)
            self.retry.note_event(event)
        return changed

    def _drain_unpaired_outcomes(self) -> bool:
        """Apply failures whose precisely attributed partner line never arrived."""
        changed = False
        for event in self.classifier.drain_unpaired_outcomes(time.time()):
            self.logger.info(
                "结束原因无配对行，按唯一在跑的执行归属：%s %s",
                event.session_id,
                event.detail or event.kind.value,
            )
            changed = self._handle_event(event, notify=True) or changed
        return changed
