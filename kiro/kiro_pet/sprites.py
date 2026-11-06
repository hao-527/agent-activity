"""Pixel-art frames for the Kiro desktop dog."""
from __future__ import annotations

from dataclasses import dataclass


# Legacy fur/cream keys remain for callers that reuse the public palette.
PALETTE: dict[str, str] = {
    "fur": "#C87832",
    "fur_light": "#E9A24C",
    "fur_dark": "#6F3B24",
    "cream": "#F5DBA3",
    "ink": "#161316",
    "white": "#FFF8E7",
    "dog_tan": "#C87832",
    "dog_tan_light": "#E9A24C",
    "dog_brown": "#6F3B24",
    "dog_saddle": "#252A30",
    "dog_saddle_light": "#3B4148",
    "dog_cream": "#F5DBA3",
    "dog_white": "#FFF8E7",
    "dog_ear": "#B86D63",
    "dog_nose": "#161316",
    "cyan": "#22D3EE",
    "cyan_dark": "#0E7490",
    "green": "#34D399",
    "gold": "#FBBF24",
    "red": "#FB7185",
    "red_dark": "#BE123C",
    "gray": "#94A3B8",
    "gray_light": "#CBD5E1",
    "gray_dark": "#475569",
}


@dataclass(frozen=True)
class PixelSprite:
    width: int
    height: int
    pixels: tuple[tuple[int, int, str], ...]


FRAME_COUNTS = {
    "offline": 8,
    "idle": 12,
    "running": 8,
    "multi": 8,
    "waiting": 8,
    "success": 12,
    "error": 6,
    "cancelled": 8,
}


def frame_count(state: str) -> int:
    return FRAME_COUNTS.get(state, FRAME_COUNTS["idle"])


def sprite_frame(state: str, frame: int, active_count: int = 0) -> PixelSprite:
    state = state if state in FRAME_COUNTS else "idle"
    index = frame % FRAME_COUNTS[state]
    cells: dict[tuple[int, int], str] = {}

    if state == "offline":
        _draw_sleeping_dog(cells, index)
        _draw_sleep(cells, index)
    elif state == "idle":
        breath = (0, 0, 1, 1, 0, 0, 0, 0, 0, 1, 1, 0)[index]
        blink = index in (5, 6)
        ear_pose = "left_twitch" if index == 8 else "right_twitch" if index == 9 else "perk"
        _draw_front_dog(cells, dy=breath, blink=blink, tail_phase=index % 4, ear_pose=ear_pose)
        if index in (0, 1, 11):
            _put(cells, 19, 18, "cyan")
    elif state in ("running", "multi", "waiting"):
        breath = 1 if index in (1, 2, 5, 6) else 0
        _draw_front_dog(cells, dy=breath, mood="focus", tail_phase=index % 4)
        _draw_laptop(cells, index)
        _draw_typing_paws(cells, breath, index)
        if state == "multi":
            _draw_orbits(cells, index, active_count)
        elif state == "waiting":
            _draw_approval(cells, index)
    elif state == "success":
        _draw_success_pose(cells, index)
        _draw_confetti(cells, index)
    elif state == "error":
        dx = (-1, 1, -1, 1, 0, 0)[index]
        _draw_front_dog(cells, dx=dx, mood="error", tail_phase=index % 4)
        _draw_error_spikes(cells, dx, index)
        _draw_warning(cells, index)
    else:  # cancelled
        _draw_low_sad_dog(cells, index)

    ordered = tuple(
        (x, y, color)
        for (x, y), color in sorted(cells.items(), key=lambda item: (item[0][1], item[0][0]))
    )
    return PixelSprite(22, 21, ordered)


def _put(cells: dict, x: int, y: int, color: str) -> None:
    """Clip every pixel to the fixed public 22x21 canvas."""
    if 0 <= x < 22 and 0 <= y < 21:
        cells[(x, y)] = color


def _rect(cells: dict, x: int, y: int, width: int, height: int, color: str) -> None:
    for px in range(x, x + width):
        for py in range(y, y + height):
            _put(cells, px, py, color)


