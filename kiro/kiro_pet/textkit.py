"""Font helpers, text measurement and CJK-safe truncation for Cocoa drawing."""
from __future__ import annotations

from functools import lru_cache

from AppKit import (
    NSFont,
    NSFontAttributeName,
    NSFontWeightMedium,
    NSFontWeightRegular,
    NSFontWeightSemibold,
    NSString,
)

_WEIGHTS = {
    "regular": NSFontWeightRegular,
    "medium": NSFontWeightMedium,
    "semibold": NSFontWeightSemibold,
}
ELLIPSIS = "…"


@lru_cache(maxsize=64)
def font(size: float, weight: str = "regular"):
    return NSFont.systemFontOfSize_weight_(
        float(size), _WEIGHTS.get(weight, NSFontWeightRegular)
    )


def text_width(text: str, text_font) -> float:
    """Measured width, so CJK titles are never silently clipped."""
    value = str(text or "")
    if not value:
        return 0.0
    size = NSString.stringWithString_(value).sizeWithAttributes_(
        {NSFontAttributeName: text_font}
    )
    return float(size.width)


def fits(text: str, text_font, max_width: float) -> bool:
    return text_width(text, text_font) <= float(max_width)


def truncate(text: str, text_font, max_width: float) -> str:
    """Collapse whitespace and cut on a character boundary with an ellipsis."""
    value = " ".join(str(text or "").split())
    if not value or max_width <= 0:
        return ""
    if text_width(value, text_font) <= max_width:
        return value
    low, high, best = 0, len(value), ""
    while low <= high:
        mid = (low + high) // 2
        candidate = value[:mid].rstrip() + ELLIPSIS
        if text_width(candidate, text_font) <= max_width:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best or ELLIPSIS
