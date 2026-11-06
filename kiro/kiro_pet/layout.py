"""Resolution-independent layout math for the Kiro desktop pet.

Every drawing rectangle and every window/edge geometry decision is derived
here from one scale preset, so the window can be resized or re-themed
without hand-tuning coordinates inside the drawing code.
"""
from __future__ import annotations
from functools import lru_cache

from dataclasses import dataclass

SPRITE_COLUMNS = 22
SPRITE_ROWS = 21
SCALE_PRESETS: dict[str, float] = {"small": 0.85, "medium": 1.0, "large": 1.2}
SCALE_ORDER = ("small", "medium", "large")
SCALE_LABELS = {"small": "小", "medium": "中", "large": "大"}
DEFAULT_SCALE = "medium"
COMPACT_ROWS = 3
MAX_BUBBLE_ROWS = 8
VALID_EDGES = ("left", "right", "bottom")


def normalize_scale(name: str) -> str:
    return name if name in SCALE_PRESETS else DEFAULT_SCALE


def next_scale(name: str) -> str:
    return SCALE_ORDER[(SCALE_ORDER.index(normalize_scale(name)) + 1) % len(SCALE_ORDER)]


def clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), float(low)), max(float(low), float(high)))


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def max_x(self) -> float:
        return self.x + self.width

    @property
    def max_y(self) -> float:
        return self.y + self.height

    @property
    def mid_x(self) -> float:
        return self.x + self.width / 2

    @property
    def mid_y(self) -> float:
        return self.y + self.height / 2

    def inset(self, dx: float, dy: float) -> "Box":
        return Box(
            self.x + dx,
            self.y + dy,
            max(0.0, self.width - 2 * dx),
            max(0.0, self.height - 2 * dy),
        )

    def offset(self, dx: float, dy: float) -> "Box":
        return Box(self.x + dx, self.y + dy, self.width, self.height)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class RowParts:
    dot: Box
    title: Box
    time: Box


@dataclass(frozen=True)
class PetLayout:
    scale_name: str
    scale: float
    pixel: float
    width: float
    height: float
    show_bubble: bool
    row_count: int
    bubble: Box
    content: Box
    header_dot: Box
    headline: Box
    activity: Box
    rows: tuple[Box, ...]
    tail: tuple[Box, ...]
    sprite: Box
    shadow: Box
    badge: Box
    dot_size: float
    time_width: float

    def row_parts(self, index: int) -> RowParts:
        row = self.rows[index]
        dot = Box(
            self.content.x,
            row.y + (row.height - self.dot_size) / 2,
            self.dot_size,
            self.dot_size,
        )
        gap = self.dot_size
        time_box = Box(self.content.max_x - self.time_width, row.y, self.time_width, row.height)
        title_width = max(0.0, time_box.x - dot.max_x - 2 * gap)
        return RowParts(dot, Box(dot.max_x + gap, row.y, title_width, row.height), time_box)

    def badge_box(self, wide: bool = False) -> Box:
        if not wide:
            return self.badge
        extra = self.badge.width * 0.3
        return Box(self.badge.x - extra, self.badge.y, self.badge.width + extra, self.badge.height)