def _draw_front_tail(cells: dict, dx: int, dy: int, phase: int) -> None:
    points = [
        [(15, 5), (17, 5), (18, 6), (19, 7), (19, 8)],
        [(15, 5), (17, 5), (18, 6), (20, 7), (20, 9)],
        [(15, 5), (17, 6), (18, 7), (19, 8), (18, 9)],
        [(15, 5), (16, 6), (17, 7), (18, 7), (19, 6)],
    ][phase % 4]
    for position, (x, y) in enumerate(points):
        color = "dog_brown" if position < 2 else "dog_tan"
        _put(cells, x + dx, y + dy, color)
        if position in (1, 2):
            _put(cells, x + dx, y + dy + 1, color)


def _draw_ears(cells: dict, dx: int, dy: int, pose: str = "perk") -> None:
    left_tip = 4 if pose == "left_twitch" else 5
    right_tip = 17 if pose == "right_twitch" else 16
    left = [
        (left_tip, 20), (4, 19), (5, 19), (3, 18), (4, 18), (5, 18), (6, 18),
        (3, 17), (4, 17), (5, 17), (6, 17), (7, 17), (4, 16), (5, 16), (6, 16), (7, 16),
    ]
    right = [
        (right_tip, 20), (15, 19), (16, 19), (15, 18), (16, 18), (17, 18), (18, 18),
        (14, 17), (15, 17), (16, 17), (17, 17), (18, 17), (14, 16), (15, 16), (16, 16), (17, 16),
    ]
    for x, y in left + right:
        _put(cells, x + dx, y + dy, "dog_brown")
    for x, y in [(5, 19), (4, 18), (5, 18), (5, 17), (16, 19), (16, 18), (17, 18), (16, 17)]:
        _put(cells, x + dx, y + dy, "dog_ear")


def _draw_front_head(
    cells: dict,
    dx: int = 0,
    dy: int = 0,
    blink: bool = False,
    mood: str = "normal",
    ear_pose: str = "perk",
) -> None:
    _draw_ears(cells, dx, dy, ear_pose)

    # Round gold-orange head and highlighted cheeks.
    _rect(cells, 7 + dx, 16 + dy, 8, 2, "dog_tan")
    _rect(cells, 6 + dx, 12 + dy, 10, 5, "dog_tan")
    _rect(cells, 5 + dx, 11 + dy, 12, 4, "dog_tan")
    _put(cells, 6 + dx, 15 + dy, "dog_tan_light")
    _put(cells, 15 + dx, 15 + dy, "dog_tan_light")
    _rect(cells, 7 + dx, 14 + dy, 2, 2, "dog_tan_light")

    # Brown forehead blaze between the ears.
    _rect(cells, 10 + dx, 15 + dy, 2, 3, "dog_brown")
    _put(cells, 11 + dx, 14 + dy, "dog_brown")

    # Cream muzzle and large black nose.
    _rect(cells, 8 + dx, 11 + dy, 6, 3, "dog_cream")
    _put(cells, 7 + dx, 12 + dy, "dog_cream")
    _put(cells, 14 + dx, 12 + dy, "dog_cream")

    if mood == "error":
        for eye_x in (7, 13):
            _put(cells, eye_x + dx, 14 + dy, "red_dark")
            _put(cells, eye_x + 1 + dx, 15 + dy, "red_dark")
            _put(cells, eye_x + dx, 15 + dy, "red_dark")
            _put(cells, eye_x + 1 + dx, 14 + dy, "red_dark")
    elif blink:
        _rect(cells, 7 + dx, 14 + dy, 2, 1, "dog_nose")
        _rect(cells, 13 + dx, 14 + dy, 2, 1, "dog_nose")
    else:
        for eye_x in (7, 13):
            _rect(cells, eye_x + dx, 14 + dy, 2, 2, "dog_nose")
            _put(cells, eye_x + dx, 15 + dy, "dog_white")
        if mood == "focus":
            _rect(cells, 7 + dx, 16 + dy, 2, 1, "dog_brown")
            _rect(cells, 13 + dx, 16 + dy, 2, 1, "dog_brown")

    _rect(cells, 10 + dx, 12 + dy, 3, 1, "dog_nose")
    _put(cells, 11 + dx, 11 + dy, "dog_nose")
    if mood == "happy":
        _put(cells, 10 + dx, 10 + dy, "dog_nose")
        _put(cells, 12 + dx, 10 + dy, "dog_nose")
        _put(cells, 11 + dx, 9 + dy, "red")
    elif mood in ("sad", "error"):
        _rect(cells, 10 + dx, 10 + dy, 3, 1, "dog_nose")
        _put(cells, 10 + dx, 9 + dy, "dog_nose")
        _put(cells, 12 + dx, 9 + dy, "dog_nose")
    else:
        _rect(cells, 10 + dx, 10 + dy, 3, 1, "dog_nose")


