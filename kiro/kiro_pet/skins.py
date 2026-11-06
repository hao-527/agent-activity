"""Pluggable pet skins.

The built-in pet is hand drawn pixel art in :mod:`kiro_pet.sprites`. A skin
pack replaces those frames with pre-rendered images, which is how a photo of a
real pet becomes a desktop companion. A pack is a directory:

    <skins dir>/<id>/skin.json
    <skins dir>/<id>/frames/<state>/00.png ...

``skin.json`` declares the frame count per state, so any generator can produce
packs as long as it writes that manifest.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from AppKit import NSImage

from .config import SKINS_DIR
from .sprites import FRAME_COUNTS

BUILTIN_ID = "pixel"
BUILTIN_NAME = "像素小狗"
MANIFEST = "skin.json"
# Multi-session and approval-wait states reuse running frames unless a pack
# explicitly ships its own artwork.
STATE_FALLBACKS = {"multi": "running", "waiting": "running"}


@dataclass(frozen=True)
class SkinInfo:
    id: str
    name: str
    path: Path | None

    @property
    def builtin(self) -> bool:
        return self.path is None


class Skin:
    """One loaded skin pack: frame counts plus lazily loaded images."""

    def __init__(self, info: SkinInfo, states: dict[str, int], cell: tuple[float, float]) -> None:
        self.info = info
        self.states = states
        self.cell = cell
        self._images: dict[tuple[str, int], NSImage] = {}

    @property
    def aspect(self) -> float:
        width, height = self.cell
        return float(width) / float(height) if height else 1.0

    def _resolve(self, state: str) -> str:
        if state in self.states:
            return state
        alias = STATE_FALLBACKS.get(state)
        if alias and alias in self.states:
            return alias
        return next(iter(self.states)) if self.states else state

    def frame_count(self, state: str) -> int:
        return max(1, int(self.states.get(self._resolve(state), 1)))

    def image(self, state: str, frame: int) -> NSImage | None:
        resolved = self._resolve(state)
        index = frame % self.frame_count(resolved)
        key = (resolved, index)
        cached = self._images.get(key)
        if cached is not None:
            return cached
        if self.info.path is None:
            return None
        path = self.info.path / "frames" / resolved / f"{index:02d}.png"
        image = NSImage.alloc().initWithContentsOfFile_(str(path))
        if image is None:
            return None
        self._images[key] = image
        return image


def _read_manifest(directory: Path) -> tuple[str, dict[str, int], tuple[float, float]] | None:
    try:
        payload = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    states = payload.get("states")
    if not isinstance(states, dict) or not states:
        return None
    counts: dict[str, int] = {}
    for state, count in states.items():
        try:
            value = int(count)
        except (TypeError, ValueError):
            continue
        if value > 0:
            counts[str(state)] = value
    if not counts:
        return None
    cell = payload.get("cell") or [111, 148]
    try:
        size = (float(cell[0]), float(cell[1]))
    except (TypeError, ValueError, IndexError):
        size = (111.0, 148.0)
    name = str(payload.get("name") or directory.name)
    return name, counts, size


def list_skins(skins_dir: Path = SKINS_DIR) -> tuple[SkinInfo, ...]:
    """Built-in skin first, then every valid pack found on disk."""
    found = [SkinInfo(BUILTIN_ID, BUILTIN_NAME, None)]
    try:
        directories = sorted(p for p in Path(skins_dir).iterdir() if p.is_dir())
    except OSError:
        directories = []
    for directory in directories:
        manifest = _read_manifest(directory)
        if manifest is None:
            continue
        found.append(SkinInfo(directory.name, manifest[0], directory))
    return tuple(found)


def load_skin(skin_id: str, skins_dir: Path = SKINS_DIR) -> Skin | None:
    """Load one pack; None means use the built-in pixel pet."""
    if not skin_id or skin_id == BUILTIN_ID:
        return None
    directory = Path(skins_dir) / skin_id
    manifest = _read_manifest(directory)
    if manifest is None:
        return None
    name, states, cell = manifest
    return Skin(SkinInfo(directory.name, name, directory), states, cell)


def frame_count(state: str, skin: Skin | None) -> int:
    if skin is not None:
        return skin.frame_count(state)
    return FRAME_COUNTS.get(state, FRAME_COUNTS["idle"])
