#!/usr/bin/env python3
"""Render the real pet UI offscreen and export PNGs for documentation.

Everything here goes through the same layout/render code the live window uses,
so the exported images are the actual appearance, not mock-ups.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from AppKit import (  # noqa: E402
    NSAffineTransform,
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSCompositeSourceOver,
    NSImage,
)
from Foundation import NSMakeRect, NSMakeSize, NSMakePoint  # noqa: E402

from kiro_pet import render  # noqa: E402
from kiro_pet.layout import Box, compute_layout, format_duration  # noqa: E402
from kiro_pet.render import BubbleRow, PetScene  # noqa: E402
from kiro_pet.status_icon import status_icon  # noqa: E402
from kiro_pet.theme import phase_accent, state_accent, theme_for  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "previews" / "doc"
BACKDROP = "#E7ECF3"
DARK = theme_for(True)


def row(title, seconds, phase="running", muted=False, session="sess_demo"):
    return BubbleRow(
        accent=phase_accent(phase),
        title=title,
        time_text=format_duration(seconds) if seconds else "",
        active=phase in ("running", "waiting"),
        muted=muted,
        session_id="" if muted else session,
    )


def canvas(width, height, backdrop=BACKDROP, pad=14.0):
    image = NSImage.alloc().initWithSize_(NSMakeSize(width + pad * 2, height + pad * 2))
    image.lockFocus()
    render.color(backdrop).setFill()
    NSBezierPath.bezierPathWithRect_(
        NSMakeRect(0, 0, width + pad * 2, height + pad * 2)
    ).fill()
    return image


def save(image, name):
    OUT.mkdir(parents=True, exist_ok=True)
    data = image.TIFFRepresentation()
    rep = NSBitmapImageRep.imageRepWithData_(data)
    png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    path = OUT / name
    png.writeToFile_atomically_(str(path), True)
    print(f"  wrote {path.name}  {int(image.size().width)}x{int(image.size().height)}")


def render_scene(scene, layout, pad=14.0, backdrop=BACKDROP):
    image = canvas(layout.width, layout.height, backdrop, pad)
    from AppKit import NSGraphicsContext

    context = NSGraphicsContext.currentContext()
    context.saveGraphicsState()
    shift = NSAffineTransform.transform()
    shift.translateXBy_yBy_(pad, pad)
    shift.concat()
    render.draw_scene(scene, layout, DARK)
    context.restoreGraphicsState()
    image.unlockFocus()
    return image


def crop(image, x, y, width, height, pad=14.0, backdrop=BACKDROP):
    out = canvas(width, height, backdrop, pad)
    image.drawInRect_fromRect_operation_fraction_(
        NSMakeRect(pad, pad, width, height),
        NSMakeRect(x, y, width, height),
        NSCompositeSourceOver,
        1.0,
    )
    out.unlockFocus()
    return out


def export_bubbles():
    layout3 = compute_layout("medium", 3)
    save(
        render_scene(
            PetScene(
                state="multi",
                frame=2,
                active_count=2,
                headline="2 个任务并行运行",
                rows=(
                    row("重构登录模块", 214),
                    row("桌宠样式与功能全面优化", 42),
                    row("还有 3 个会话", 0, "idle", muted=True),
                ),
            ),
            layout3,
        ),
        "01-bubble-multi.png",
    )
    layout2 = compute_layout("medium", 2)
    save(
        render_scene(
            PetScene(
                state="running",
                frame=1,
                active_count=1,
                headline="Kiro 正在工作",
                rows=(row("生成本周项目报告", 96), row("正在执行工具", 0, "idle", muted=True)),
            ),
            layout2,
        ),
        "02-bubble-running.png",
    )
    save(
        render_scene(
            PetScene(
                state="success",
                frame=3,
                active_count=0,
                headline="任务完成啦！",
                rows=(row("桌宠样式与功能全面优化", 8, "success"),),
            ),
            compute_layout("medium", 1),
        ),
        "03-bubble-success.png",
    )
    save(
        render_scene(
            PetScene(
                state="error",
                frame=1,
                active_count=0,
                headline="Kiro 出现异常",
                rows=(row("连接已中断，请重试", 12, "error"),),
            ),
            compute_layout("medium", 1),
        ),
        "04-bubble-error.png",
    )
    save(
        render_scene(
            PetScene(
                state="idle",
                frame=4,
                active_count=0,
                headline="Kiro 在待命",
                rows=(row("有任务时我会动起来", 0, "idle", muted=True),),
            ),
            compute_layout("medium", 1),
        ),
        "05-bubble-idle.png",
    )
    save(
        render_scene(
            PetScene(
                state="offline",
                frame=2,
                active_count=0,
                headline="Kiro 未运行",
                rows=(row("启动 Kiro 我就醒过来", 0, "idle", muted=True),),
            ),
            compute_layout("medium", 1),
        ),
        "06-bubble-offline.png",
    )


def export_states_strip():
    """All eight pet states side by side, sprite only."""
    layout = compute_layout("medium", 1, show_bubble=False)
    states = ("offline", "idle", "running", "multi", "waiting", "success", "error", "cancelled")
    cell_w = layout.sprite.width + 18
    cell_h = layout.height
    pad = 14.0
    out = canvas(cell_w * len(states), cell_h, BACKDROP, pad)
    from AppKit import NSGraphicsContext

    for index, state in enumerate(states):
        frame_index = {
            "success": 3, "error": 1, "idle": 4, "offline": 2, "waiting": 1
        }.get(state, 2)
        scene = PetScene(
            state=state,
            frame=frame_index,
            active_count=3 if state == "multi" else (
                1 if state in ("running", "waiting") else 0
            ),
            headline="",
            show_bubble=False,
        )
        context = NSGraphicsContext.currentContext()
        context.saveGraphicsState()
        shift = NSAffineTransform.transform()
        shift.translateXBy_yBy_(pad + index * cell_w - layout.sprite.x + 9, pad)
        shift.concat()
        render.draw_scene(scene, layout, DARK)
        context.restoreGraphicsState()
    out.unlockFocus()
    save(out, "07-states-strip.png")


def export_rails():
    layout = compute_layout("medium", 3)
    cases = (
        ("08-rail-rest.png", "left", 36.0, ()),
        (
            "09-rail-preview.png",
            "left",
            248.0,
            (row("重构登录模块", 214), row("桌宠样式与功能全面优化", 42), row("生成本周项目报告", 5830, "success")),
        ),
        (
            "10-rail-bottom.png",
            "bottom",
            214.0,
            (row("重构登录模块", 214), row("桌宠样式与功能全面优化", 42)),
        ),
    )
    for name, edge, sliver, rows in cases:
        scene = PetScene(
            state="multi" if rows else "running",
            frame=3,
            active_count=2 if rows else 1,
            headline="2 个任务并行运行" if rows else "Kiro 正在工作",
            rows=rows,
            docked_edge=edge,
            tab_sliver=sliver,
            tab_thickness=36.0,
            tab_caption="2 个" if rows else "3分",
            hover=bool(rows),
        )
        full = render_scene(scene, layout, pad=0.0, backdrop=BACKDROP)
        if edge == "left":
            box = (layout.width - sliver, 0.0, sliver, layout.height)
        else:
            box = (0.0, layout.height - sliver, layout.width, sliver)
        save(crop(full, *box), name)


def export_menubar():
    """Kiro's menu-bar item on light and dark menu bars, every state."""
    from AppKit import (
        NSAppearance,
        NSAppearanceNameAqua,
        NSAppearanceNameDarkAqua,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSString,
    )

    states = (
        ("running", "2"),
        ("multi", "3"),
        ("waiting", "1"),
        ("success", ""),
        ("error", ""),
        ("idle", ""),
        ("offline", ""),
    )
    cell = 96.0
    row_height = 30.0
    pad = 10.0
    out = canvas(cell * len(states), row_height * 2, "#F2F4F8", pad)
    rows = (
        (
            "#F2F4F8",
            NSAppearance.appearanceNamed_(NSAppearanceNameAqua),
            NSColor.blackColor().colorWithAlphaComponent_(0.8),
        ),
        (
            "#1C1C1E",
            NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua),
            NSColor.whiteColor().colorWithAlphaComponent_(0.9),
        ),
    )
    for row_index, (background, appearance, text_color) in enumerate(rows):
        row_y = pad + (len(rows) - 1 - row_index) * row_height
        render.color(background).setFill()
        NSBezierPath.bezierPathWithRect_(
            NSMakeRect(pad, row_y, cell * len(states), row_height)
        ).fill()
        for index, (state, count) in enumerate(states):
            x = pad + index * cell + 6.0
            y = row_y + 4.0
            icon = status_icon(
                state_accent(state), appearance, int(count) if count else 0
            )
            icon_width = icon.size().width
            icon.drawInRect_(NSMakeRect(x, y, icon_width, 22.0))
            attrs = {
                NSFontAttributeName: NSFont.systemFontOfSize_(13.0),
                NSForegroundColorAttributeName: text_color,
            }
            NSString.stringWithString_(state).drawInRect_withAttributes_(
                NSMakeRect(x + icon_width + 4.0, y + 4.0, cell - icon_width - 8.0, 16.0),
                attrs,
            )
    out.unlockFocus()
    save(out, "11-menubar-states.png")