def _draw_front_dog(
    cells: dict,
    dx: int = 0,
    dy: int = 0,
    blink: bool = False,
    mood: str = "normal",
    tail_phase: int = 0,
    ear_pose: str = "perk",
) -> None:
    _draw_front_tail(cells, dx, dy, tail_phase)

    # Dark saddle, broad white chest, and short white forelegs/paws.
    _rect(cells, 6 + dx, 4 + dy, 10, 6, "dog_saddle")
    _rect(cells, 5 + dx, 5 + dy, 2, 4, "dog_saddle_light")
    _rect(cells, 15 + dx, 5 + dy, 2, 4, "dog_saddle_light")
    _rect(cells, 9 + dx, 4 + dy, 4, 6, "dog_white")
    _put(cells, 8 + dx, 8 + dy, "dog_white")
    _put(cells, 13 + dx, 8 + dy, "dog_white")

    _rect(cells, 5 + dx, 1 + dy, 3, 3, "dog_tan")
    _rect(cells, 14 + dx, 1 + dy, 3, 3, "dog_tan")
    _rect(cells, 7 + dx, 1 + dy, 3, 5, "dog_white")
    _rect(cells, 12 + dx, 1 + dy, 3, 5, "dog_white")
    _put(cells, 8 + dx, 1 + dy, "dog_cream")
    _put(cells, 13 + dx, 1 + dy, "dog_cream")

    _draw_front_head(cells, dx, dy, blink, mood, ear_pose)


def _draw_crouching_dog(cells: dict, phase: int = 0) -> None:
    _draw_front_tail(cells, 0, -2, phase)
    _rect(cells, 5, 2, 12, 5, "dog_saddle")
    _rect(cells, 8, 2, 6, 5, "dog_white")
    _rect(cells, 3, 1, 6, 2, "dog_white")
    _rect(cells, 13, 1, 6, 2, "dog_white")
    _draw_front_head(cells, dy=-4, mood="happy")


def _draw_jumping_dog(cells: dict, rise: int, paws_up: bool) -> None:
    # Compact airborne body leaves the ground rows empty instead of shifting a seated pose.
    _draw_front_tail(cells, 0, rise + 1, 2)
    _rect(cells, 7, 5 + rise, 8, 7, "dog_saddle")
    _rect(cells, 9, 6 + rise, 4, 6, "dog_white")
    _rect(cells, 7, 4 + rise, 3, 2, "dog_white")
    _rect(cells, 12, 4 + rise, 3, 2, "dog_white")
    if paws_up:
        _rect(cells, 4, 8 + rise, 3, 3, "dog_white")
        _rect(cells, 15, 8 + rise, 3, 3, "dog_white")
        _put(cells, 4, 10 + rise, "dog_cream")
        _put(cells, 17, 10 + rise, "dog_cream")
    else:
        _rect(cells, 5, 6 + rise, 3, 3, "dog_white")
        _rect(cells, 14, 6 + rise, 3, 3, "dog_white")
    _draw_front_head(cells, dy=rise, mood="happy")


