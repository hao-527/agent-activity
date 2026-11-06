#!/usr/bin/env python3
"""Export checkerboard-backed RGBA previews for every desktop-pet sprite."""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kiro_pet.sprites import FRAME_COUNTS, PALETTE, sprite_frame


STATES = ("offline", "idle", "running", "multi", "waiting", "success", "error", "cancelled")
KEY_STATES = ("idle", "running", "waiting", "success", "offline")
SCALE = 6
FRAME_GAP = 4
CANVAS_MARGIN = 8
ROW_GAP = 14
CHECKER_SIZE = 6
CHECKER_COLORS = ((40, 46, 56, 255), (60, 68, 80, 255))
SEPARATOR_COLOR = (10, 15, 24, 255)
SEPARATOR_HIGHLIGHT = (71, 85, 105, 255)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Raster:
    """A minimal in-memory RGBA canvas."""

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("canvas dimensions must be positive")
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height * 4)

    def fill_checkerboard(self) -> None:
        for y in range(self.height):
            for x in range(self.width):
                color = CHECKER_COLORS[((x // CHECKER_SIZE) + (y // CHECKER_SIZE)) % 2]
                offset = (y * self.width + x) * 4
                self.pixels[offset : offset + 4] = bytes(color)

    def fill_rect(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: tuple[int, int, int, int],
    ) -> None:
        if width < 0 or height < 0:
            raise ValueError("rectangle dimensions must be nonnegative")
        if x < 0 or y < 0 or x + width > self.width or y + height > self.height:
            raise ValueError("rectangle exceeds canvas")
        row = bytes(color) * width
        for row_y in range(y, y + height):
            start = (row_y * self.width + x) * 4
            self.pixels[start : start + len(row)] = row


def parse_rgb_hex(value: str) -> tuple[int, int, int, int]:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"invalid palette value: {value!r}")
    try:
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16), 255
    except ValueError as exc:
        raise ValueError(f"invalid palette value: {value!r}") from exc


def validate_sprite_data() -> tuple[dict[str, tuple[object, ...]], tuple[int, int]]:
    """Validate every palette entry, coordinate, and frame, then return all frames."""
    for key, value in PALETTE.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"invalid palette key: {key!r}")
        parse_rgb_hex(value)

    frames_by_state: dict[str, tuple[object, ...]] = {}
    expected_size: tuple[int, int] | None = None
    for state in STATES:
        if state not in FRAME_COUNTS:
            raise ValueError(f"missing FRAME_COUNTS entry: {state}")
        count = FRAME_COUNTS[state]
        if not isinstance(count, int) or count <= 0:
            raise ValueError(f"invalid frame count for {state}: {count!r}")

        state_frames = []
        for frame_index in range(count):
            active_count = 4 if state == "multi" else 0
            sprite = sprite_frame(state, frame_index, active_count)
            if not isinstance(sprite.width, int) or not isinstance(sprite.height, int):
                raise ValueError(f"non-integer dimensions at {state} frame {frame_index}")
            if sprite.width <= 0 or sprite.height <= 0:
                raise ValueError(f"nonpositive dimensions at {state} frame {frame_index}")
            size = (sprite.width, sprite.height)
            if expected_size is None:
                expected_size = size
            elif size != expected_size:
                raise ValueError(
                    f"inconsistent dimensions at {state} frame {frame_index}: "
                    f"{size} != {expected_size}"
                )

            seen: set[tuple[int, int]] = set()
            for pixel in sprite.pixels:
                if not isinstance(pixel, tuple) or len(pixel) != 3:
                    raise ValueError(f"invalid pixel at {state} frame {frame_index}: {pixel!r}")
                x, y, palette_key = pixel
                if not isinstance(x, int) or not isinstance(y, int):
                    raise ValueError(f"non-integer coordinate at {state} frame {frame_index}")
                if not (0 <= x < sprite.width and 0 <= y < sprite.height):
                    raise ValueError(
                        f"coordinate out of range at {state} frame {frame_index}: {(x, y)}"
                    )
                if palette_key not in PALETTE:
                    raise ValueError(
                        f"missing palette key at {state} frame {frame_index}: {palette_key!r}"
                    )
                parse_rgb_hex(PALETTE[palette_key])
                if (x, y) in seen:
                    raise ValueError(
                        f"repeated coordinate at {state} frame {frame_index}: {(x, y)}"
                    )
                seen.add((x, y))
            state_frames.append(sprite)
        frames_by_state[state] = tuple(state_frames)

    assert expected_size is not None
    return frames_by_state, expected_size


