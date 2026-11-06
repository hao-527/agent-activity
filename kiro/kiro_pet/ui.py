"""Native Cocoa window, interaction and menu bar item for the desktop pet."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import logging
import subprocess
import time

import objc
from AppKit import (
    NSApp,
    NSAppearanceNameAqua,
    NSAppearanceNameDarkAqua,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSCursor,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagOption,
    NSFloatingWindowLevel,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSNormalWindowLevel,
    NSPanel,
    NSScreen,
    NSStatusBar,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSTrackingMouseMoved,
    NSVariableStatusItemLength,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
)
from Foundation import (
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSNotificationCenter,
    NSObject,
    NSTimer,
)

from . import presence, render
from .config import (
    APP_LOG_FILE,
    JUMP_REQUEST_FILE,
    KIRO_BUNDLE_ID,
    STATUS_FILE,
    AppConfig,
    SettingsStore,
)
from .layout import (
    Box,
    SCALE_LABELS,
    clamp,
    collapsed_layout,
    docked_flush_origin,
    SCALE_ORDER,
    VALID_EDGES,
    compute_layout,
    docked_origin,
    expanded_origin,
    format_duration,
    format_duration_short,
    nearest_edge,
)
from .monitor import KiroLogMonitor
from .render import BubbleRow, PetScene
from .session_jump import SessionJumper
from . import skins
from .skins import BUILTIN_ID
from .state import PetSnapshot, SessionAggregator, SessionView, session_label
from .status_icon import status_icon
from .theme import PHASE_ICONS, phase_accent, phase_icon, state_accent, theme_for

APPEARANCE_LABELS = {"auto": "跟随系统", "dark": "深色", "light": "浅色"}
HOTKEY_HINT = "⌥⌘P"


class PetView(NSView):
    def initWithFrame_controller_(self, frame, controller):
        self = objc.super(PetView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._controller = controller
        self._mouse_down_origin = None
        self._tracking = None
        self.setToolTip_(
            "Kiro 桌面宠物 · 点任务名跳到该会话 · 拖动移动 · 单击展开详情 · 双击打开 Kiro · 右键菜单"
        )
        self._install_tracking()
        return self

    def isFlipped(self):
        return False

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDownCanMoveWindow(self):
        return True

    def _install_tracking(self):
        if self._tracking is not None:
            self.removeTrackingArea_(self._tracking)
        self._tracking = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingMouseEnteredAndExited
            | NSTrackingMouseMoved
            | NSTrackingActiveAlways
            | NSTrackingInVisibleRect,
            self,
            None,
        )
        self.addTrackingArea_(self._tracking)

    def updateTrackingAreas(self):
        objc.super(PetView, self).updateTrackingAreas()
        self._install_tracking()

    def mouseEntered_(self, event):
        self._controller.set_hover(True)

    def mouseExited_(self, event):
        self._controller.set_hover(False)

    def mouseMoved_(self, event):
        self._controller.update_hover_row(
            self.convertPoint_fromView_(event.locationInWindow(), None)
        )

    def resetCursorRects(self):
        objc.super(PetView, self).resetCursorRects()
        for box, session_id in self._controller.hit_rows():
            if session_id:
                self.addCursorRect_cursor_(
                    NSMakeRect(*box.as_tuple()), NSCursor.pointingHandCursor()
                )

    def mouseDown_(self, event):
        if self._controller.is_edge_collapsed:
            self._mouse_down_origin = None
            point = (
                self.convertPoint_fromView_(event.locationInWindow(), None)
                if event is not None
                else None
            )
            if point is not None and self._controller.handle_row_click(point):
                return
            self._controller.begin_dock_drag(event)
            return
        if event.clickCount() >= 2:
            self._mouse_down_origin = None
            self._controller.openKiro_(self)
            return
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        if self._controller.handle_row_click(point):
            self._mouse_down_origin = None
            return
        origin = self.window().frame().origin
        self._mouse_down_origin = (float(origin.x), float(origin.y))
        objc.super(PetView, self).mouseDown_(event)

    def mouseDragged_(self, event):
        if self._controller.is_edge_collapsed:
            self._controller.continue_dock_drag(event)

    def mouseUp_(self, event):
        if self._controller.is_edge_collapsed:
            self._controller.finish_dock_drag(event)
            return
        start = self._mouse_down_origin
        self._mouse_down_origin = None
        if start is None:
            return
        objc.super(PetView, self).mouseUp_(event)
        origin = self.window().frame().origin
        dx = float(origin.x) - start[0]
        dy = float(origin.y) - start[1]
        if dx * dx + dy * dy > 4.0:
            self._controller.finish_user_drag()
        else:
            self._controller.toggleDetail_(self)

    def menuForEvent_(self, event):
        return self._controller.build_menu()

    def drawRect_(self, dirty_rect):
        self._controller.draw_into_view()


class PetController(NSObject):
    def configureWithConfig_aggregator_monitor_settings_logger_demo_smoke_(
        self,
        config: AppConfig,
        aggregator: SessionAggregator,
        monitor: KiroLogMonitor,
        settings: SettingsStore,
        logger: logging.Logger,
        demo: bool,
        smoke_seconds: float,
    ):
        self.config = config
        self.aggregator = aggregator
        self.monitor = monitor
        self.settings = settings
        self.logger = logger
        self.demo = demo
        self.smoke_seconds = smoke_seconds
        self.jumper = SessionJumper(logger, config=config)
        self.skin = skins.load_skin(settings.settings.skin)
        self.window = None
        self.view = None
        self.status_item = None
        self._status_menu = None
        self._status_timer = None
        self._animation_timer = None
        self._animation_interval = 0.0
        self._presence_timer = None
        self._hotkey_monitor = None
        self._frame_index = 0
        self._last_state = ""
        self._last_rows = -1
        self._hover = False
        self._hover_row = ""
        self._peek_until = 0.0
        self._dock_drag = None
        self._settle_timer = None
        # Injectable so the drag maths can be exercised without a real cursor.
        self._pointer = NSEvent.mouseLocation
        self._jump_request_seen = 0
        self._screen_change_timer = None
        self._snap_hint = ""
        self._programmatic_move = False
        return self

    # -- lifecycle -----------------------------------------------------------
    def applicationDidFinishLaunching_(self, notification):
        self._create_window()
        self._create_status_item()
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "screensChanged:", "NSApplicationDidChangeScreenParametersNotification", None
        )
        if not self.demo:
            if self.settings.settings.monitor_paused:
                self.monitor.set_paused(True)
            self.monitor.start()
            self._refresh_presence()
            self._presence_timer = self._make_timer(
                self.config.presence_refresh_interval, "refreshPresence:", True
            )
        if self.settings.settings.hotkey_enabled:
            self._install_hotkey()
        if self.is_edge_collapsed:
            self.collapse_to_edge(self.settings.settings.docked_edge, persist=False, animate=False)
        if self.settings.settings.pet_visible:
            self.window.orderFrontRegardless()
            self.logger.info("桌面宠物窗口已显示")
        else:
            self.window.orderOut_(self)
            self.logger.info("桌面宠物窗口已隐藏，菜单栏入口保持可用")
        self._retune_animation_timer(force=True)
        if self.smoke_seconds > 0:
            self._smoke_timer = self._make_timer(self.smoke_seconds, "quit:", False)

    def applicationWillTerminate_(self, notification):
        for attribute in (
            "_status_timer",
            "_animation_timer",
            "_presence_timer",
            "_settle_timer",
        ):
            timer = getattr(self, attribute, None)
            if timer is not None:
                timer.invalidate()
                setattr(self, attribute, None)
        self._remove_hotkey()
        try:
            NSNotificationCenter.defaultCenter().removeObserver_(self)
        except Exception:
            pass
        if self.status_item is not None:
            NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
            self.status_item = None
        self.monitor.stop()
        self.settings.save()
        self.logger.info("Kiro 桌面宠物退出")

    def _make_timer(self, interval: float, selector: str, repeats: bool):
        return NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            interval, self, selector, None, repeats
        )

    # -- state ---------------------------------------------------------------
    @property
    def is_edge_collapsed(self) -> bool:
        return self.settings.settings.docked_edge in VALID_EDGES

    def current_snapshot(self) -> PetSnapshot:
        return self.aggregator.snapshot()

    def theme(self):
        mode = self.settings.settings.appearance
        if mode == "dark":
            return theme_for(True)
        if mode == "light":
            return theme_for(False)
        return theme_for(self._system_dark())

    def _system_dark(self) -> bool:
        try:
            appearance = NSApp.effectiveAppearance()
            match = appearance.bestMatchFromAppearancesWithNames_(
                [NSAppearanceNameAqua, NSAppearanceNameDarkAqua]
            )
            return str(match) == str(NSAppearanceNameDarkAqua)
        except Exception:
            return True

    def pet_scale(self) -> float:
        return compute_layout(self.settings.settings.pet_scale, 1).scale

    def tab_thickness(self, scale: float | None = None) -> float:
        """Rail thickness follows the pet size, like every other measurement."""
        scale = self.pet_scale() if scale is None else scale
        return float(round(self.config.edge_tab_visible * scale))

    def _canvas_bounds(self) -> tuple[float, float]:
        visible = self._visible_frame()
        return (float(visible.size.width) - 8.0, float(visible.size.height) - 8.0)

    def _card_open(self) -> bool:
        """The preview card shows on hover, or while an auto peek is running."""
        return bool(self._hover or self._peek_until > time.time())

    def _collapsed_capacity(self) -> int:
        return int(self.config.collapsed_rows) if self._card_open() else 0

    def collapsed_rail(self, rows_count: int, snapshot=None):
        """Rail geometry for the docked window, sized to its own content."""
        scale = self.pet_scale()
        snapshot = snapshot if snapshot is not None else self.current_snapshot()
        bounds = self._canvas_bounds()
        return collapsed_layout(
            self.settings.settings.docked_edge or "left",
            scale,
            rows_count,
            self.tab_thickness(scale),
            with_badge=snapshot.active_count > 0 or bool(snapshot.flash),
            with_arrow=self._hover,
            max_width=bounds[0],
            max_height=bounds[1],
        )

    def _tab_caption(self, snapshot: PetSnapshot) -> str:
        # The side rail is only 36px wide, so it needs the compact form.
        compact = self.settings.settings.docked_edge != "bottom"
        if any(item.phase == "waiting" for item in snapshot.sessions):
            return "待确认"
        if snapshot.active_count > 1:
            return f"{snapshot.active_count} 个"
        running = [
            item for item in snapshot.sessions if item.phase in ("running", "waiting")
        ]
        if running:
            longest = min(running, key=lambda item: item.started_at or time.time())
            if longest.started_at:
                elapsed = time.time() - longest.started_at
                return format_duration_short(elapsed) if compact else format_duration(elapsed)
            return "运行中"
        if snapshot.flash == "success" or snapshot.overall == "success":
            return "完成"
        if snapshot.flash == "error" or snapshot.overall == "error":
            return "异常"
        if snapshot.flash == "cancelled" or snapshot.overall == "cancelled":
            return "取消"
        if snapshot.overall == "offline":
            return "离线"
        return "待命"

    def frame_state(self):
        snapshot = self.current_snapshot()
        if self.is_edge_collapsed:
            capacity = self._collapsed_capacity()
            rows = self._rows_for(snapshot, capacity) if capacity else ()
            # Keep the window itself a stable size while docked so the rail
            # geometry and the restored position never drift.
            layout = compute_layout(
                self.settings.settings.pet_scale,
                self.config.compact_rows,
                self.settings.settings.show_bubble,
            )
            return snapshot, rows, layout
        rows = self._rows_for(snapshot)
        layout = compute_layout(
            self.settings.settings.pet_scale, len(rows), self.settings.settings.show_bubble
        )
        return snapshot, rows, layout

    def _row_limit(self) -> int:
        if self.settings.settings.detail_expanded or self._hover:
            return int(self.config.detail_rows)
        return int(self.config.compact_rows)

    def _collapsed_rail(self, layout, rows, snapshot=None):
        return self.collapsed_rail(len(rows), snapshot)

    @staticmethod
    def _row_time(view: SessionView, now: float) -> str:
        if view.phase in ("running", "waiting"):
            return format_duration(now - view.started_at) if view.started_at else "进行中"
        anchor = view.completed_at or view.updated_at
        if not anchor:
            return ""
        delta = max(0.0, now - anchor)
        return "刚刚" if delta < 5 else f"{format_duration(delta)}前"

    def _rows_for(self, snapshot: PetSnapshot, limit: int | None = None) -> tuple[BubbleRow, ...]:
        if limit is None and not self.settings.settings.show_bubble:
            return ()
        if snapshot.overall == "offline" or not snapshot.sessions:
            return (
                BubbleRow(
                    accent=phase_accent("idle"),
                    title=snapshot.subline or "暂无会话",
                    muted=True,
                ),
            )
        now = time.time()
        limit = self._row_limit() if limit is None else max(1, int(limit))
        waiting = [item for item in snapshot.sessions if item.phase == "waiting"]
        running = [item for item in snapshot.sessions if item.phase == "running"]
        others = [
            item for item in snapshot.sessions if item.phase not in ("running", "waiting")
        ]
        ordered = waiting + running + others
        visible = ordered[:limit]
        hidden = len(ordered) - len(visible)
        if hidden > 0 and limit >= 2:
            visible = ordered[: limit - 1]
            hidden = len(ordered) - len(visible)
        rows = [
            BubbleRow(
                accent=phase_accent(item.phase),
                title=session_label(item),
                time_text=self._row_time(item, now),
                active=item.phase in ("running", "waiting"),
                session_id=item.session_id,
            )
            for item in visible
        ]
        if hidden > 0:
            rows.append(
                BubbleRow(accent=phase_accent("idle"), title=f"还有 {hidden} 个会话", muted=True)
            )
        elif len(rows) == 1 and visible and visible[0].detail and limit >= 2:
            rows.append(
                BubbleRow(accent=phase_accent("idle"), title=visible[0].detail, muted=True)
            )
        return tuple(rows)

    # -- drawing -------------------------------------------------------------
    def hit_rows(self) -> tuple[tuple[Box, str], ...]:
        """Clickable task rectangles for the bubble or for the docked card."""
        snapshot, rows, layout = self.frame_state()
        if self.is_edge_collapsed:
            rail = self._collapsed_rail(layout, rows, snapshot)
            if not rail.has_card:
                return ()
            boxes = rail.rows
        else:
            boxes = layout.rows
        hits = []
        for index, row in enumerate(rows[: len(boxes)]):
            box = boxes[index]
            hits.append(
                (Box(box.x - 3.0, box.y, box.width + 6.0, box.height - 2.0), row.session_id)
            )
        return tuple(hits)

    def _session_at(self, point) -> str:
        for box, session_id in self.hit_rows():
            if not session_id:
                continue
            if box.x <= float(point.x) <= box.max_x and box.y <= float(point.y) <= box.max_y:
                return session_id
        return ""

    def update_hover_row(self, point) -> None:
        target = self._session_at(point)
        if target == self._hover_row:
            return
        self._hover_row = target
        if self.view is not None:
            self.view.setNeedsDisplay_(True)
            if self.window is not None:
                self.window.invalidateCursorRectsForView_(self.view)

    def handle_row_click(self, point) -> bool:
        if not self.is_edge_collapsed and not self.settings.settings.show_bubble:
            return False
        session_id = self._session_at(point)
        if not session_id:
            return False
        self.logger.info("点击任务行，准备跳转到 Kiro 会话 %s", session_id)
        self.jumper.jump_async(session_id)
        return True

    def draw_into_view(self) -> None:
        snapshot, rows, layout = self.frame_state()
        if self._hover_row:
            rows = tuple(
                replace(row, highlight=bool(row.session_id) and row.session_id == self._hover_row)
                for row in rows
            )
        scene = PetScene(
            state=snapshot.overall,
            frame=self._frame_index,
            active_count=snapshot.active_count,
            headline=snapshot.headline,
            rows=rows,
            flash=snapshot.flash,
            docked_edge=self.settings.settings.docked_edge if self.is_edge_collapsed else "",
            tab_thickness=self.tab_thickness(layout.scale),
            # Upper bound is the screen, never the window: feeding the window
            # size back in would shrink the rail a little on every redraw.
            canvas=self._canvas_bounds(),
            tab_caption=self._tab_caption(snapshot),
            snap_hint=self._snap_hint,
            show_bubble=self.settings.settings.show_bubble,
            hover=self._hover,
            skin=self.skin,
        )
        render.draw_scene(scene, layout, self.theme())

    def animate_(self, timer):
        if self.window is None or self.view is None:
            return
        snapshot, rows, layout = self.frame_state()
        if snapshot.overall != self._last_state:
            self._last_state = snapshot.overall
            self._frame_index = 0
            self._retune_animation_timer()
        else:
            self._frame_index = (self._frame_index + 1) % skins.frame_count(snapshot.overall, self.skin)
        self._service_peek(snapshot)
        if self.is_edge_collapsed:
            self._last_rows = len(rows)
        elif len(rows) != self._last_rows:
            self._last_rows = len(rows)
            self._apply_layout(layout)
        elif abs(float(self.window.frame().size.width) - layout.width) > 0.5:
            self._apply_layout(layout)
        self.view.setNeedsDisplay_(True)

    def _service_peek(self, snapshot: PetSnapshot) -> None:
        """Briefly slide the rail out when something finished while docked."""
        if not self.is_edge_collapsed:
            self._peek_until = 0.0
            return
        now = time.time()
        trigger = snapshot.flash or (
            snapshot.overall if snapshot.overall in ("success", "error", "cancelled") else ""
        )
        signature = f"{trigger}:{snapshot.flash_title or snapshot.subline}"
        if (
            trigger
            and self.settings.settings.auto_peek
            and signature != getattr(self, "_peek_signature", "")
        ):
            self._peek_signature = signature
            self._peek_until = now + float(self.config.auto_peek_seconds)
            self.logger.info("收起状态下检测到「%s」，自动探头提示", trigger)
            self._sync_dock()
            return
        if not trigger:
            self._peek_signature = ""
        if self._peek_until and now >= self._peek_until:
            self._peek_until = 0.0
            self._sync_dock()

    def _sync_dock(self) -> None:
        """Re-fit the docked window when the card opens or closes."""
        if not self.is_edge_collapsed or self.window is None:
            return
        self._apply_dock_frame(animate=True)
        self.view.setNeedsDisplay_(True)

    def _retune_animation_timer(self, force: bool = False) -> None:
        if self.is_edge_collapsed:
            interval = (
                self.config.animation_interval
                if self._hover or self._peek_until > time.time()
                else self.config.docked_animation_interval
            )
        elif self._last_state in ("running", "multi", "success", "error"):
            interval = self.config.animation_interval
        else:
            interval = self.config.idle_animation_interval
        if not force and abs(interval - self._animation_interval) < 0.01:
            return
        if self._animation_timer is not None:
            self._animation_timer.invalidate()
        self._animation_interval = interval
        self._animation_timer = self._make_timer(interval, "animate:", True)

    # -- window --------------------------------------------------------------
    def _create_window(self) -> None:
        layout = self.frame_state()[2]
        x, y = self._initial_position(layout.width, layout.height)
        saved_x = self.settings.settings.x
        saved_y = self.settings.settings.y
        if saved_x is not None and saved_y is not None and (
            abs(float(saved_x) - x) > 1 or abs(float(saved_y) - y) > 1
        ):
            # Saved coordinates pointed at a display that is no longer attached.
            # Persist the correction so the stale position cannot resurface.
            self.logger.info(
                "保存的位置 (%.0f, %.0f) 已不在任何屏幕上，改为 (%.0f, %.0f)",
                float(saved_x),
                float(saved_y),
                x,
                y,
            )
            self.settings.settings.x = float(x)
            self.settings.settings.y = float(y)
            self.settings.save()
        frame = NSMakeRect(x, y, layout.width, layout.height)
        self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setHasShadow_(True)
        self.window.setHidesOnDeactivate_(False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setMovableByWindowBackground_(True)
        self.window.setIgnoresMouseEvents_(False)
        self.window.setAcceptsMouseMovedEvents_(True)
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.window.setLevel_(
            NSFloatingWindowLevel if self.settings.settings.always_on_top else NSNormalWindowLevel
        )
        self.window.setDelegate_(self)
        self.view = PetView.alloc().initWithFrame_controller_(
            NSMakeRect(0, 0, layout.width, layout.height), self
        )
        self.window.setContentView_(self.view)

    def _apply_layout(self, layout) -> None:
        """Resize bottom-aligned so the pet itself never jumps on screen."""
        if self.window is None:
            return
        frame = self.window.frame()
        if (
            abs(float(frame.size.width) - layout.width) < 0.5
            and abs(float(frame.size.height) - layout.height) < 0.5
        ):
            return
        self._begin_programmatic()
        self.window.setFrame_display_(
            NSMakeRect(frame.origin.x, frame.origin.y, layout.width, layout.height), True
        )
        self._end_programmatic()
        if self.is_edge_collapsed:
            self.collapse_to_edge(
                self.settings.settings.docked_edge, persist=False, animate=False
            )

    def _initial_position(self, width: float, height: float) -> tuple[float, float]:
        screens = NSScreen.screens()
        main = NSScreen.mainScreen()
        visible = main.visibleFrame()
        default_x = visible.origin.x + visible.size.width - width - 24
        default_y = visible.origin.y + 28
        x = self.settings.settings.x
        y = self.settings.settings.y
        if x is None or y is None:
            return default_x, default_y
        for screen in screens:
            area = screen.visibleFrame()
            if (
                x + width > area.origin.x
                and x < area.origin.x + area.size.width
                and y + height > area.origin.y
                and y < area.origin.y + area.size.height
            ):
                clamped_x = min(max(x, area.origin.x), area.origin.x + area.size.width - width)
                clamped_y = min(max(y, area.origin.y), area.origin.y + area.size.height - height)
                return clamped_x, clamped_y
        return default_x, default_y

    def _dock_anchor(self):
        """Centre of the docked rail, used to pick the right display.

        A rail sitting flush against an edge can touch two displays, and
        ``window.screen()`` may then report the neighbour, so anchor on the
        rail's own centre instead.
        """
        if self.window is None or not self.is_edge_collapsed:
            return None
        frame = self.window.frame()
        return (
            float(frame.origin.x + frame.size.width / 2),
            float(frame.origin.y + frame.size.height / 2),
        )

    def _visible_frame(self):
        anchor = self._dock_anchor()
        if anchor is not None:
            for candidate in NSScreen.screens():
                area = candidate.frame()
                if (
                    area.origin.x <= anchor[0] <= area.origin.x + area.size.width
                    and area.origin.y <= anchor[1] <= area.origin.y + area.size.height
                ):
                    return candidate.visibleFrame()
        screen = self.window.screen() if self.window is not None else None
        if screen is not None:
            return screen.visibleFrame()
        frame = self.window.frame()
        center_x = frame.origin.x + frame.size.width / 2
        center_y = frame.origin.y + frame.size.height / 2
        screens = list(NSScreen.screens())
        for candidate in screens:
            area = candidate.frame()
            if (
                area.origin.x <= center_x <= area.origin.x + area.size.width
                and area.origin.y <= center_y <= area.origin.y + area.size.height
            ):
                return candidate.visibleFrame()
        if screens:
            selected = min(
                screens,
                key=lambda candidate: (
                    center_x - (candidate.frame().origin.x + candidate.frame().size.width / 2)
                )
                ** 2
                + (
                    center_y - (candidate.frame().origin.y + candidate.frame().size.height / 2)
                )
                ** 2,
            )
            return selected.visibleFrame()
        return NSScreen.mainScreen().visibleFrame()

    def windowDidMove_(self, notification):
        if self.window is None or self._programmatic_move or self.is_edge_collapsed:
            return
        frame = self.window.frame()
        self.settings.settings.x = float(frame.origin.x)
        self.settings.settings.y = float(frame.origin.y)
        self.settings.save()
        visible = self._visible_frame()
        hint = nearest_edge(
            frame.origin.x,
            frame.origin.y,
            frame.size.width,
            frame.size.height,
            visible.origin.x,
            visible.origin.y,
            visible.size.width,
            visible.size.height,
            self.config.edge_snap_distance,
        )
        if hint != self._snap_hint:
            self._snap_hint = hint
            self.view.setNeedsDisplay_(True)
        # A window drag driven by AppKit does not always deliver mouseUp to the
        # view, so the snap decision is made once the window stops moving.
        if self._settle_timer is not None:
            self._settle_timer.invalidate()
        self._settle_timer = self._make_timer(
            self.config.drag_settle_delay, "settleDrag:", False
        )

    def settleDrag_(self, timer):
        self._settle_timer = None
        if self._programmatic_move or self.is_edge_collapsed or self.window is None:
            return
        self.finish_user_drag()

    def screensChanged_(self, notification):
        """Debounce screen-change events (macOS fires multiple in rapid succession)."""
        if self._screen_change_timer is not None:
            self._screen_change_timer.invalidate()
        self._screen_change_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "_applyScreenChange:", None, False
        )

    def _applyScreenChange_(self, timer):
        """Actually reposition the pet after a debounced screen change."""
        self._screen_change_timer = None
        if self.window is None:
            return
        if self.is_edge_collapsed:
            self.collapse_to_edge(
                self.settings.settings.docked_edge, persist=False, animate=False
            )
            return
        frame = self.window.frame()
        x, y = self._initial_position(frame.size.width, frame.size.height)
        self._begin_programmatic()
        self.window.setFrame_display_(
            NSMakeRect(x, y, frame.size.width, frame.size.height), True
        )
        self._end_programmatic()
        self.settings.settings.x = float(x)
        self.settings.settings.y = float(y)
        self.settings.save()
        self.logger.info("屏幕参数变化，桌宠已回到可见区域")

    # -- hover, docking, drag ------------------------------------------------
    def _pointer_inside_window(self) -> bool:
        if self.window is None:
            return False
        try:
            point = self._pointer()
        except Exception:
            return False
        frame = self.window.frame()
        return (
            frame.origin.x - 1 <= float(point.x) <= frame.origin.x + frame.size.width + 1
            and frame.origin.y - 1 <= float(point.y) <= frame.origin.y + frame.size.height + 1
        )

    def set_hover(self, hovering: bool) -> None:
        if self._hover == hovering:
            return
        if (
            not hovering
            and self.is_edge_collapsed
            and self._pointer_inside_window()
        ):
            # Transparent parts of the rail can report an exit while the pointer
            # is still over the window; the status timer closes it for real.
            return
        self._hover = hovering
        if not hovering:
            self._hover_row = ""
        if self.is_edge_collapsed:
            self._retune_animation_timer()
            self._sync_dock()
            if self.view is not None:
                self.view.setNeedsDisplay_(True)
        elif self.view is not None:
            self._last_rows = -1
            self.view.setNeedsDisplay_(True)

    def finish_user_drag(self) -> None:
        if self.window is None or self.is_edge_collapsed:
            return
        if self._settle_timer is not None:
            self._settle_timer.invalidate()
            self._settle_timer = None
        self._snap_hint = ""
        frame = self.window.frame()
        visible = self._visible_frame()
        edge = nearest_edge(
            frame.origin.x,
            frame.origin.y,
            frame.size.width,
            frame.size.height,
            visible.origin.x,
            visible.origin.y,
            visible.size.width,
            visible.size.height,
            self.config.edge_snap_distance,
        )
        if edge:
            self.logger.info(
                "拖动停稳在 %s 边缘（阈值 %.0fpx），收起为侧边栏",
                edge,
                self.config.edge_snap_distance,
            )
            self.collapse_to_edge(edge)
        elif self.view is not None:
            self.view.setNeedsDisplay_(True)

    def collapse_to_edge(self, edge: str, persist: bool = True, animate: bool = True) -> None:
        if edge not in VALID_EDGES or self.window is None:
            return
        frame = self.window.frame()
        first = not self.is_edge_collapsed
        if first and not self._programmatic_move:
            # Only the expanded geometry lives in x/y; the rail keeps its own
            # along-edge offset.
            self.settings.settings.x = float(frame.origin.x)
            self.settings.settings.y = float(frame.origin.y)
        self.settings.settings.docked_edge = edge
        self._snap_hint = ""
        if first or self.settings.settings.dock_offset is None:
            self.settings.settings.dock_offset = float(
                frame.origin.x if edge == "bottom" else frame.origin.y
            )
        if persist:
            self.settings.save()
        self._apply_dock_frame(animate)
        # While docked the pet handles its own dragging so it can only slide
        # along the edge instead of being pulled back onto the desktop.
        self.window.setMovableByWindowBackground_(False)
        self._retune_animation_timer()
        self.view.setNeedsDisplay_(True)
        if first:
            rail = self.collapsed_rail(self._collapsed_capacity())
            self.logger.info(
                "已收起到 %s 边缘，侧边栏 %.0fx%.0f", edge, rail.width, rail.height
            )

    def _apply_dock_frame(self, animate: bool = True) -> None:
        """Resize the window down to the rail and stick it to the edge.

        Keeping the full pet window and pushing it off screen would leave a
        large transparent region that still swallows clicks, so the docked
        window is exactly as big as what it draws.
        """
        if self.window is None or not self.is_edge_collapsed:
            return
        edge = self.settings.settings.docked_edge
        snapshot = self.current_snapshot()
        rows = self._rows_for(snapshot, self._collapsed_capacity()) if self._collapsed_capacity() else ()
        rail = self.collapsed_rail(len(rows), snapshot)
        visible = self._visible_frame()
        frame = self.window.frame()
        offset = self.settings.settings.dock_offset
        if offset is None:
            offset = float(frame.origin.x if edge == "bottom" else frame.origin.y)
        x, y = docked_flush_origin(
            edge,
            rail.width,
            rail.height,
            visible.origin.x,
            visible.origin.y,
            visible.size.width,
            visible.size.height,
            float(offset),
        )
        target = NSMakeRect(x, y, rail.width, rail.height)
        # The handle must not move when the card opens: a handle that slides out
        # from under the pointer makes hover flicker open/closed. Right-edge
        # rails grow leftwards, so compensate the origin by the handle shift.
        if edge == "right":
            rest = self.collapsed_rail(0, snapshot)
            handle_shift = (rail.width - rail.tab.x) - (rest.width - rest.tab.x)
            target = NSMakeRect(x + handle_shift, y, rail.width, rail.height)
        if (
            abs(float(frame.origin.x) - x) < 0.5
            and abs(float(frame.origin.y) - y) < 0.5
            and abs(float(frame.size.width) - rail.width) < 0.5
            and abs(float(frame.size.height) - rail.height) < 0.5
        ):
            return
        self._begin_programmatic()
        try:
            self.window.setFrame_display_animate_(target, True, bool(animate))
        finally:
            self._end_programmatic()

    def begin_dock_drag(self, event) -> None:
        if self.window is None:
            return
        location = self._pointer()
        frame = self.window.frame()
        self._dock_drag = {
            "mouse": (float(location.x), float(location.y)),
            "origin": (float(frame.origin.x), float(frame.origin.y)),
            "moved": 0.0,
        }

    def continue_dock_drag(self, event) -> None:
        drag = self._dock_drag
        if drag is None or self.window is None:
            return
        location = self._pointer()
        dx = float(location.x) - drag["mouse"][0]
        dy = float(location.y) - drag["mouse"][1]
        drag["moved"] = max(drag["moved"], (dx * dx + dy * dy) ** 0.5)
        frame = self.window.frame()
        visible = self._visible_frame()
        edge = self.settings.settings.docked_edge
        if edge == "bottom":
            x, y = docked_flush_origin(
                edge, frame.size.width, frame.size.height,
                visible.origin.x, visible.origin.y, visible.size.width, visible.size.height,
                drag["origin"][0] + dx,
            )
        else:
            x, y = docked_flush_origin(
                edge, frame.size.width, frame.size.height,
                visible.origin.x, visible.origin.y, visible.size.width, visible.size.height,
                drag["origin"][1] + dy,
            )
        self._begin_programmatic()
        self.window.setFrameOrigin_(NSMakePoint(x, y))
        self._end_programmatic()
        self.view.setNeedsDisplay_(True)

    def finish_dock_drag(self, event) -> None:
        drag = self._dock_drag
        self._dock_drag = None
        if drag is None:
            return
        if drag["moved"] < 4.0:
            self.expandFromEdge_(self)
            return
        frame = self.window.frame()
        edge = self.settings.settings.docked_edge
        self.settings.settings.dock_offset = float(
            frame.origin.x if edge == "bottom" else frame.origin.y
        )
        self.settings.save()
        self.logger.info("桌宠已沿 %s 边缘调整收起位置", edge)

    def expandFromEdge_(self, sender):
        edge = self.settings.settings.docked_edge
        if edge not in VALID_EDGES or self.window is None:
            return
        visible = self._visible_frame()
        # The docked window shrank to the rail, so restore the pet size first.
        full = compute_layout(
            self.settings.settings.pet_scale,
            self.config.compact_rows,
            self.settings.settings.show_bubble,
        )
        current = self.window.frame()
        self._begin_programmatic()
        try:
            self.window.setFrame_display_(
                NSMakeRect(current.origin.x, current.origin.y, full.width, full.height), False
            )
        finally:
            self._end_programmatic()
        frame = self.window.frame()
        saved_x = self.settings.settings.x
        saved_y = self.settings.settings.y
        if saved_x is None:
            saved_x = float(frame.origin.x)
        if saved_y is None:
            saved_y = float(frame.origin.y)
        x, y = expanded_origin(
            edge,
            frame.size.width,
            frame.size.height,
            visible.origin.x,
            visible.origin.y,
            visible.size.width,
            visible.size.height,
            saved_x,
            saved_y,
        )
        self.settings.settings.docked_edge = ""
        self.settings.settings.x = x
        self.settings.settings.y = y
        self.settings.save()
        self._peek_until = 0.0
        self._peek_signature = ""
        self.window.setMovableByWindowBackground_(True)
        self._set_programmatic_frame(x, y, True)
        self.window.orderFrontRegardless()
        self._last_rows = -1
        self._retune_animation_timer()
        self.view.setNeedsDisplay_(True)

    def _begin_programmatic(self) -> None:
        self._programmatic_move = True

    def _end_programmatic(self) -> None:
        self._programmatic_move = False

    def _set_programmatic_frame(self, x: float, y: float, animate: bool) -> None:
        """Move synchronously so the docked geometry is exact when we return."""
        frame = self.window.frame()
        target = NSMakeRect(x, y, frame.size.width, frame.size.height)
        self._begin_programmatic()
        try:
            self.window.setFrame_display_animate_(target, True, bool(animate))
        finally:
            self._end_programmatic()

    # -- menu bar ------------------------------------------------------------
    def _create_status_item(self) -> None:
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._status_menu = NSMenu.alloc().initWithTitle_("Kiro 桌面宠物")
        self._status_menu.setDelegate_(self)
        self.status_item.setMenu_(self._status_menu)
        self.refreshStatus_(None)
        self._status_timer = self._make_timer(
            self.config.status_refresh_interval, "refreshStatus:", True
        )

    def _status_icon(self, accent: str, count: int) -> NSImage:
        button = self.status_item.button() if self.status_item is not None else None
        appearance = button.effectiveAppearance() if button is not None else None
        return status_icon(accent, appearance, count)

    def refreshStatus_(self, timer):
        if self.status_item is None:
            return
        snapshot = self.current_snapshot()
        button = self.status_item.button()
        if button is None:
            return
        button.setImage_(self._status_icon(state_accent(snapshot.overall), snapshot.active_count))
        button.setTitle_("")
        button.setAccessibilityLabel_(snapshot.headline)
        tooltip = snapshot.headline
        if snapshot.subline:
            tooltip = f"{tooltip}\n{snapshot.subline}"
        if not self.settings.settings.pet_visible:
            tooltip = f"{tooltip}\n桌宠已隐藏，点这里 > 显示桌宠"
        button.setToolTip_(tooltip)
        if self._hover and self.is_edge_collapsed and not self._pointer_inside_window():
            self.set_hover(False)
        self._consume_jump_request()

    def _consume_jump_request(self, max_age: float = 300.0) -> str:
        """Handle a click on one of our notifications."""
        try:
            stamp = JUMP_REQUEST_FILE.stat().st_mtime_ns
        except OSError:
            return ""
        if stamp == self._jump_request_seen:
            return ""
        self._jump_request_seen = stamp
        try:
            payload = json.loads(JUMP_REQUEST_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        session_id = str(payload.get("session_id", "") or "")
        if not session_id.startswith("sess_"):
            return ""
        try:
            requested_at = float(payload.get("at", 0))
        except (TypeError, ValueError):
            requested_at = 0.0
        # Ignore requests left over from an earlier run of the pet.
        if requested_at <= 0 or abs(time.time() - requested_at) > max_age:
            return ""
        self.logger.info("通知被点击，准备跳转到 Kiro 会话 %s", session_id)
        self.jumper.jump_async(session_id)
        return session_id

    def refreshPresence_(self, timer):
        self._refresh_presence()

    def _refresh_presence(self) -> None:
        if self.demo:
            return
        if self.aggregator.set_kiro_running(presence.kiro_running()):
            self.monitor.publisher.publish(self.aggregator.snapshot())
            if self.view is not None:
                self.view.setNeedsDisplay_(True)

    def menuNeedsUpdate_(self, menu):
        snapshot = self.current_snapshot()
        now = time.time()
        menu.removeAllItems()
        self._add_disabled(menu, snapshot.headline)
        self._add_disabled(
            menu,
            f"运行 {snapshot.active_count} · 最近 {snapshot.total_sessions}"
            f" · 日志 {snapshot.log_count} · Kiro {'在运行' if snapshot.kiro_running else '未运行'}",
        )
        self._add_disabled(menu, self.monitor.stats.summary_line(now))
        retry_line = self.monitor.retry.status_line(now)
        if retry_line:
            self._add_disabled(menu, retry_line)
        if not self.settings.settings.pet_visible:
            self._add_disabled(menu, "桌宠已隐藏 · 点下面「显示桌宠」找回")
        menu.addItem_(NSMenuItem.separatorItem())
        if snapshot.sessions:
            for session in snapshot.sessions:
                label = session_label(session)
                title = (
                    f"{phase_icon(session.phase)} {label} · {self._row_time(session, now)}"
                    f" · {session.detail or '暂无详情'}"
                )
                item = self._add_item(menu, title, "sessionClicked:")
                item.setRepresentedObject_(session.session_id)
        else:
            self._add_disabled(menu, "暂无会话事件")
        menu.addItem_(NSMenuItem.separatorItem())
        self._add_item(
            menu,
            "隐藏桌宠" if self.settings.settings.pet_visible else "显示桌宠",
            "togglePetVisibility:",
        )
        self._add_item(
            menu,
            "展开桌宠" if self.is_edge_collapsed else "收起到屏幕边缘",
            "toggleEdgeDock:",
        )
        self._check(
            self._add_item(menu, "展开全部任务", "toggleDetail:"),
            self.settings.settings.detail_expanded,
        )
        self._check(
            self._add_item(menu, "收起时自动探头", "toggleAutoPeek:"),
            self.settings.settings.auto_peek,
        )
        self._check(
            self._add_item(menu, "通知提醒", "toggleNotify:"),
            self.settings.settings.notifications_enabled,
        )
        self._check(
            self._add_item(menu, "通知提示音", "toggleNotifySound:"),
            self.settings.settings.notify_sound_enabled,
        )
        self._check(
            self._add_item(menu, "中断后自动重试", "toggleAutoRetry:"),
            self.settings.settings.auto_retry,
        )
        self._add_submenu_choices(
            menu,
            "宠物尺寸",
            [(SCALE_LABELS[name], name) for name in SCALE_ORDER],
            self.settings.settings.pet_scale,
            "setScale:",
        )
        self._add_submenu_choices(
            menu,
            "更换形象",
            [(info.name, info.id) for info in skins.list_skins()],
            self.settings.settings.skin,
            "setSkin:",
        )
        self._add_submenu_choices(
            menu,
            "外观",
            [(APPEARANCE_LABELS[name], name) for name in ("auto", "dark", "light")],
            self.settings.settings.appearance,
            "setAppearance:",
        )
        self._add_item(menu, "立即重扫", "rescan:")
        menu.addItem_(NSMenuItem.separatorItem())
        self._add_item(menu, "打开 Kiro", "openKiro:")
        self._add_item(menu, "打开运行日志", "openLog:")
        self._add_item(menu, "退出桌宠", "quit:")

    def build_menu(self):
        snapshot = self.current_snapshot()
        now = time.time()
        menu = NSMenu.alloc().initWithTitle_("Kiro 桌面宠物")
        self._add_item(menu, "打开 Kiro", "openKiro:")
        menu.addItem_(NSMenuItem.separatorItem())
        self._add_item(
            menu,
            "隐藏桌宠" if self.settings.settings.pet_visible else "显示桌宠",
            "togglePetVisibility:",
        )
        self._add_item(
            menu,
            "展开桌宠" if self.is_edge_collapsed else "收起到屏幕边缘",
            "toggleEdgeDock:",
        )
        self._check(
            self._add_item(menu, "展开全部任务", "toggleDetail:"),
            self.settings.settings.detail_expanded,
        )
        self._check(
            self._add_item(menu, "收起时自动探头", "toggleAutoPeek:"),
            self.settings.settings.auto_peek,
        )
        self._check(
            self._add_item(menu, "显示状态气泡", "toggleBubble:"),
            self.settings.settings.show_bubble,
        )
        self._check(
            self._add_item(menu, "始终置顶", "toggleTop:"),
            self.settings.settings.always_on_top,
        )
        self._add_submenu_choices(
            menu,
            "宠物尺寸",
            [(SCALE_LABELS[name], name) for name in SCALE_ORDER],
            self.settings.settings.pet_scale,
            "setScale:",
        )
        self._add_submenu_choices(
            menu,
            "更换形象",
            [(info.name, info.id) for info in skins.list_skins()],
            self.settings.settings.skin,
            "setSkin:",
        )
        self._add_submenu_choices(
            menu,
            "外观",
            [(APPEARANCE_LABELS[name], name) for name in ("auto", "dark", "light")],
            self.settings.settings.appearance,
            "setAppearance:",
        )
        pause_title = "恢复日志监控" if self.monitor.paused else "暂停日志监控"
        self._add_item(menu, pause_title, "togglePause:")
        self._add_item(menu, "立即重新扫描日志", "rescan:")
        self._check(
            self._add_item(menu, "通知提醒", "toggleNotify:"),
            self.settings.settings.notifications_enabled,
        )
        self._check(
            self._add_item(menu, "通知提示音", "toggleNotifySound:"),
            self.settings.settings.notify_sound_enabled,
        )
        self._check(
            self._add_item(menu, "中断后自动重试", "toggleAutoRetry:"),
            self.settings.settings.auto_retry,
        )
        self._check(
            self._add_item(menu, f"全局快捷键 {HOTKEY_HINT}", "toggleHotkey:"),
            self.settings.settings.hotkey_enabled,
        )
        self._add_item(menu, "发送测试通知", "testNotify:")

        menu.addItem_(NSMenuItem.separatorItem())
        self._add_disabled(
            menu, f"会话状态 · 运行 {snapshot.active_count} / 最近 {snapshot.total_sessions}"
        )
        self._add_disabled(menu, self.monitor.stats.summary_line(now))
        retry_line = self.monitor.retry.status_line(now)
        if retry_line:
            self._add_disabled(menu, retry_line)
        if snapshot.sessions:
            for session in snapshot.sessions:
                when = (
                    datetime.fromtimestamp(session.updated_at).strftime("%H:%M:%S")
                    if session.updated_at
                    else "--:--"
                )
                item = self._add_item(
                    menu,
                    f"{phase_icon(session.phase)} {session_label(session)} · {when} · {session.detail}",
                    "sessionClicked:",
                )
                item.setRepresentedObject_(session.session_id)
        else:
            self._add_disabled(menu, "暂无会话事件")

        menu.addItem_(NSMenuItem.separatorItem())
        self._add_item(menu, "打开运行日志", "openLog:")
        self._add_item(menu, "打开状态 JSON", "openStatus:")
        self._add_item(menu, "退出桌宠（本次登录）", "quit:")
        return menu

    def _add_item(self, menu, title: str, action: str):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        item.setTarget_(self)
        menu.addItem_(item)
        return item

    def _add_submenu_choices(self, menu, title, choices, current, action):
        parent = self._add_item(menu, title, None)
        submenu = NSMenu.alloc().initWithTitle_(title)
        for label, value in choices:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, action, "")
            item.setTarget_(self)
            item.setRepresentedObject_(value)
            self._check(item, value == current)
            submenu.addItem_(item)
        parent.setSubmenu_(submenu)
        return parent

    @staticmethod
    def _check(item, checked: bool):
        item.setState_(NSControlStateValueOn if checked else NSControlStateValueOff)
        return item

    @staticmethod
    def _add_disabled(menu, title: str):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        item.setEnabled_(False)
        menu.addItem_(item)
        return item

    # -- actions -------------------------------------------------------------
    def openKiro_(self, sender):
        try:
            subprocess.Popen(["/usr/bin/open", "-b", KIRO_BUNDLE_ID])
        except OSError as exc:
            self.logger.warning("无法打开 Kiro: %s", exc)

    def sessionClicked_(self, sender):
        session_id = str(sender.representedObject() or "")
        if not session_id:
            self.openKiro_(sender)
            return
        self.logger.info("菜单点击会话，准备跳转到 %s", session_id)
        self.jumper.jump_async(session_id)

    def togglePetVisibility_(self, sender):
        visible = not self.settings.settings.pet_visible
        self.settings.settings.pet_visible = visible
        self.settings.save()
        if visible:
            self.window.orderFrontRegardless()
            self.logger.info("桌宠已显示（菜单操作）")
        else:
            self.window.orderOut_(self)
            # Hiding persists across restarts, so make the way back obvious:
            # silently vanishing looks identical to a crash.
            self.logger.info("桌宠已隐藏（菜单操作），可从菜单栏图标 > 显示桌宠 找回")
            if not self.demo:
                self.monitor.notifier.send_hint(
                    "桌宠已隐藏",
                    "点菜单栏的 Kiro 图标 > 显示桌宠 就能找回",
                )

    def toggleEdgeDock_(self, sender):
        if self.is_edge_collapsed:
            self.expandFromEdge_(sender)
            return
        frame = self.window.frame()
        visible = self._visible_frame()
        edge = nearest_edge(
            frame.origin.x,
            frame.origin.y,
            frame.size.width,
            frame.size.height,
            visible.origin.x,
            visible.origin.y,
            visible.size.width,
            visible.size.height,
        )
        self.collapse_to_edge(edge)

    def toggleDetail_(self, sender):
        self.settings.settings.detail_expanded = not self.settings.settings.detail_expanded
        self.settings.save()
        self._last_rows = -1
        if self.view is not None:
            self.view.setNeedsDisplay_(True)

    def toggleAutoPeek_(self, sender):
        self.settings.settings.auto_peek = not self.settings.settings.auto_peek
        self.settings.save()
        if not self.settings.settings.auto_peek and self._peek_until:
            self._peek_until = 0.0
            self._sync_dock()

    def toggleBubble_(self, sender):
        self.settings.settings.show_bubble = not self.settings.settings.show_bubble
        self.settings.save()
        self._last_rows = -1
        if self.view is not None:
            self.view.setNeedsDisplay_(True)

    def toggleTop_(self, sender):
        value = not self.settings.settings.always_on_top
        self.settings.settings.always_on_top = value
        self.settings.save()
        self.window.setLevel_(NSFloatingWindowLevel if value else NSNormalWindowLevel)

    def setScale_(self, sender):
        value = str(sender.representedObject() or "")
        if not value or value == self.settings.settings.pet_scale:
            return
        self.settings.settings.pet_scale = value
        self.settings.save()
        self._last_rows = -1
        self._apply_layout(self.frame_state()[2])
        if self.view is not None:
            self.view.setNeedsDisplay_(True)
        self.logger.info("宠物尺寸切换为 %s", value)

    def setSkin_(self, sender):
        value = str(sender.representedObject() or "") or BUILTIN_ID
        if value == self.settings.settings.skin:
            return
        loaded = skins.load_skin(value)
        if value != BUILTIN_ID and loaded is None:
            self.logger.warning("形象包 %s 无法加载，保持当前形象", value)
            return
        self.settings.settings.skin = value
        self.settings.save()
        self.skin = loaded
        self._frame_index = 0
        self._last_rows = -1
        if self.view is not None:
            self.view.setNeedsDisplay_(True)
        self.logger.info("形象已切换为 %s", value)

    def setAppearance_(self, sender):
        value = str(sender.representedObject() or "")
        if not value or value == self.settings.settings.appearance:
            return
        self.settings.settings.appearance = value
        self.settings.save()
        if self.view is not None:
            self.view.setNeedsDisplay_(True)

    def togglePause_(self, sender):
        paused = not self.monitor.paused
        self.monitor.set_paused(paused)
        self.settings.settings.monitor_paused = paused
        self.settings.save()

    def rescan_(self, sender):
        self.monitor.request_rescan()
        self._refresh_presence()
        self.logger.info("用户请求立即重新扫描 Kiro 日志与会话标题")

    def toggleAutoRetry_(self, sender):
        value = not self.settings.settings.auto_retry
        self.settings.settings.auto_retry = value
        self.settings.save()
        self.logger.info("中断后自动重试已%s", "开启" if value else "关闭")

    def toggleNotify_(self, sender):
        self.settings.settings.notifications_enabled = (
            not self.settings.settings.notifications_enabled
        )
        self.settings.save()

    def toggleNotifySound_(self, sender):
        value = not self.settings.settings.notify_sound_enabled
        self.settings.settings.notify_sound_enabled = value
        self.settings.save()
        self.logger.info("通知提示音已%s", "开启" if value else "关闭")
        # 即时反馈：开声音发一条能听到的确认，关声音则静音发送，
        # 让用户点完当场就知道开关是否生效。send_hint 会尊重该开关。
        try:
            self.monitor.notifier.send_hint(
                "通知提示音已开启" if value else "通知提示音已关闭",
                "这是一条示例通知" + ("，能听到提示音" if value else "，已静音"),
            )
        except Exception as exc:
            self.logger.warning("发送提示音反馈通知失败：%s", exc)

    def toggleHotkey_(self, sender):
        enabled = not self.settings.settings.hotkey_enabled
        self.settings.settings.hotkey_enabled = enabled
        self.settings.save()
        if enabled:
            self._install_hotkey()
        else:
            self._remove_hotkey()

    def testNotify_(self, sender):
        try:
            self.monitor.notifier.send_test("success")
            self.logger.info("已发送测试通知")
        except Exception as exc:
            self.logger.warning("发送测试通知失败：%s", exc)

    def openLog_(self, sender):
        NSWorkspace.sharedWorkspace().openFile_(str(APP_LOG_FILE))

    def openStatus_(self, sender):
        NSWorkspace.sharedWorkspace().openFile_(str(STATUS_FILE))

    def quit_(self, sender):
        NSApp.terminate_(self)

    # -- optional global hotkey ---------------------------------------------
    def _install_hotkey(self) -> None:
        if self._hotkey_monitor is not None:
            return

        def handler(event):
            try:
                flags = event.modifierFlags()
                wanted = NSEventModifierFlagCommand | NSEventModifierFlagOption
                if (flags & wanted) != wanted:
                    return
                characters = (event.charactersIgnoringModifiers() or "").lower()
                if characters == "p":
                    self.togglePetVisibility_(self)
            except Exception as exc:
                self.logger.debug("全局快捷键处理失败：%s", exc)

        try:
            self._hotkey_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown, handler
            )
        except Exception as exc:
            self._hotkey_monitor = None
            self.logger.warning("注册全局快捷键失败：%s", exc)
            return
        if self._hotkey_monitor is None:
            self.logger.info(
                "全局快捷键需要系统设置中的输入监控权限，未授权时 %s 不会生效", HOTKEY_HINT
            )
        else:
            self.logger.info("已启用全局快捷键 %s", HOTKEY_HINT)

    def _remove_hotkey(self) -> None:
        if self._hotkey_monitor is None:
            return
        try:
            NSEvent.removeMonitor_(self._hotkey_monitor)
        except Exception:
            pass
        self._hotkey_monitor = None
