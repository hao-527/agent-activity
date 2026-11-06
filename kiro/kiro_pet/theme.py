"""Color themes and state accents for the Kiro desktop pet."""
from __future__ import annotations

from dataclasses import dataclass

# Match the semantic system colours used by the other menu-bar Activities:
# purple = idle, green = active/completed, yellow = waiting/cancelled,
# orange = problem. Offline remains neutral gray.
STATE_ACCENTS = {
    "offline": "#8E8E93",
    "idle": "#AF52DE",
    "running": "#34C759",
    "multi": "#34C759",
    "waiting": "#FFD60A",
    "success": "#34C759",
    "error": "#FF9500",
    "cancelled": "#FFD60A",
}
PHASE_ACCENTS = {
    "idle": "#AF52DE",
    "running": "#34C759",
    "waiting": "#FFD60A",
    "success": "#34C759",
    "error": "#FF9500",
    "cancelled": "#FFD60A",
}
PHASE_ICONS = {
    "idle": "○",
    "running": "●",
    "waiting": "?",
    "success": "✓",
    "error": "!",
    "cancelled": "—",
}


def state_accent(state: str) -> str:
    return STATE_ACCENTS.get(state, STATE_ACCENTS["idle"])


def phase_accent(phase: str) -> str:
    return PHASE_ACCENTS.get(phase, PHASE_ACCENTS["idle"])


def phase_icon(phase: str) -> str:
    return PHASE_ICONS.get(phase, "○")


@dataclass(frozen=True)
class Theme:
    name: str
    bubble_fill: str
    bubble_alpha: float
    bubble_border: str
    bubble_border_alpha: float
    row_fill: str
    row_alpha: float
    row_active_alpha: float
    text_primary: str
    text_secondary: str
    text_tertiary: str
    shadow_color: str
    shadow_alpha: float
    tab_fill: str
    tab_alpha: float
    badge_fill: str
    badge_text: str
    hint_fill: str
    hint_alpha: float


DARK = Theme(
    name="dark",
    bubble_fill="#0D0A18",
    bubble_alpha=0.93,
    bubble_border="#FFFFFF",
    bubble_border_alpha=0.14,
    row_fill="#FFFFFF",
    row_alpha=0.06,
    row_active_alpha=0.13,
    text_primary="#FFFFFF",
    text_secondary="#D6D1EA",
    text_tertiary="#9C95BA",
    shadow_color="#000000",
    shadow_alpha=0.28,
    tab_fill="#171323",
    tab_alpha=0.96,
    badge_fill="#EF4444",
    badge_text="#FFFFFF",
    hint_fill="#A78BFA",
    hint_alpha=0.55,
)
LIGHT = Theme(
    name="light",
    bubble_fill="#FFFFFF",
    bubble_alpha=0.95,
    bubble_border="#1B1630",
    bubble_border_alpha=0.16,
    row_fill="#1B1630",
    row_alpha=0.05,
    row_active_alpha=0.11,
    text_primary="#161227",
    text_secondary="#3E3757",
    text_tertiary="#6E6790",
    shadow_color="#000000",
    shadow_alpha=0.20,
    tab_fill="#FFFFFF",
    tab_alpha=0.95,
    badge_fill="#DC2626",
    badge_text="#FFFFFF",
    hint_fill="#7C3AED",
    hint_alpha=0.50,
)


def theme_for(dark_mode: bool) -> Theme:
    return DARK if dark_mode else LIGHT