def _draw_side_dog(cells: dict, flip: bool = False, roll_phase: int = 0) -> None:
    local: dict[tuple[int, int], str] = {}
    # A genuinely horizontal body for the sideways roll frames.
    _rect(local, 8, 4 + roll_phase, 10, 7, "dog_saddle")
    _put(local, 18, 6 + roll_phase, "dog_saddle_light")
    _rect(local, 8, 4 + roll_phase, 7, 3, "dog_white")
    _rect(local, 7, 3 + roll_phase, 4, 2, "dog_white")
    _rect(local, 13, 3 + roll_phase, 4, 2, "dog_white")
    for x, y in [(17, 8), (19, 9), (20, 10), (20, 11)]:
        _put(local, x, y + roll_phase, "dog_tan")

    _rect(local, 4, 8 + roll_phase, 7, 6, "dog_tan")
    _rect(local, 3, 9 + roll_phase, 2, 4, "dog_tan")
    for x, y in [(5, 15), (4, 14), (5, 14), (6, 14), (7, 13)]:
        _put(local, x, y + roll_phase, "dog_brown")
    _put(local, 5, 14 + roll_phase, "dog_ear")
    _rect(local, 3, 8 + roll_phase, 4, 3, "dog_cream")
    _rect(local, 3, 9 + roll_phase, 2, 1, "dog_nose")
    _rect(local, 6, 11 + roll_phase, 2, 2, "dog_nose")
    _put(local, 6, 12 + roll_phase, "dog_white")
    _rect(local, 8, 12 + roll_phase, 2, 1, "dog_brown")

    for (x, y), color in local.items():
        _put(cells, 21 - x if flip else x, y, color)


def _draw_back_dog(cells: dict, wiggle: int = 0) -> None:
    # Back-down pose: white belly and all four paws face the viewer.
    for x, y in [(16, 5), (18, 4), (19, 5), (20, 6)]:
        _put(cells, x + wiggle, y, "dog_tan")
    _rect(cells, 7 + wiggle, 4, 8, 9, "dog_saddle")
    _rect(cells, 8 + wiggle, 5, 6, 8, "dog_white")
    _rect(cells, 9 + wiggle, 6, 4, 5, "dog_cream")
    _rect(cells, 4 + wiggle, 8, 4, 3, "dog_white")
    _rect(cells, 14 + wiggle, 8, 4, 3, "dog_white")
    _rect(cells, 6 + wiggle, 3, 3, 3, "dog_white")
    _rect(cells, 13 + wiggle, 3, 3, 3, "dog_white")

    _rect(cells, 6 + wiggle, 12, 10, 6, "dog_tan")
    for x, y in [(5, 16), (4, 17), (3, 17), (16, 16), (17, 17), (18, 17)]:
        _put(cells, x + wiggle, y, "dog_brown")
    _put(cells, 4 + wiggle, 17, "dog_ear")
    _put(cells, 17 + wiggle, 17, "dog_ear")
    _rect(cells, 8 + wiggle, 12, 6, 3, "dog_cream")
    _rect(cells, 10 + wiggle, 13, 3, 1, "dog_nose")
    _put(cells, 11 + wiggle, 12, "dog_nose")
    _rect(cells, 8 + wiggle, 16, 2, 1, "dog_nose")
    _rect(cells, 13 + wiggle, 16, 2, 1, "dog_nose")
    _rect(cells, 10 + wiggle, 17, 2, 1, "dog_brown")


def _draw_success_pose(cells: dict, frame: int) -> None:
    # prepare -> crouch -> jump -> airborne -> land -> side roll -> belly -> recover -> sit
    if frame == 0:
        _draw_front_dog(cells, mood="happy", tail_phase=0)
    elif frame == 1:
        _draw_crouching_dog(cells, 1)
    elif frame == 2:
        _draw_jumping_dog(cells, -1, False)
    elif frame == 3:
        _draw_jumping_dog(cells, 0, True)
    elif frame == 4:
        _draw_jumping_dog(cells, -1, True)
    elif frame == 5:
        _draw_crouching_dog(cells, 3)
    elif frame == 6:
        _draw_side_dog(cells, False, 0)
    elif frame == 7:
        _draw_side_dog(cells, False, 1)
    elif frame == 8:
        _draw_back_dog(cells, 0)
    elif frame == 9:
        _draw_side_dog(cells, True, 0)
    elif frame == 10:
        _draw_crouching_dog(cells, 0)
    else:
        _draw_front_dog(cells, mood="happy", tail_phase=1)


