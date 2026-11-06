#!/usr/bin/env python3
"""Kiro Desktop Pet application entry point."""
from __future__ import annotations

import argparse
import fcntl
import os
import signal
import sys
import time

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

from kiro_pet.config import AppConfig, LOCK_FILE, SettingsStore, configure_logging, ensure_runtime_dirs
from kiro_pet.events import EventType, LogEvent
from kiro_pet.monitor import KiroLogMonitor
from kiro_pet.state import SessionAggregator
from kiro_pet.ui import PetController

_CONTROLLER = None
_LOCK_HANDLE = None


def acquire_single_instance():
    global _LOCK_HANDLE
    ensure_runtime_dirs()
    handle = open(LOCK_FILE, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _LOCK_HANDLE = handle
    return True


def seed_demo(aggregator: SessionAggregator, state: str, active_count: int) -> None:
    now = time.time()
    if state == "offline":
        aggregator.set_log_count(0)
        return
    aggregator.set_log_count(3)
    if state == "idle":
        return
    count = max(2, active_count) if state == "multi" else 1
    for index in range(count):
        sid = f"sess_demo-{index + 1}"
        path = f"/demo/window{index + 1}/Kiro Logs.log"
        aggregator.process(
            LogEvent(
                EventType.REQUEST,
                now - 2,
                sid,
                path,
                model="claude-opus-4.8" if index == 0 else "gpt-5.6-sol",
                mode="vibe",
                workspace="示例项目" if index == 0 else f"后台会话-{index + 1}",
            )
        )
        if state == "success":
            aggregator.process(
                LogEvent(EventType.SUCCESS, now - 1, sid, path, detail="任务已完成")
            )
        elif state == "waiting":
            aggregator.process(
                LogEvent(EventType.APPROVAL, now - 1, sid, path, detail="等待批准：终端命令")
            )
        elif state == "error":
            aggregator.process(
                LogEvent(EventType.ERROR, now - 1, sid, path, detail="连接中断，需要回来重试")
            )
        elif state == "cancelled":
            aggregator.process(LogEvent(EventType.CANCEL, now - 1, sid, path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kiro macOS desktop pet")
    parser.add_argument(
        "--demo-state",
        choices=("offline", "idle", "running", "multi", "waiting", "success", "error", "cancelled"),
        help="show a fixed state without reading Kiro logs",
    )
    parser.add_argument("--demo-count", type=int, default=3, help="active count for multi demo")
    parser.add_argument(
        "--smoke-seconds", type=float, default=0.0, help="automatically exit after N seconds"
    )
    return parser.parse_args()


def main() -> int:
    global _CONTROLLER
    args = parse_args()
    if not acquire_single_instance():
        print("Kiro Desktop Pet is already running", file=sys.stderr)
        return 2

    config = AppConfig()
    logger = configure_logging()
    settings = SettingsStore()
    aggregator = SessionAggregator(config)
    monitor = KiroLogMonitor(config, aggregator, settings, logger)
    demo = bool(args.demo_state)
    if demo:
        seed_demo(aggregator, args.demo_state, args.demo_count)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = PetController.alloc().init()
    controller.configureWithConfig_aggregator_monitor_settings_logger_demo_smoke_(
        config, aggregator, monitor, settings, logger, demo, args.smoke_seconds
    )
    _CONTROLLER = controller
    app.setDelegate_(controller)

    def terminate(signum, frame):
        app.terminate_(None)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    logger.info("=== Kiro Desktop Pet 启动 pid=%d demo=%s ===", os.getpid(), args.demo_state or "no")
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
