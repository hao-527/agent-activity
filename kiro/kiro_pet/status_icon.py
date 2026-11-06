"""Kiro's official spirit mark adapted for the macOS menu bar."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from AppKit import (
    NSAppearance,
    NSAppearanceNameAqua,
    NSAppearanceNameDarkAqua,
    NSApplication,
    NSAttributedString,
    NSBezierPath,
    NSColor,
    NSCompositeSourceAtop,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSRectFillUsingOperation,
)
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize

from . import render

SPIRIT_ASSET = Path(__file__).resolve().parent / "assets" / "kiro-spirit.svg"

# The official 17×16 SVG carries ~2pt of empty space on each side. Crop it away
# instead of letting the transparent margin inflate the status item.
ICON_HEIGHT = 22.0
BASE_WIDTH = 22.0
SPIRIT_RECT = NSMakeRect(-1.562, 3.0, 17.0, 16.0)
HALO_RECT = NSMakeRect(13.938, 1.0, 8.0, 8.0)
CORE_RECT = NSMakeRect(14.938, 2.0, 6.0, 6.0)

# Draw the task count into the image so no fixed button gap sits between the
# badge and the number. The native title would leave ~6pt of dead space.
STATUS_FONT = NSFont.systemFontOfSize_(13.0)
TEXT_GAP = 1.5
TEXT_PAD = 0.75


@lru_cache(maxsize=1)
def _spirit_image() -> NSImage | None:
    return NSImage.alloc().initWithContentsOfFile_(str(SPIRIT_ASSET))


def dark_appearance(appearance=None) -> bool:
    """Resolve light/dark mode from the status button's own appearance context."""
    if appearance is None:
        appearance = NSApplication.sharedApplication().effectiveAppearance()
    match = appearance.bestMatchFromAppearancesWithNames_([NSAppearanceNameAqua, NSAppearanceNameDarkAqua])
    return match == NSAppearanceNameDarkAqua


def count_text(count: int) -> str:
    return str(count) if count > 0 else ""


def count_width(text: str) -> float:
    if not text:
        return 0.0
    attrs = {
        NSFontAttributeName: STATUS_FONT,
        NSForegroundColorAttributeName: NSColor.labelColor(),
    }
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs).size().width


@lru_cache(maxsize=64)
def _render_status_icon(accent: str, dark: bool, count: int) -> NSImage:
    text = count_text(count)
    text_width = count_width(text)
    width = BASE_WIDTH + (TEXT_GAP + text_width + TEXT_PAD if text else 0.0)
    image = NSImage.alloc().initWithSize_(NSMakeSize(width, ICON_HEIGHT))

    def draw() -> None:
        image.lockFocus()
        spirit = _spirit_image()
        if spirit is not None:
            # Keep Kiro's official 17×16 mark at native menu-bar scale. The canvas
            # is cropped to the ink so the mark carries no transparent side margin.
            spirit.drawInRect_(SPIRIT_RECT)
            (NSColor.whiteColor() if dark else NSColor.colorWithCalibratedWhite_alpha_(0.12, 1.0)).setFill()
            NSRectFillUsingOperation(SPIRIT_RECT, NSCompositeSourceAtop)
        else:
            # Keep the status item usable if its packaged asset is ever missing.
            (NSColor.whiteColor() if dark else NSColor.labelColor()).setStroke()
            fallback = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(-0.562, 3.5, 15.0, 15.0))
            fallback.setLineWidth_(1.4)
            fallback.stroke()

        # Match the other Activities exactly: 8pt background disc, 6pt colour
        # core. Resolving the disc under the target appearance keeps it dark on
        # a dark menu bar and light on a light one.
        NSColor.windowBackgroundColor().setFill()
        NSBezierPath.bezierPathWithOvalInRect_(HALO_RECT).fill()
        render.color(accent).setFill()
        NSBezierPath.bezierPathWithOvalInRect_(CORE_RECT).fill()

        if text:
            baseline = (ICON_HEIGHT - STATUS_FONT.capHeight()) / 2.0
            y = baseline + STATUS_FONT.descender()
            attrs = {
                NSFontAttributeName: STATUS_FONT,
                NSForegroundColorAttributeName: NSColor.labelColor(),
            }
            NSAttributedString.alloc().initWithString_attributes_(text, attrs).drawAtPoint_(
                NSMakePoint(BASE_WIDTH + TEXT_GAP, y)
            )
        image.unlockFocus()

    appearance = NSAppearance.appearanceNamed_(
        NSAppearanceNameDarkAqua if dark else NSAppearanceNameAqua
    )
    appearance.performAsCurrentDrawingAppearance_(draw)
    return image


def status_icon(accent: str, appearance=None, count: int = 0) -> NSImage:
    """Return Kiro's mark, state badge and task count as one compact image."""
    return _render_status_icon(accent, dark_appearance(appearance), int(count))