def export_notifications():
    """macOS notification banners for every category the pet can send.

    Titles and sounds come from kiro_pet.notify so the images stay truthful.
    """
    from AppKit import NSFont, NSFontAttributeName, NSForegroundColorAttributeName, NSString
    from kiro_pet.notify import _CATEGORY_META

    cases = (
        ("12-notify-success.png", "success", "重构登录模块", "17:41:38"),
        ("13-notify-error.png", "error", "模型繁忙或过载", "17:42:05"),
        ("14-notify-interrupt.png", "interrupt", "", "17:41:38"),
        ("15-notify-cancel.png", "cancel", "", "17:43:11"),
        ("16-notify-long-run.png", "long_run", "重构登录模块 已运行 18分", "17:59:02"),
        ("17-notify-approval.png", "approval", "", "18:02:44"),
    )
    fallback = {
        "success": "当前任务已结束",
        "error": "执行出现异常",
        "interrupt": "AI 执行已停止，请回到 Kiro 重试",
        "cancel": "本次执行已中止",
        "long_run": "任务仍在执行中",
        "approval": "有敏感操作待批准",
    }
    jumpable = {"success", "error", "interrupt", "cancel", "long_run"}

    card_w, card_h, pad = 540.0, 110.0, 16.0

    def banner(category, subtitle, clock):
        title = _CATEGORY_META[category][0]
        subtitle = subtitle or fallback[category]
        tail = "点我跳到这个会话" if category in jumpable else "点我跳回 Kiro"
        image = canvas(card_w, card_h, BACKDROP, pad)
        card = Box(pad, pad, card_w, card_h)
        render.color("#000000", 0.10).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(card.x, card.y - 2, card.width, card.height), 20, 20
        ).fill()
        render.color("#F4F3F7", 0.99).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(*card.as_tuple()), 20, 20
        ).fill()
        render.color("#000000", 0.08).setStroke()
        border = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(card.x + 0.5, card.y + 0.5, card.width - 1, card.height - 1), 20, 20
        )
        border.setLineWidth_(1.0)
        border.stroke()

        # terminal-notifier's icon: a dark terminal tile with a prompt glyph
        icon = Box(card.x + 18, card.mid_y - 29, 58, 58)
        render.color("#8E8E93").setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(*icon.as_tuple()), 12, 12
        ).fill()
        inner = icon.inset(4, 4)
        render.color("#1C1C1E").setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(*inner.as_tuple()), 9, 9
        ).fill()
        prompt_attrs = {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(18.0),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
        }
        NSString.stringWithString_(">_").drawInRect_withAttributes_(
            NSMakeRect(inner.x + 8, inner.y + 13, inner.width, 24), prompt_attrs
        )

        text_x = icon.max_x + 16
        text_w = card.max_x - text_x - 20
        lines = (
            (title, NSFont.boldSystemFontOfSize_(17.0), 0.92),
            (subtitle, NSFont.boldSystemFontOfSize_(16.0), 0.88),
            (f"时间 {clock}，{tail}", NSFont.systemFontOfSize_(16.0), 0.62),
        )
        y = card.max_y - 32
        for value, font, alpha in lines:
            attrs = {
                NSFontAttributeName: font,
                NSForegroundColorAttributeName: NSColor.blackColor().colorWithAlphaComponent_(alpha),
            }
            NSString.stringWithString_(value).drawInRect_withAttributes_(
                NSMakeRect(text_x, y, text_w, 26), attrs
            )
            y -= 27
        image.unlockFocus()
        return image

    for name, category, subtitle, clock in cases:
        save(banner(category, subtitle, clock), name)

    # one stacked overview of all six banners
    gap = 10.0
    pad_all = 16.0
    total_h = len(cases) * card_h + (len(cases) - 1) * gap
    out = canvas(card_w, total_h, BACKDROP, pad_all)
    out.unlockFocus()
    stack = NSImage.alloc().initWithSize_(
        NSMakeSize(card_w + pad_all * 2, total_h + pad_all * 2)
    )
    stack.lockFocus()
    render.color(BACKDROP).setFill()
    NSBezierPath.bezierPathWithRect_(
        NSMakeRect(0, 0, card_w + pad_all * 2, total_h + pad_all * 2)
    ).fill()
    for index, (_, category, subtitle, clock) in enumerate(cases):
        single = banner(category, subtitle, clock)
        y = total_h + pad_all - (index + 1) * card_h - index * gap
        single.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(pad_all - 16.0, y - 16.0, single.size().width, single.size().height),
            NSMakeRect(0, 0, single.size().width, single.size().height),
            NSCompositeSourceOver,
            1.0,
        )
    stack.unlockFocus()
    save(stack, "18-notify-all.png")


def main() -> int:
    print("exporting UI previews ->", OUT)
    export_bubbles()
    export_states_strip()
    export_rails()
    export_menubar()
    export_notifications()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