@lru_cache(maxsize=32)
def compute_layout(
    scale_name: str = DEFAULT_SCALE,
    row_count: int = 1,
    show_bubble: bool = True,
) -> PetLayout:
    """Build every rectangle for one scale preset and bubble row count."""
    scale_name = normalize_scale(scale_name)
    scale = SCALE_PRESETS[scale_name]

    def u(value: float) -> float:
        return float(round(value * scale))

    # Integer pixel size keeps the pixel-art sprite crisp on Retina displays.
    pixel = float(max(4, int(round(6 * scale))))
    rows = int(clamp(row_count, 0, MAX_BUBBLE_ROWS))
    rows = max(1, rows) if show_bubble else 0

    margin = u(7)
    pad = u(11)
    header_h = u(21)
    row_h = u(18)
    gap = u(4)
    floor = u(13)
    sprite_w = SPRITE_COLUMNS * pixel
    sprite_h = SPRITE_ROWS * pixel
    width = max(u(276), sprite_w + 2 * margin)
    bubble_h = (pad * 2 + header_h + gap + rows * row_h) if show_bubble else 0.0
    tail_h = u(11) if show_bubble else 0.0
    height = floor + sprite_h + tail_h + bubble_h + margin

    sprite = Box((width - sprite_w) / 2, floor, sprite_w, sprite_h)
    shadow_w = sprite_w * 0.84
    shadow = Box((width - shadow_w) / 2, u(4), shadow_w, u(15))
    bubble = Box(margin, height - margin - bubble_h, width - 2 * margin, bubble_h)
    content = bubble.inset(pad, pad)

    dot = u(9)
    activity_w = u(28)
    header_dot = Box(content.x, content.max_y - header_h + (header_h - dot) / 2, dot, dot)
    activity = Box(content.max_x - activity_w, content.max_y - header_h, activity_w, header_h)
    headline_x = header_dot.max_x + u(7)
    headline = Box(
        headline_x,
        content.max_y - header_h,
        max(0.0, activity.x - headline_x - u(4)),
        header_h,
    )
    row_boxes = tuple(
        Box(content.x, content.max_y - header_h - gap - (index + 1) * row_h, content.width, row_h)
        for index in range(rows)
    )
    tail = (
        (
            Box(width / 2 - u(8), bubble.y - u(6), u(16), u(6)),
            Box(width / 2 - u(4), bubble.y - u(11), u(8), u(5)),
        )
        if show_bubble
        else ()
    )
    badge = Box(sprite.max_x - u(9), sprite.max_y - u(25), u(27), u(23))

    return PetLayout(
        scale_name=scale_name,
        scale=scale,
        pixel=pixel,
        width=width,
        height=height,
        show_bubble=show_bubble,
        row_count=rows,
        bubble=bubble,
        content=content,
        header_dot=header_dot,
        headline=headline,
        activity=activity,
        rows=row_boxes,
        tail=tail,
        sprite=sprite,
        shadow=shadow,
        badge=badge,
        dot_size=u(7),
        time_width=u(60),
    )


def nearest_edge(
    origin_x: float,
    origin_y: float,
    width: float,
    height: float,
    visible_x: float,
    visible_y: float,
    visible_width: float,
    visible_height: float,
    threshold: float | None = None,
) -> str:
    """Return the nearest supported screen edge, optionally within a threshold."""
    distances = {
        "left": abs(origin_x - visible_x),
        "right": abs((origin_x + width) - (visible_x + visible_width)),
        "bottom": abs(origin_y - visible_y),
    }
    edge = min(distances, key=distances.get)
    if threshold is not None and distances[edge] > threshold:
        return ""
    return edge


def docked_origin(
    edge: str,
    origin_x: float,
    origin_y: float,
    width: float,
    height: float,
    visible_x: float,
    visible_y: float,
    visible_width: float,
    visible_height: float,
    visible_sliver: float,
) -> tuple[float, float]:
    """Place a window outside one edge while keeping an exact visible sliver."""
    clamped_x = clamp(origin_x, visible_x, visible_x + visible_width - width)
    clamped_y = clamp(origin_y, visible_y, visible_y + visible_height - height)
    if edge == "left":
        return float(visible_x - width + visible_sliver), clamped_y
    if edge == "right":
        return float(visible_x + visible_width - visible_sliver), clamped_y
    if edge == "bottom":
        return clamped_x, float(visible_y - height + visible_sliver)
    return clamped_x, clamped_y


def expanded_origin(
    edge: str,
    width: float,
    height: float,
    visible_x: float,
    visible_y: float,
    visible_width: float,
    visible_height: float,
    saved_x: float,
    saved_y: float,
    margin: float = 8,
) -> tuple[float, float]:
    """Restore a docked window just inside its edge, preserving the other axis."""
    min_x = visible_x + margin
    max_x = visible_x + visible_width - width - margin
    min_y = visible_y + margin
    max_y = visible_y + visible_height - height - margin
    x = clamp(saved_x, min_x, max_x)
    y = clamp(saved_y, min_y, max_y)
    if edge == "left":
        x = clamp(min_x, min_x, max_x)
    elif edge == "right":
        x = clamp(max_x, min_x, max_x)
    elif edge == "bottom":
        y = clamp(min_y, min_y, max_y)
    return x, y


def format_duration_short(seconds: float) -> str:
    """At most three characters, for the 36px side rail."""
    value = int(max(0.0, float(seconds)))
    if value < 3:
        return "刚开始"
    if value < 60:
        return f"{value}秒"
    if value < 3600:
        return f"{value // 60}分"
    return f"{value // 3600}时"