def render_frame(canvas: Raster, sprite: object, origin_x: int, origin_y: int) -> None:
    """Convert Cocoa's bottom-up sprite coordinates into top-down PNG rows."""
    for x, y, palette_key in sprite.pixels:
        png_y = origin_y + (sprite.height - 1 - y) * SCALE
        canvas.fill_rect(
            origin_x + x * SCALE,
            png_y,
            SCALE,
            SCALE,
            parse_rgb_hex(PALETTE[palette_key]),
        )


def png_chunk(type_code: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(type_code)
    crc = zlib.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + type_code + payload + struct.pack(">I", crc)


def encode_rgba_png(path: Path, canvas: Raster) -> None:
    """Write an 8-bit RGBA PNG with filter type 0 on every scanline."""
    stride = canvas.width * 4
    raw = bytearray()
    for y in range(canvas.height):
        raw.append(0)
        start = y * stride
        raw.extend(canvas.pixels[start : start + stride])
    ihdr = struct.pack(">IIBBBBB", canvas.width, canvas.height, 8, 6, 0, 0, 0)
    png_bytes = (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(png_bytes)


def make_all_states_preview(
    frames_by_state: dict[str, tuple[object, ...]],
    logical_size: tuple[int, int],
) -> tuple[Raster, list[int]]:
    logical_width, logical_height = logical_size
    frame_width = logical_width * SCALE
    frame_height = logical_height * SCALE
    max_count = max(FRAME_COUNTS[state] for state in STATES)
    width = 2 * CANVAS_MARGIN + max_count * frame_width + (max_count - 1) * FRAME_GAP
    height = (
        2 * CANVAS_MARGIN
        + len(STATES) * frame_height
        + (len(STATES) - 1) * ROW_GAP
    )
    canvas = Raster(width, height)
    canvas.fill_checkerboard()
    row_tops: list[int] = []

    for row_index, state in enumerate(STATES):
        row_top = CANVAS_MARGIN + row_index * (frame_height + ROW_GAP)
        row_tops.append(row_top)
        for frame_index, sprite in enumerate(frames_by_state[state]):
            origin_x = CANVAS_MARGIN + frame_index * (frame_width + FRAME_GAP)
            render_frame(canvas, sprite, origin_x, row_top)
        if row_index < len(STATES) - 1:
            gap_top = row_top + frame_height
            separator_y = gap_top + (ROW_GAP - 4) // 2
            canvas.fill_rect(0, separator_y, width, 4, SEPARATOR_COLOR)
            canvas.fill_rect(0, separator_y, width, 1, SEPARATOR_HIGHLIGHT)

    return canvas, row_tops


def make_strip(frames: tuple[object, ...], logical_size: tuple[int, int]) -> Raster:
    logical_width, logical_height = logical_size
    frame_width = logical_width * SCALE
    frame_height = logical_height * SCALE
    width = 2 * CANVAS_MARGIN + len(frames) * frame_width + (len(frames) - 1) * FRAME_GAP
    if width > 1900:
        raise ValueError(f"strip width {width} exceeds 1900 pixels")
    height = 2 * CANVAS_MARGIN + frame_height
    canvas = Raster(width, height)
    canvas.fill_checkerboard()
    for frame_index, sprite in enumerate(frames):
        origin_x = CANVAS_MARGIN + frame_index * (frame_width + FRAME_GAP)
        render_frame(canvas, sprite, origin_x, CANVAS_MARGIN)
    return canvas


def write_report(
    path: Path,
    all_canvas: Raster,
    row_tops: list[int],
    logical_size: tuple[int, int],
    strip_canvases: dict[str, Raster],
) -> None:
    logical_width, logical_height = logical_size
    frame_width = logical_width * SCALE
    frame_height = logical_height * SCALE
    lines = [
        "Kiro desktop pet sprite preview manifest",
        "================================================",
        "All-states image: dog_all_states.png",
        f"Canvas: {all_canvas.width}x{all_canvas.height} pixels, RGBA 8-bit",
        f"Logical sprite canvas: {logical_width}x{logical_height} pixels",
        f"Scale: {SCALE}x ({frame_width}x{frame_height} pixels per rendered frame)",
        f"Canvas margin: {CANVAS_MARGIN} pixels",
        f"Frame gap: {FRAME_GAP} pixels (checkerboard remains visible)",
        f"Row gap: {ROW_GAP} pixels with a 4-pixel separator",
        f"Checkerboard: {CHECKER_SIZE}x{CHECKER_SIZE} pixel cells, colors {CHECKER_COLORS}",
        "Coordinate orientation: sprite y=0 is rendered at the bottom to match the Cocoa UI",
        "Multi preview: active_count=4",
        "",
        "Rows:",
    ]
    for row_number, (state, row_top) in enumerate(zip(STATES, row_tops), start=1):
        count = FRAME_COUNTS[state]
        lines.append(
            f"Row {row_number}: state={state}; frames=0-{count - 1}; count={count}; "
            f"PNG y={row_top}-{row_top + frame_height - 1}"
        )
    lines.extend(["", "Key animation strips:"])
    for state in KEY_STATES:
        canvas = strip_canvases[state]
        count = FRAME_COUNTS[state]
        lines.append(
            f"dog_{state}_strip.png: {canvas.width}x{canvas.height}; "
            f"frames=0-{count - 1}; count={count}"
        )
    lines.extend(
        [
            "",
            "PNG encoding: signature + IHDR + zlib-compressed IDAT + IEND",
            "Scanline filter: 0 (none) for every row",
            "Palette pixels: opaque RGBA; logical transparency: checkerboard background",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def inspect_png(path: Path) -> tuple[int, int, int]:
    """Parse and validate PNG chunks, pixels, dimensions, size, and scanline filters."""
    data = path.read_bytes()
    if len(data) <= 1024:
        raise ValueError(f"{path.name} is only {len(data)} bytes; expected > 1 KiB")
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path.name} has an invalid PNG signature")

    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    width = height = 0
    idat_parts: list[bytes] = []
    seen_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError(f"{path.name} has a truncated chunk header")
        length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        type_code = data[offset : offset + 4]
        offset += 4
        payload_end = offset + length
        if payload_end + 4 > len(data):
            raise ValueError(f"{path.name} has a truncated chunk")
        payload = data[offset:payload_end]
        stored_crc = struct.unpack_from(">I", data, payload_end)[0]
        actual_crc = zlib.crc32(type_code)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if stored_crc != actual_crc:
            raise ValueError(f"{path.name} has a CRC mismatch in {type_code!r}")
        offset = payload_end + 4

        if type_code == b"IHDR":
            if chunk_index != 0 or length != 13:
                raise ValueError(f"{path.name} has an invalid IHDR chunk")
            fields = struct.unpack(">IIBBBBB", payload)
            width, height = fields[0], fields[1]
            if width <= 0 or height <= 0:
                raise ValueError(f"{path.name} has nonpositive dimensions")
            if fields[2:] != (8, 6, 0, 0, 0):
                raise ValueError(f"{path.name} is not an 8-bit noninterlaced RGBA PNG")
        elif type_code == b"IDAT":
            idat_parts.append(payload)
        elif type_code == b"IEND":
            if length != 0 or offset != len(data):
                raise ValueError(f"{path.name} has an invalid IEND chunk")
            seen_iend = True
            break
        chunk_index += 1

    if not seen_iend or not idat_parts or width <= 0 or height <= 0:
        raise ValueError(f"{path.name} is missing IHDR, IDAT, or IEND")
    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except zlib.error as exc:
        raise ValueError(f"{path.name} has an invalid zlib IDAT payload") from exc
    stride = width * 4
    expected_length = height * (stride + 1)
    if len(raw) != expected_length:
        raise ValueError(
            f"{path.name} decompressed to {len(raw)} bytes, expected {expected_length}"
        )
    if any(raw[row * (stride + 1)] != 0 for row in range(height)):
        raise ValueError(f"{path.name} does not use filter 0 on every row")
    return width, height, len(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export RGBA sprite preview PNGs")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "previews",
        help="output directory (default: <project>/previews)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    frames_by_state, logical_size = validate_sprite_data()
    all_canvas, row_tops = make_all_states_preview(frames_by_state, logical_size)
    all_path = output_dir / "dog_all_states.png"
    encode_rgba_png(all_path, all_canvas)

    strip_canvases: dict[str, Raster] = {}
    png_paths = [all_path]
    for state in KEY_STATES:
        canvas = make_strip(frames_by_state[state], logical_size)
        strip_canvases[state] = canvas
        path = output_dir / f"dog_{state}_strip.png"
        encode_rgba_png(path, canvas)
        png_paths.append(path)

    report_path = output_dir / "dog_all_states.txt"
    write_report(report_path, all_canvas, row_tops, logical_size, strip_canvases)

    results = [inspect_png(path) for path in png_paths]
    post_frames, post_size = validate_sprite_data()
    frame_total = sum(len(frames) for frames in post_frames.values())
    expected_total = sum(FRAME_COUNTS[state] for state in STATES)
    if post_size != logical_size or frame_total != expected_total:
        raise ValueError("post-export sprite validation did not match initial validation")

    print(f"Output directory: {output_dir}")
    for path, (width, height, file_size) in zip(png_paths, results):
        print(f"OK: {path.name}\t{width}x{height}\t{file_size} bytes")
    print(f"OK: {report_path.name}\t{report_path.stat().st_size} bytes")
    print(
        "Validation: PNG signature/IHDR/CRC/zlib/filter0 and "
        f"sprite coordinates/palette for {frame_total} frames PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
