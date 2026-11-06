#!/usr/bin/env python3
"""Turn one photo of a real pet into a desktop pet skin pack.

Everything runs locally with frameworks that ship with macOS:

1. Vision's foreground instance mask lifts the animal off its background.
2. Vision's animal body pose gives eyes, ears and paws, so layers and the
   background-scrap cleanup are placed from data instead of guesswork.
3. The cutout is animated with whole-subject affine transforms. Slicing it into
   bands tears the silhouette as soon as a band moves, so every motion here
   moves the whole subject: breathing, bobbing, jump squash, shake, sag, sleep.

Photo skins cannot fake eye blinks or independent limbs; that needs hand drawn
frames. See AGENTS.md for the trade-offs.

Usage:
    python3 scripts/make_photo_pet.py --photo ~/Desktop/dog.jpg --name 我家狗
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import Quartz  # noqa: E402
import Vision  # noqa: E402
from AppKit import (  # noqa: E402
    NSAffineTransform,
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSCompositeSourceOver,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGraphicsContext,
    NSImage,
    NSImageInterpolationHigh,
    NSString,
)
from Foundation import NSMakeRect, NSMakeSize, NSURL  # noqa: E402

from kiro_pet.config import SKINS_DIR  # noqa: E402

# state -> frame count; mirrors the built-in pixel pet so both feel the same
STATES = {
    "idle": 12,
    "running": 8,
    "success": 12,
    "error": 6,
    "cancelled": 8,
    "offline": 8,
}
CELL_HEIGHT = 148.0  # points; rendered at 2x for Retina
SUPERSAMPLE = 2.0


def log(message: str) -> None:
    print(message, flush=True)


def slugify(value: str, fallback: str = "pet") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug or fallback


def cutout(photo_path: Path, out_path: Path) -> None:
    """Vision foreground mask -> transparent PNG of the subject."""
    image = Quartz.CIImage.imageWithContentsOfURL_(NSURL.fileURLWithPath_(str(photo_path)))
    if image is None:
        raise SystemExit(f"读不出图片: {photo_path}")
    extent = image.extent()
    log(f"  输入 {int(extent.size.width)}x{int(extent.size.height)}")
    handler = Vision.VNImageRequestHandler.alloc().initWithCIImage_options_(image, {})
    request = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise SystemExit(f"抠图失败: {error}")
    results = request.results()
    if not results:
        raise SystemExit("没检测到前景主体，换一张主体更清晰的照片")
    observation = results[0]
    log(f"  前景实例 {len(observation.allInstances())} 个")
    buffer, error = observation.generateMaskedImageOfInstances_fromRequestHandler_croppedToInstancesExtent_error_(
        observation.allInstances(), handler, True, None
    )
    if buffer is None:
        raise SystemExit(f"生成蒙版失败: {error}")
    masked = Quartz.CIImage.imageWithCVPixelBuffer_(buffer)
    rect = masked.extent()
    log(f"  抠出主体 {int(rect.size.width)}x{int(rect.size.height)}")
    context = Quartz.CIContext.context()
    data = context.PNGRepresentationOfImage_format_colorSpace_options_(
        masked, Quartz.kCIFormatRGBA8, Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB), {}
    )
    if data is None:
        raise SystemExit("PNG 编码失败")
    data.writeToFile_atomically_(str(out_path), True)


def joints(photo_path: Path) -> dict:
    """Animal body pose joints in original pixel space."""
    image = Quartz.CIImage.imageWithContentsOfURL_(NSURL.fileURLWithPath_(str(photo_path)))
    extent = image.extent()
    handler = Vision.VNImageRequestHandler.alloc().initWithCIImage_options_(image, {})
    request = Vision.VNDetectAnimalBodyPoseRequest.alloc().init()
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise SystemExit(f"关节识别失败: {error}")
    results = request.results() or []
    if not results:
        raise SystemExit("没识别到动物姿态，换一张正面、四肢可见的照片")
    points, _ = results[0].recognizedPointsForJointsGroupName_error_(
        Vision.VNAnimalBodyPoseObservationJointsGroupNameAll, None
    )
    width = float(extent.size.width)
    height = float(extent.size.height)
    found = {}
    for name, point in (points or {}).items():
        location = point.location()
        found[str(name).replace("animal_joint_", "")] = {
            "px": float(location.x) * width,
            "py": (1.0 - float(location.y)) * height,
            "confidence": float(point.confidence()),
        }
    required = ("left_eye", "right_eye", "left_ear_top", "right_ear_top")
    missing = [name for name in required if found.get(name, {}).get("confidence", 0) < 0.3]
    if missing:
        raise SystemExit(f"关键关节置信度不足: {', '.join(missing)}，换一张更清晰的正面照")
    log("  关节点 " + " ".join(f"{n}={found[n]['confidence']:.2f}" for n in required))
    return {"size": [width, height], "joints": found}


class Rig:
    """Whole-subject affine puppet built from the cutout plus joints."""

    def __init__(self, cutout_path: Path, pose: dict) -> None:
        self.photo = NSImage.alloc().initWithContentsOfFile_(str(cutout_path))
        if self.photo is None:
            raise SystemExit("抠图结果无法加载")
        self.pw = float(self.photo.size().width)
        self.ph = float(self.photo.size().height)
        src_w = float(pose["size"][0])
        j = pose["joints"]
        k = self.pw / src_w
        ear_x = [j["left_ear_top"]["px"] * k, j["right_ear_top"]["px"] * k]
        offx = sum(ear_x) / 2 - self.pw / 2
        offy = min(j["left_ear_top"]["py"], j["right_ear_top"]["py"]) * k - self.ph * 0.05
        self.left_eye = (j["left_eye"]["px"] * k - offx, j["left_eye"]["py"] * k - offy)
        self.right_eye = (j["right_eye"]["px"] * k - offx, j["right_eye"]["py"] * k - offy)
        self.eye_gap = abs(self.left_eye[0] - self.right_eye[0]) or self.pw * 0.2
        self._clean_scrap()
        self.scale = CELL_HEIGHT * SUPERSAMPLE / self.ph
        self.cw = int(round(self.pw * self.scale)) + int(20 * SUPERSAMPLE)
        self.ch = int(round(CELL_HEIGHT * SUPERSAMPLE)) + int(22 * SUPERSAMPLE)

    def _clean_scrap(self) -> None:
        """Drop greyish background left between the ears by the mask."""
        rep = NSBitmapImageRep.imageRepWithData_(self.photo.TIFFRepresentation())
        width, height = int(rep.pixelsWide()), int(rep.pixelsHigh())
        kx, ky = width / self.pw, height / self.ph
        eye_top = min(self.left_eye[1], self.right_eye[1])
        x0 = int((min(self.left_eye[0], self.right_eye[0]) + self.eye_gap * 0.10) * kx)
        x1 = int((max(self.left_eye[0], self.right_eye[0]) - self.eye_gap * 0.10) * kx)
        removed = 0
        for y in range(0, max(1, int(eye_top * 0.55 * ky))):
            for x in range(max(0, x0), min(width, x1)):
                color = rep.colorAtX_y_(x, y)
                if color is None:
                    continue
                c = color.colorUsingColorSpaceName_("NSCalibratedRGBColorSpace")
                if c is None or c.alphaComponent() < 0.05:
                    continue
                r, g, b = c.redComponent(), c.greenComponent(), c.blueComponent()
                if r - b < 0.10 and max(r, g, b) - min(r, g, b) < 0.12:
                    rep.setColor_atX_y_(NSColor.clearColor(), x, y)
                    removed += 1
        if removed:
            image = NSImage.alloc().initWithSize_(NSMakeSize(self.pw, self.ph))
            image.addRepresentation_(rep)
            self.photo = image
        log(f"  清理背景残留 {removed} 像素")

    def _body(self, dx=0.0, dy=0.0, rotate=0.0, sx=1.0, sy=1.0, alpha=1.0) -> None:
        context = NSGraphicsContext.currentContext()
        context.saveGraphicsState()
        context.setImageInterpolation_(NSImageInterpolationHigh)
        transform = NSAffineTransform.transform()
        transform.translateXBy_yBy_(10 * SUPERSAMPLE + dx, 12 * SUPERSAMPLE + dy)
        transform.scaleXBy_yBy_(self.scale, self.scale)
        transform.translateXBy_yBy_(self.pw / 2, 0)  # anchor at the paws
        if rotate:
            transform.rotateByDegrees_(rotate)
        transform.scaleXBy_yBy_(sx, sy)
        transform.translateXBy_yBy_(-self.pw / 2, 0)
        transform.concat()
        self.photo.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, self.pw, self.ph), NSMakeRect(0, 0, self.pw, self.ph),
            NSCompositeSourceOver, alpha,
        )
        context.restoreGraphicsState()

    def _dots(self, frame: int, colors, y_ratio: float, size: float) -> None:
        for index, hexv in enumerate(colors):
            v = hexv.lstrip("#")
            NSColor.colorWithSRGBRed_green_blue_alpha_(
                int(v[0:2], 16) / 255, int(v[2:4], 16) / 255, int(v[4:6], 16) / 255, 0.95
            ).setFill()
            x = 10 * SUPERSAMPLE + (0.14 + 0.24 * index) * self.pw * self.scale
            y = 12 * SUPERSAMPLE + CELL_HEIGHT * SUPERSAMPLE * y_ratio + ((frame + index * 3) % 6) * 6 * SUPERSAMPLE
            NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, size, size)).fill()

    def _zzz(self, frame: int) -> None:
        attrs = {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(12.0 * SUPERSAMPLE),
            NSForegroundColorAttributeName: NSColor.whiteColor().colorWithAlphaComponent_(0.9),
        }
        NSString.stringWithString_("z" * (1 + frame % 3)).drawInRect_withAttributes_(
            NSMakeRect(self.cw - 40 * SUPERSAMPLE, self.ch - (26 + (frame % 3) * 3) * SUPERSAMPLE,
                       36 * SUPERSAMPLE, 16 * SUPERSAMPLE),
            attrs,
        )

    def frame(self, state: str, index: int) -> NSImage:
        image = NSImage.alloc().initWithSize_(NSMakeSize(self.cw, self.ch))
        image.lockFocus()
        if state == "idle":
            t = index / STATES["idle"] * math.tau
            self._body(sy=1.0 + math.sin(t) * 0.030, sx=1.0 - math.sin(t) * 0.012,
                       rotate=math.sin(t / 2) * 2.2)
        elif state == "running":
            t = index / STATES["running"] * math.tau
            self._body(dy=abs(math.sin(t)) * 5.0 * SUPERSAMPLE,
                       sy=1.0 - abs(math.sin(t)) * 0.035, sx=1.0 + abs(math.sin(t)) * 0.022,
                       rotate=math.sin(t * 2) * 2.6)
        elif state == "success":
            t = index / (STATES["success"] - 1)
            lift = math.sin(t * math.pi) * CELL_HEIGHT * SUPERSAMPLE * 0.26
            if index in (0, 1):
                self._body(sy=0.90, sx=1.06)
            elif index >= STATES["success"] - 2:
                self._body(sy=0.95, sx=1.03)
            else:
                self._body(dy=lift, sy=1.0 + lift / (CELL_HEIGHT * SUPERSAMPLE) * 0.10,
                           sx=1.0 - lift / (CELL_HEIGHT * SUPERSAMPLE) * 0.06,
                           rotate=math.sin(t * math.tau) * 3.0)
            self._dots(index, ("#34D399", "#FBBF24", "#22D3EE", "#FB7185"), 0.55, 4.0 * SUPERSAMPLE)
        elif state == "error":
            shake = (-3.0, 3.0, -2.0, 2.0, -1.0, 1.0)[index % 6] * SUPERSAMPLE
            self._body(dx=shake, rotate=shake / SUPERSAMPLE * 0.6, sy=0.995)
            self._dots(index, ("#FB7185", "#FB7185", "#FB7185"), 0.86, 3.5 * SUPERSAMPLE)
        elif state == "cancelled":
            sag = (0, 1, 2, 2, 1, 0, 1, 2)[index % 8]
            self._body(dy=-sag * 1.1 * SUPERSAMPLE, sy=0.94 - sag * 0.008, sx=1.03,
                       rotate=-2.5, alpha=0.95)
        else:  # offline
            t = index / STATES["offline"] * math.tau
            self._body(sy=0.84 + math.sin(t) * 0.016, sx=1.10, alpha=0.55, rotate=-3.0)
            self._zzz(index)
        image.unlockFocus()
        return image


def save_png(image: NSImage, path: Path) -> None:
    rep = NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    path.parent.mkdir(parents=True, exist_ok=True)
    data.writeToFile_atomically_(str(path), True)


# Both Vision requests used here (foreground instance mask, animal body pose)
# only exist on macOS 14+. Without this guard they return nil and the failure
# surfaces as an unrelated AttributeError deep in the pipeline.
MIN_MACOS_MAJOR = 14


def require_macos_version() -> None:
    import platform

    release = platform.mac_ver()[0] or ""
    try:
        major = int(release.split(".")[0])
    except (ValueError, IndexError):
        return  # unknown version string: let the pipeline try
    if major < MIN_MACOS_MAJOR:
        raise SystemExit(
            f"照片生成形象需要 macOS {MIN_MACOS_MAJOR} 或更高版本，当前是 macOS {release}。\n"
            "这一步用的是系统 Vision 框架的前景抠图与动物姿态识别，旧系统没有这两个能力。\n"
            "桌宠本身不受影响，继续使用内置的「像素小狗」形象即可。"
        )


def main() -> int:
    require_macos_version()
    parser = argparse.ArgumentParser(description="用一张宠物照片生成桌宠皮肤包")
    parser.add_argument("--photo", required=True, help="宠物正面照片路径")
    parser.add_argument("--name", default="", help="显示名称，例如 我家狗")
    parser.add_argument("--id", default="", help="皮肤 ID，默认按名称或文件名生成")
    parser.add_argument("--out", default=str(SKINS_DIR), help="皮肤包输出目录")
    parser.add_argument("--keep-cutout", action="store_true", help="保留抠图中间文件")
    args = parser.parse_args()

    photo = Path(args.photo).expanduser().resolve()
    if not photo.is_file():
        raise SystemExit(f"照片不存在: {photo}")
    name = args.name.strip() or photo.stem
    skin_id = args.id.strip() or slugify(args.name or photo.stem)
    target = Path(args.out).expanduser() / skin_id
    target.mkdir(parents=True, exist_ok=True)

    log(f"[1/4] 抠图: {photo.name}")
    cutout_path = target / "cutout.png"
    cutout(photo, cutout_path)

    log("[2/4] 识别关节点")
    pose = joints(photo)

    log("[3/4] 生成动画帧")
    rig = Rig(cutout_path, pose)
    total = 0
    for state, count in STATES.items():
        for index in range(count):
            save_png(rig.frame(state, index), target / "frames" / state / f"{index:02d}.png")
            total += 1
        log(f"  {state}: {count} 帧")

    log("[4/4] 写入皮肤清单")
    manifest = {
        "id": skin_id,
        "name": name,
        "kind": "photo",
        "source": photo.name,
        "cell": [round(rig.cw / SUPERSAMPLE, 1), round(rig.ch / SUPERSAMPLE, 1)],
        "states": STATES,
    }
    (target / "skin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not args.keep_cutout:
        cutout_path.unlink(missing_ok=True)

    log("")
    log(f"完成: {total} 帧 -> {target}")
    log(f"皮肤 ID: {skin_id}   显示名: {name}")
    log("在桌宠菜单里选「更换形象」→ " + name + " 即可切换。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