def format_duration(seconds: float) -> str:
    """Compact Chinese duration that fits the narrow time column."""
    value = int(max(0.0, float(seconds)))
    if value < 3:
        return "刚开始"
    if value < 60:
        return f"{value}秒"
    if value < 3600:
        minutes, rest = divmod(value, 60)
        if minutes < 10 and rest:
            return f"{minutes}分{rest}秒"
        return f"{minutes}分"
    hours, rest = divmod(value, 3600)
    return f"{hours}时{rest // 60:02d}分"


# --- collapsed (docked) presentation ----------------------------------------
COLLAPSED_CARD_WIDTH = 214.0
COLLAPSED_CARD_WIDTH_BOTTOM = 252.0
SPRITE_MINI_PIXEL = 1.0


@dataclass(frozen=True)
class CollapsedLayout:
    """Content-sized docked rail.

    The docked window is shrunk to exactly this size and placed flush against
    the screen edge, instead of keeping the full pet window and pushing it off
    screen. A full-size window would leave a large transparent area that still
    swallows mouse clicks, which is what the pet used to do.
    """

    edge: str
    scale: float
    width: float
    height: float
    tab: Box
    accent: Box
    sprite: Box
    badge: Box
    caption: Box
    arrow: Box
    arrow_text: str
    card: Box | None
    header: Box | None
    content: Box | None
    rows: tuple[Box, ...]
    dot_size: float
    time_width: float

    @property
    def size(self) -> tuple[float, float]:
        return (self.width, self.height)

    @property
    def has_card(self) -> bool:
        return self.card is not None and bool(self.rows)

    def row_parts(self, index: int) -> RowParts:
        row = self.rows[index]
        content = self.content
        dot = Box(
            content.x,
            row.y + (row.height - self.dot_size) / 2,
            self.dot_size,
            self.dot_size,
        )
        gap = self.dot_size
        time_box = Box(content.max_x - self.time_width, row.y, self.time_width, row.height)
        title_width = max(0.0, time_box.x - dot.max_x - 2 * gap)
        return RowParts(dot, Box(dot.max_x + gap, row.y, title_width, row.height), time_box)


