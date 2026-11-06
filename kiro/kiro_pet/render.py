"""All Cocoa drawing for the pet window, driven by layout + theme.

The view only forwards a :class:`PetScene`; every rectangle comes from
:mod:`kiro_pet.layout` and every color from :mod:`kiro_pet.theme`, so the
same drawing code works for any scale preset or appearance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import math

from AppKit import (
    NSBezierPath,
    NSColor,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSString,
)
from Foundation import NSMakeRect, NSMakeSize

from . import textkit
from .layout import Box, CollapsedLayout, PetLayout, collapsed_layout
from .sprites import PALETTE, sprite_frame
from .theme import Theme, state_accent


@dataclass(frozen=True)
class BubbleRow:
    accent: str
    title: str
    time_text: str = ""
    active: bool = False
    muted: bool = False
    session_id: str = ""
    highlight: bool = False


@dataclass(frozen=True)
class PetScene:
    state: str
    frame: int
    active_count: int
    headline: str
    rows: tuple[BubbleRow, ...] = field(default_factory=tuple)
    flash: str = ""
    docked_edge: str = ""
    tab_sliver: float = 36.0
    tab_thickness: float = 36.0
    tab_caption: str = ""
    snap_hint: str = ""
    show_bubble: bool = True
    hover: bool = False
    skin: object | None = None
    canvas: tuple[float, float] | None = None


@lru_cache(maxsize=96)
def color(hex_value: str, alpha: float = 1.0):
    value = hex_value.lstrip("#")
    red = int(value[0:2], 16) / 255.0
    green = int(value[2:4], 16) / 255.0
    blue = int(value[4:6], 16) / 255.0
    return NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, float(alpha))


@lru_cache(maxsize=512)
def sprite_image(state: str, frame: int, active_count: int, pixel: float) -> NSImage:
    """Rasterize one pixel frame once and reuse it for every later redraw."""
    sprite = sprite_frame(state, frame, active_count)
    image = NSImage.alloc().initWithSize_(
        NSMakeSize(sprite.width * pixel, sprite.height * pixel)
    )
    image.lockFocus()
    for px, py, key in sprite.pixels:
        color(PALETTE[key]).setFill()
        NSBezierPath.fillRect_(NSMakeRect(px * pixel, py * pixel, pixel, pixel))
    image.unlockFocus()
    return image


def clear_sprite_cache() -> None:
    sprite_image.cache_clear()


def _rounded(box: Box, radius: float):
    return NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(*box.as_tuple()), radius, radius
    )


def _fill_rounded(box: Box, radius: float, hex_color: str, alpha: float = 1.0) -> None:
    color(hex_color, alpha).setFill()
    _rounded(box, radius).fill()


def _stroke_rounded(box: Box, radius: float, hex_color: str, alpha: float, line: float = 1.0) -> None:
    color(hex_color, alpha).setStroke()
    path = _rounded(box.inset(line / 2, line / 2), radius)
    path.setLineWidth_(line)
    path.stroke()


def _fill_oval(box: Box, hex_color: str, alpha: float = 1.0) -> None:
    color(hex_color, alpha).setFill()
    NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(*box.as_tuple())).fill()


def _draw_text(
    text: str,
    box: Box,
    text_font,
    hex_color: str,
    alpha: float = 1.0,
    align: str = "left",
) -> None:
    value = str(text or "")
    if not value or box.width <= 0:
        return
    attrs = {
        NSFontAttributeName: text_font,
        NSForegroundColorAttributeName: color(hex_color, alpha),
    }
    string = NSString.stringWithString_(value)
    size = string.sizeWithAttributes_(attrs)
    y = box.y + (box.height - float(size.height)) / 2
    if align == "right":
        x = box.max_x - float(size.width)
        width = float(size.width)
    elif align == "center":
        x = box.mid_x - float(size.width) / 2
        width = float(size.width)
    else:
        x = box.x
        width = box.width
    string.drawInRect_withAttributes_(
        NSMakeRect(x, y, width, float(size.height) + 1), attrs
    )


def draw_scene(scene: PetScene, layout: PetLayout, theme: Theme) -> None:
    if scene.docked_edge:
        _draw_collapsed(scene, layout, theme)
        return
    if scene.show_bubble and layout.bubble.height > 0:
        _draw_bubble(scene, layout, theme)
        _draw_tail(layout, theme)
    _draw_shadow(layout, theme)
    _draw_sprite(scene, layout)
    if scene.active_count > 0:
        _draw_badge(scene, layout, theme)
    if scene.flash:
        _draw_flash(scene, layout)
    if scene.snap_hint:
        _draw_snap_hint(scene, layout, theme)


def _draw_bubble(scene: PetScene, layout: PetLayout, theme: Theme) -> None:
    radius = max(10.0, 15.0 * layout.scale)
    _fill_rounded(layout.bubble, radius, theme.bubble_fill, theme.bubble_alpha)
    _stroke_rounded(
        layout.bubble, radius, theme.bubble_border, theme.bubble_border_alpha, 1.0
    )

    accent = state_accent(scene.state)
    _fill_oval(layout.header_dot.inset(-2.0, -2.0), accent, 0.22)
    _fill_oval(layout.header_dot, accent)

    headline_font = textkit.font(max(11.0, 13.0 * layout.scale), "semibold")
    _draw_text(
        textkit.truncate(scene.headline, headline_font, layout.headline.width),
        layout.headline,
        headline_font,
        theme.text_primary,
    )
    if scene.state in ("running", "multi"):
        _draw_activity_dots(scene, layout, accent)

    title_font = textkit.font(max(9.5, 11.0 * layout.scale), "medium")
    time_font = textkit.font(max(9.0, 10.0 * layout.scale), "regular")
    row_radius = max(5.0, 7.0 * layout.scale)
    for index, row in enumerate(scene.rows[: len(layout.rows)]):
        parts = layout.row_parts(index)
        box = layout.rows[index]
        if row.highlight:
            row_alpha = min(0.24, theme.row_active_alpha * 1.9)
        elif row.active:
            row_alpha = theme.row_active_alpha
        else:
            row_alpha = theme.row_alpha
        _fill_rounded(
            Box(box.x - 3.0, box.y, box.width + 6.0, box.height - 2.0),
            row_radius,
            theme.row_fill,
            row_alpha,
        )
        if not row.muted:
            _fill_oval(parts.dot, row.accent)
        if row.highlight:
            title_color = theme.text_primary
        elif row.muted:
            title_color = theme.text_tertiary
        else:
            title_color = theme.text_secondary
        _draw_text(
            textkit.truncate(row.title, title_font, parts.title.width),
            parts.title,
            title_font,
            title_color,
        )
        if row.time_text:
            _draw_text(
                textkit.truncate(row.time_text, time_font, parts.time.width),
                parts.time,
                time_font,
                theme.text_tertiary,
                align="right",
            )


def _draw_activity_dots(scene: PetScene, layout: PetLayout, accent: str) -> None:
    size = max(3.0, 4.0 * layout.scale)
    gap = size + max(2.0, 3.0 * layout.scale)
    base_x = layout.activity.max_x - (3 * gap - (gap - size))
    for index in range(3):
        phase = (scene.frame + index * 2) % 6
        lift = size * 0.5 if phase in (1, 2) else 0.0
        _fill_oval(
            Box(base_x + index * gap, layout.activity.mid_y - size / 2 + lift, size, size),
            accent,
            0.45 + index * 0.2,
        )


def _draw_tail(layout: PetLayout, theme: Theme) -> None:
    for box in layout.tail:
        color(theme.bubble_fill, theme.bubble_alpha).setFill()
        NSBezierPath.fillRect_(NSMakeRect(*box.as_tuple()))


def _draw_shadow(layout: PetLayout, theme: Theme) -> None:
    _fill_oval(layout.shadow, theme.shadow_color, theme.shadow_alpha)


def _fit_bottom(box: Box, aspect: float) -> Box:
    """Largest box with this aspect that fits, sitting on the given floor."""
    if aspect <= 0:
        return box
    height = box.height
    width = height * aspect
    if width > box.width:
        width = box.width
        height = width / aspect
    return Box(box.mid_x - width / 2, box.y, width, height)


def _draw_sprite(scene: PetScene, layout: PetLayout) -> None:
    if scene.skin is not None:
        image = scene.skin.image(scene.state, scene.frame)
        if image is not None:
            # Photo skins are portrait; keep their aspect and stand them on the floor.
            target = _fit_bottom(layout.sprite, scene.skin.aspect)
            image.drawInRect_(NSMakeRect(*target.as_tuple()))
            return
    image = sprite_image(scene.state, scene.frame, scene.active_count, layout.pixel)
    image.drawInRect_(NSMakeRect(*layout.sprite.as_tuple()))


def _draw_badge(scene: PetScene, layout: PetLayout, theme: Theme) -> None:
    label = "9+" if scene.active_count > 9 else str(scene.active_count)
    box = layout.badge_box(scene.active_count > 9)
    _fill_rounded(box, box.height / 2, theme.badge_fill, 1.0)
    _draw_text(
        label,
        box,
        textkit.font(max(10.0, 12.0 * layout.scale), "semibold"),
        theme.badge_text,
        align="center",
    )


def _draw_flash(scene: PetScene, layout: PetLayout) -> None:
    """Local celebration/alert that does not replace the running animation."""
    accent = state_accent(scene.flash)
    size = max(2.0, 3.0 * layout.scale)
    slots = (0.12, 0.3, 0.5, 0.72, 0.88)
    for index, ratio in enumerate(slots):
        rise = ((scene.frame + index * 2) % 5) * size * 1.5
        x = layout.sprite.x + layout.sprite.width * ratio
        y = layout.sprite.max_y - layout.sprite.height * 0.08 + rise
        _fill_oval(Box(x, y, size, size), accent, 0.9 - index * 0.1)


def _draw_snap_hint(scene: PetScene, layout: PetLayout, theme: Theme) -> None:
    """Preview bar telling the user this drag will dock to that edge."""
    thickness = max(3.0, 5.0 * layout.scale)
    if scene.snap_hint == "left":
        box = Box(0.0, layout.height * 0.2, thickness, layout.height * 0.6)
    elif scene.snap_hint == "right":
        box = Box(layout.width - thickness, layout.height * 0.2, thickness, layout.height * 0.6)
    else:
        box = Box(layout.width * 0.2, 0.0, layout.width * 0.6, thickness)
    _fill_rounded(box, thickness / 2, theme.hint_fill, theme.hint_alpha)


def collapsed_layout_for(scene: PetScene, layout: PetLayout) -> CollapsedLayout:
    """The docked geometry a scene will be drawn with (shared with hit-testing)."""
    return collapsed_layout(
        scene.docked_edge,
        layout.scale,
        len(scene.rows),
        scene.tab_thickness,
        with_badge=scene.active_count > 0 or bool(scene.flash),
        with_arrow=scene.hover,
        max_width=scene.canvas[0] if scene.canvas else 10_000.0,
        max_height=scene.canvas[1] if scene.canvas else 10_000.0,
    )


def _pulse_alpha(state: str, frame: int) -> float:
    if state == "error":
        return 0.95 if frame % 2 else 0.3
    if state in ("running", "multi"):
        return 0.5 + 0.4 * abs(math.sin(frame * 0.5))
    if state == "waiting":
        return 0.88 if frame % 4 < 2 else 0.58
    if state == "success":
        return 0.95
    if state == "offline":
        return 0.28
    return 0.6


def _draw_pulse(box: Box, accent: str, state: str, frame: int) -> None:
    radius = min(box.width, box.height) / 2
    _fill_rounded(box, radius, accent, _pulse_alpha(state, frame))
    if state not in ("running", "multi"):
        return
    # A bright segment travels along the rail so a docked pet still reads as busy.
    vertical = box.height >= box.width
    length = box.height if vertical else box.width
    segment = max(6.0, length * 0.26)
    travel = max(0.0, length - segment)
    period = 16
    phase = (frame % period) / (period - 1)
    offset = travel * (2 * phase if phase <= 0.5 else 2 * (1 - phase))
    chunk = (
        Box(box.x, box.y + offset, box.width, segment)
        if vertical
        else Box(box.x + offset, box.y, segment, box.height)
    )
    _fill_rounded(chunk, radius, accent, 0.98)


def _draw_collapsed(scene: PetScene, layout: PetLayout, theme: Theme) -> None:
    rail = collapsed_layout_for(scene, layout)
    accent = state_accent(scene.flash or scene.state)
    radius = max(8.0, 12.0 * layout.scale)

    if rail.has_card:
        _fill_rounded(rail.card, radius, theme.bubble_fill, theme.bubble_alpha)
        _stroke_rounded(rail.card, radius, theme.bubble_border, theme.bubble_border_alpha)
        header_font = textkit.font(max(10.5, 12.0 * layout.scale), "semibold")
        _draw_text(
            textkit.truncate(scene.headline, header_font, rail.header.width),
            rail.header,
            header_font,
            theme.text_primary,
        )
        title_font = textkit.font(max(9.5, 10.5 * layout.scale), "medium")
        time_font = textkit.font(max(9.0, 9.5 * layout.scale), "regular")
        row_radius = max(5.0, 7.0 * layout.scale)
        for index, row in enumerate(scene.rows[: len(rail.rows)]):
            parts = rail.row_parts(index)
            box = rail.rows[index]
            if row.highlight:
                alpha = min(0.24, theme.row_active_alpha * 1.9)
            elif row.active:
                alpha = theme.row_active_alpha
            else:
                alpha = theme.row_alpha
            _fill_rounded(
                Box(box.x - 3.0, box.y, box.width + 6.0, box.height - 2.0),
                row_radius,
                theme.row_fill,
                alpha,
            )
            if not row.muted:
                _fill_oval(parts.dot, row.accent)
            _draw_text(
                textkit.truncate(row.title, title_font, parts.title.width),
                parts.title,
                title_font,
                theme.text_primary
                if row.highlight
                else (theme.text_tertiary if row.muted else theme.text_secondary),
            )
            if row.time_text:
                _draw_text(
                    textkit.truncate(row.time_text, time_font, parts.time.width),
                    parts.time,
                    time_font,
                    theme.text_tertiary,
                    align="right",
                )

    _fill_rounded(rail.tab, radius, theme.tab_fill, theme.tab_alpha)
    _stroke_rounded(rail.tab, radius, theme.bubble_border, theme.bubble_border_alpha)
    _draw_pulse(rail.accent, accent, scene.flash or scene.state, scene.frame)

    if scene.skin is not None:
        mini = scene.skin.image(scene.state, scene.frame)
        if mini is not None:
            mini.drawInRect_(NSMakeRect(*_fit_bottom(rail.sprite, scene.skin.aspect).as_tuple()))
        else:
            sprite_image(scene.state, scene.frame, scene.active_count,
                         max(1.0, float(round(layout.scale)))).drawInRect_(
                NSMakeRect(*rail.sprite.as_tuple())
            )
    else:
        # The mini pet is drawn at one screen pixel per sprite cell, so it stays crisp.
        pixel = max(1.0, float(round(layout.scale)))
        sprite_image(scene.state, scene.frame, scene.active_count, pixel).drawInRect_(
            NSMakeRect(*rail.sprite.as_tuple())
        )

    if scene.tab_caption:
        _draw_text(
            textkit.truncate(
                scene.tab_caption, textkit.font(max(8.5, 9.5 * layout.scale), "medium"), rail.caption.width
            ),
            rail.caption,
            textkit.font(max(8.5, 9.5 * layout.scale), "medium"),
            theme.text_secondary,
            align="center",
        )
    if scene.active_count > 0:
        _fill_rounded(rail.badge, rail.badge.height / 2, theme.badge_fill)
        _draw_text(
            "9+" if scene.active_count > 9 else str(scene.active_count),
            rail.badge,
            textkit.font(max(8.5, 10.0 * layout.scale), "semibold"),
            theme.badge_text,
            align="center",
        )
    elif scene.flash:
        _fill_oval(rail.badge.inset(rail.badge.width * 0.3, rail.badge.height * 0.3), accent)
    if scene.hover:
        _draw_text(
            rail.arrow_text,
            rail.arrow,
            textkit.font(max(11.0, 13.0 * layout.scale), "semibold"),
            theme.text_tertiary,
            align="center",
        )