def _draw_sleeping_dog(cells: dict, frame: int) -> None:
    breath = (0, 0, 1, 1, 0, 0, 1, 0)[frame]

    # Curled horizontal grayscale body, wrapped by its tail.
    _rect(cells, 8, 4, 10, 7, "gray_dark")
    _rect(cells, 10, 5, 7, 4, "gray")
    _rect(cells, 11, 10, 5, 1 + breath, "gray_dark")
    for x, y in [(17, 4), (19, 4), (20, 5), (20, 7), (19, 8), (18, 7), (17, 6)]:
        _put(cells, x, y, "gray")
    _rect(cells, 8, 3, 7, 2, "gray_light")

    # Head rests on the paws; the ear is folded, not upright.
    _rect(cells, 4, 6, 8, 7, "gray")
    _rect(cells, 3, 7, 2, 4, "gray")
    for x, y in [(5, 14), (4, 13), (5, 13), (6, 13), (7, 12)]:
        _put(cells, x, y + (1 if breath and x == 5 else 0), "gray_dark")
    _put(cells, 5, 13, "gray")
    _rect(cells, 3, 6, 5, 3, "gray_light")
    _rect(cells, 3, 7, 2, 1, "gray_dark")
    _rect(cells, 6, 10, 3, 1, "gray_dark")
    _rect(cells, 4, 3, 6, 2, "gray_light")


def _draw_low_sad_dog(cells: dict, frame: int) -> None:
    head_drop = (0, -1, -1, 0, 0, -1, 0, 0)[frame]
    blink = frame in (4, 5)

    # Low tail, flattened dark back, and paws stretched on the floor.
    tail = [(15, 3), (17, 3), (19, 2), (20, 2 + frame % 2)]
    for x, y in tail:
        _put(cells, x, y, "dog_tan")
    _rect(cells, 6, 2, 11, 6, "dog_saddle")
    _rect(cells, 8, 2, 6, 5, "dog_white")
    _rect(cells, 3, 1, 7, 2, "dog_white")
    _rect(cells, 12, 1, 7, 2, "dog_white")

    # Sideways drooped ears and lowered head are unique to cancelled.
    hy = head_drop
    for x, y in [(5, 12), (4, 11), (3, 10), (2, 9), (2, 8), (16, 12), (17, 11), (18, 10), (19, 9), (19, 8)]:
        _put(cells, x, y + hy, "dog_brown")
    _put(cells, 3, 9 + hy, "dog_ear")
    _put(cells, 18, 9 + hy, "dog_ear")
    _rect(cells, 5, 6 + hy, 12, 7, "dog_tan")
    _rect(cells, 7, 6 + hy, 8, 2, "dog_cream")
    _rect(cells, 10, 10 + hy, 2, 3, "dog_brown")
    if blink:
        _rect(cells, 7, 9 + hy, 2, 1, "dog_nose")
        _rect(cells, 13, 9 + hy, 2, 1, "dog_nose")
    else:
        _rect(cells, 7, 9 + hy, 2, 2, "dog_nose")
        _rect(cells, 13, 9 + hy, 2, 2, "dog_nose")
        _put(cells, 7, 10 + hy, "dog_white")
        _put(cells, 13, 10 + hy, "dog_white")
        if frame in (2, 3):
            _put(cells, 15, 8 + hy, "cyan")
    _rect(cells, 10, 7 + hy, 3, 1, "dog_nose")
    _put(cells, 11, 6 + hy, "dog_nose")
    _rect(cells, 10, 5 + hy, 3, 1, "dog_nose")