@lru_cache(maxsize=32)
def collapsed_layout(
    edge: str,
    scale: float = 1.0,
    row_count: int = 0,
    tab_thickness: float = 36.0,
    with_badge: bool = False,
    with_arrow: bool = False,
    max_width: float = 10_000.0,
    max_height: float = 10_000.0,
) -> CollapsedLayout:
    """Lay out the docked rail, sized to its own content.

    The handle always hugs the screen edge; the optional preview card grows
    inwards from it.
    """
    edge = edge if edge in VALID_EDGES else "left"

    def u(value: float) -> float:
        return float(round(value * scale))

    thickness = max(u(20), float(tab_thickness))
    gap = u(6)
    pad = u(10)
    header_h = u(19)
    row_h = u(17)
    dot_size = u(7)
    time_width = u(60)
    corner = u(12)
    rows = int(clamp(row_count, 0, MAX_BUBBLE_ROWS))
    card_needed = (pad * 2 + header_h + gap + rows * row_h) if rows else 0.0
    pixel = max(1.0, float(round(scale)))
    sprite_w = float(SPRITE_COLUMNS) * pixel
    sprite_h = float(SPRITE_ROWS) * pixel
    vertical = edge in ("left", "right")

    if vertical:
        caption_h = u(15)
        badge_h = u(18)
        arrow_h = u(16)
        # The arrow slot is always reserved: a handle that changes length when
        # the pointer arrives would move out from under the cursor and make
        # hover flicker between opened and closed.
        handle_len = u(9) + sprite_h + u(3) + caption_h + u(9) + arrow_h + u(3)
        if with_badge:
            handle_len += badge_h + u(3)
        handle_len = min(max_height - u(4), max(u(58), handle_len))
        card_w = min(u(COLLAPSED_CARD_WIDTH), max(u(120), max_width - thickness - gap - u(4)))
        show_card = rows > 0 and card_w >= u(120)
        card_h = min(card_needed, max_height - u(4)) if show_card else 0.0
        width = thickness + ((gap + card_w) if show_card else 0.0)
        height = max(handle_len, card_h)
        # Anchored to the bottom edge of the window, which is the corner that
        # stays put while the card opens upwards.
        tab_y = 0.0
        if edge == "left":
            tab = Box(0.0, tab_y, thickness, handle_len)
            accent = Box(u(3), tab_y + corner, u(3), max(u(6), handle_len - 2 * corner))
            card_x = thickness + gap
            arrow_text = "›"
        else:
            tab = Box(width - thickness, tab_y, thickness, handle_len)
            accent = Box(width - u(6), tab_y + corner, u(3), max(u(6), handle_len - 2 * corner))
            card_x = 0.0
            arrow_text = "‹"
        cursor = tab.max_y - u(9)
        sprite = Box(tab.mid_x - sprite_w / 2, cursor - sprite_h, sprite_w, sprite_h)
        cursor = sprite.y - u(3)
        caption = Box(tab.x, cursor - caption_h, tab.width, caption_h)
        cursor = caption.y - u(3)
        badge = Box(
            tab.mid_x - badge_h / 2, max(tab.y + u(3), cursor - badge_h), badge_h, badge_h
        )
        if with_badge:
            cursor = badge.y - u(3)
        arrow = Box(tab.x, max(tab.y + u(3), cursor - arrow_h - u(3)), tab.width, arrow_h)
        card = header = content = None
        row_boxes: tuple[Box, ...] = ()
        if show_card and card_h > 0:
            card = Box(card_x, max(0.0, height - card_h), card_w, card_h)
    else:
        badge_w = u(18)
        arrow_w = u(15)
        handle_len = u(11) + sprite_w + u(7) + u(50) + u(11) + arrow_w + u(4)
        if with_badge:
            handle_len += badge_w + u(5)
        card_w = min(u(COLLAPSED_CARD_WIDTH_BOTTOM), max(u(150), max_width - u(4)))
        show_card = rows > 0 and card_needed > 0
        card_h = min(card_needed, max_height - thickness - gap - u(4)) if show_card else 0.0
        show_card = show_card and card_h >= u(50)
        handle_len = min(max_width - u(4), max(u(104), handle_len))
        width = max(handle_len, card_w if show_card else 0.0)
        height = thickness + ((gap + card_h) if show_card else 0.0)
        # Anchored to the left edge for the same reason as the side rails.
        tab = Box(0.0, 0.0, handle_len, thickness)
        accent = Box(tab.x + corner, u(4), max(u(10), tab.width - 2 * corner), u(3))
        sprite = Box(tab.x + u(11), tab.mid_y - sprite_h / 2 + u(1), sprite_w, sprite_h)
        arrow = Box(tab.max_x - u(11) - arrow_w, tab.mid_y - u(8), arrow_w, u(16))
        right = arrow.x - u(4)
        badge = Box(right - badge_w, tab.mid_y - badge_w / 2, badge_w, badge_w)
        if with_badge:
            right = badge.x - u(5)
        caption_x = sprite.max_x + u(7)
        caption = Box(caption_x, tab.mid_y - u(9), max(u(20), right - caption_x), u(16))
        arrow_text = "⌃"
        card = header = content = None
        row_boxes = ()
        if show_card:
            card = Box(0.0, thickness + gap, card_w, card_h)

    if card is not None:
        content = card.inset(pad, pad)
        header = Box(content.x, content.max_y - header_h, content.width, header_h)
        row_boxes = tuple(
            Box(
                content.x,
                content.max_y - header_h - gap - (index + 1) * row_h,
                content.width,
                row_h,
            )
            for index in range(rows)
            if content.max_y - header_h - gap - (index + 1) * row_h >= content.y - 0.5
        )
        if not row_boxes:
            card = header = content = None

    return CollapsedLayout(
        edge=edge,
        scale=scale,
        width=width,
        height=height,
        tab=tab,
        accent=accent,
        sprite=sprite,
        badge=badge,
        caption=caption,
        arrow=arrow,
        arrow_text=arrow_text,
        card=card,
        header=header,
        content=content,
        rows=row_boxes,
        dot_size=dot_size,
        time_width=time_width,
    )


def docked_flush_origin(
    edge: str,
    width: float,
    height: float,
    visible_x: float,
    visible_y: float,
    visible_width: float,
    visible_height: float,
    offset: float,
) -> tuple[float, float]:
    """Place a content-sized rail flush against one screen edge."""
    if edge == "left":
        y = clamp(offset, visible_y, visible_y + visible_height - height)
        return float(visible_x), y
    if edge == "right":
        y = clamp(offset, visible_y, visible_y + visible_height - height)
        return float(visible_x + visible_width - width), y
    x = clamp(offset, visible_x, visible_x + visible_width - width)
    return x, float(visible_y)