def _draw_laptop(cells: dict, frame: int) -> None:
    # Screen stays to the dog's right and below the eyes, never covering the face.
    _rect(cells, 16, 6, 5, 5, "gray_dark")
    _rect(cells, 17, 7, 3, 3, "cyan_dark")
    _put(cells, 17 + frame % 3, 8, "cyan")
    _rect(cells, 10, 4, 11, 2, "gray_dark")
    _rect(cells, 11, 5, 8, 1, "gray")
    _put(cells, 12 + frame % 6, 5, "cyan")


def _draw_typing_paws(cells: dict, dy: int, frame: int) -> None:
    left_y = 5 + (frame % 2)
    right_y = 5 + ((frame + 1) % 2)
    left_x = 10 + (frame // 2) % 2
    right_x = 14 + ((frame // 2) + 1) % 2
    _rect(cells, left_x, left_y, 3, 2, "dog_white")
    _rect(cells, right_x, right_y, 3, 2, "dog_white")
    _put(cells, left_x + 1, left_y, "dog_cream")
    _put(cells, right_x + 1, right_y, "dog_cream")
    if dy:
        _put(cells, left_x, left_y + 2, "dog_white")


def _draw_orbits(cells: dict, frame: int, active_count: int) -> None:
    orbit = [(2, 13), (3, 17), (8, 20), (14, 20), (19, 17), (20, 13), (19, 10), (3, 10)]
    colors = ("cyan", "green", "gold", "red")
    count = min(max(active_count, 2), 4)
    for index in range(count):
        x, y = orbit[(frame + index * 2) % len(orbit)]
        _put(cells, x, y, colors[index])
        if index == 0:
            _put(cells, x, y - 1, colors[index])


def _draw_approval(cells: dict, frame: int) -> None:
    """Yellow confirmation prompt beside the focused working pose."""
    y = 15 + (1 if frame in (2, 3) else 0)
    for x, py in ((19, y + 3), (18, y + 2), (19, y + 2), (20, y + 2), (20, y + 1)):
        _put(cells, x, py, "gold")
    _put(cells, 19, y, "gold")


def _draw_confetti(cells: dict, frame: int) -> None:
    points = [
        (3, 18, "gold"), (18, 17, "green"), (2, 12, "cyan"),
        (19, 11, "red"), (5, 20, "green"), (17, 20, "gold"),
    ]
    for index, (x, y, color) in enumerate(points):
        fall = (frame + index * 2) % 5
        _put(cells, x, max(1, y - fall), color)
        if (frame + index) % 2:
            _put(cells, x + 1, max(1, y - fall), color)


def _draw_error_spikes(cells: dict, dx: int, frame: int) -> None:
    spikes = [(4, 7), (3, 11), (4, 16), (17, 16), (18, 12), (17, 8), (8, 19), (13, 19)]
    color = "red_dark" if frame % 2 else "dog_saddle_light"
    for index, (x, y) in enumerate(spikes):
        if (index + frame) % 3 != 0:
            _put(cells, x + dx, y, color)


def _draw_warning(cells: dict, frame: int) -> None:
    x = 19
    color = "red" if frame % 2 else "gold"
    for row, width in enumerate((1, 3, 5)):
        for px in range(x - width // 2, x - width // 2 + width):
            _put(cells, px, 16 - row, color)
    _put(cells, x, 15, "red_dark")
    _put(cells, x, 13, "red_dark")


def _draw_sleep(cells: dict, frame: int) -> None:
    phase = frame % 4
    base_x = 14 + phase // 2
    base_y = 13 + (phase % 2)
    # Two pixel Zs drift upward independently of the curled dog's breathing.
    for x, y in [(base_x, base_y + 2), (base_x + 1, base_y + 2), (base_x + 1, base_y + 1), (base_x, base_y)]:
        _put(cells, x, y, "gray_light")
    if frame >= 2:
        for x, y in [(18, 18), (19, 18), (19, 17), (18, 16)]:
            _put(cells, x, y, "gray")
