# Claude Activity

macOS 菜单栏里的 `CC` 标记与状态圆点。双击 `Claude Activity.app` 启动，点击图标可以查看每个正在运行的会话、进行中的状态或退出。没有通知、声音或 Dock 图标。已配置登录自启。

## 菜单栏显示

菜单栏里只有两样东西：**一个数字**和**一个圆点**，左边是 `CC` 标记。任何时候都不会出现文字以外的内容。

- **没有会话**：数字隐藏，只剩 `CC` 标记和紫色圆点。
- **有会话但没有对话**：数字依然隐藏，圆点紫色。开着但不干活的会话不计入数字。
- **正在对话**：数字是**正在对话**的会话数（`1`、`2`、`3`…），圆点转绿；对话数变化时脉冲 4 秒，所以对话结束也能看见一下变化。
- 圆点核心静止时直径 6pt，脉冲时外圈光晕放大到 9pt（核心仍是 6pt），位置固定在右下角 (20.4, 5)。

数字只算正在对话的会话，不是进程数。一个会话挂在那里几小时没动，进程还活着，但没有任务在跑，就不该让菜单栏显示数字——这正是之前显示 `2` 而两边都没在干活的原因。总进程数放在悬停提示和菜单顶部（`1 个正在对话（共 2 个会话）`）。

只要有一个会话处于 `busy` / `shell` / `waiting` 就算在对话。`idle` 只是进程还活着，不算对话。

「几个会话在对话」这类文字只出现在悬停提示和下拉菜单顶部，不进菜单栏。

读不到注册表时圆点变橙，数字隐藏。

### 尺寸与位置

画布 23.5×22pt：`CC` 的布局框为 `x 0.5…15.5`，彩点核心位于 `x 17.4…23.4`。**两者的中线不同**——`CC` 居画布中线 y=11，彩点保持低位置 y=5。

| 元素 | 8× 渲染可见范围 | 代码几何尺寸 |
|---|---|---|
| `CC` 墨迹 | x 0.4…15.4，y 6.9…15.0 | 约 15 × 8.1pt，中心 y ≈ 10.9 |
| 彩点核心 | x 17.4…23.3，y 2.0…7.9 | 矩形 `(17.4, 2, 6×6)`，圆心 (20.4, 5)，直径 6pt |
| 彩点光晕（静止） | x 16.4…23.4，y 1.0…8.9 | 矩形 `(16.4, 1, 8×8)`，直径 8pt |
| 彩点光晕（脉冲） | x 15.9…23.4，y 0.5…9.4 | 矩形 `(15.9, 0.5, 9×9)`，直径 9pt |

上表范围是 8× 渲染后逐像素量出的抗锯齿边缘。光晕使用菜单栏背景色，超出画布右缘的部分无需显示；彩色核心完整位于画布内。脉冲光晕左缘 x=15.9，`CC` 右缘 x=15.4，中间仍有约 0.5pt，不会遮到字形。

彩点保持核心 6pt、光晕 8pt、脉冲 9pt，只把共同圆心从 (21, 5) 左移到 (20.4, 5)，以压缩横向留白；字体、字号、字重和字距均未改变。

光晕用 `windowBackgroundColor` 画，作用是**把标记从彩点周围挖开**。现在 `CC` 最右到 15.4，脉冲光晕从 15.9 开始，两者不会相碰；光晕继续保留，视觉样式不变。

`CC` 用系统字体的圆体（`.rounded`）11.5pt Bold，字距 `-0.6`。定位不靠字体的行框，而是用 CoreText 的 `CTLineGetBoundsWithOptions(.useGlyphPathBounds)`
取真实字形轮廓的包围盒，再把轮廓中心对到中线：

```swift
context.textPosition = CGPoint(x: box.midX - ink.midX, y: midline - ink.midY)
```

这一步是必要的：`CC` 没有降部，行框（含 descender 空白）居中会让墨迹看起来明显偏上。按轮廓居中不需要任何经验补偿值，换字号、换字体都稳。

字距 `-0.6` 是实测结果。默认字距在这个尺寸下宽到像两个词；再紧（-1.15）两个 `C` 的碗几乎相接，1× 下看着粘连。-0.6 是两个字母仍分明、又读成一个标记的那个点，在 1× 与 2× 下都看过。

标记本身不随状态变化——只有彩点换颜色和大小。这样菜单栏里变化的是「有没有事」，而不是图标本身在动。

想看效果，直接渲染对比图（不启动应用）：

```sh
'Claude Activity.app/Contents/MacOS/ClaudeActivity' --render --both --out /tmp/marks.png --scale 8
open /tmp/marks.png
```

不带 `--both` 只画当前标记；`--mark burst` 可以切回旧的八射线标记本体运行。`--render` 的图里每格画了两条虚线：红色 y=11 是 `CC` 的中线，蓝色 y=5 是彩点的圆心，用来分别检查两者是否在自己的位置上。

## 数据来源

每 2 秒只读 `~/.claude/sessions`（或 `$CLAUDE_CONFIG_DIR/sessions`）里的 `<pid>.json`。这是 Claude Code 自己发布的会话注册表，字段包括 `pid`、`sessionId`、`cwd`、`name`、`status`、`updatedAt`。会话是否存在由进程决定：用 `kill(pid, 0)` 判断，进程没了就不算。

状态取自注册表的 `status` 字段，官方取值是 `busy` / `shell` / `idle` / `waiting`。

同目录下的 `<pid>.<64位hex>.key` 是 IPC 密钥文件，按文件名不是纯数字直接跳过，不会被读取。不读取 transcript、不读取凭据、不修改任何 Claude 设置、不发送任何数据。

## 局限

这是本机活动指示器，不是任务健康保证。

- 只覆盖当前用户本机的会话，看不到其他机器或云端会话。
- 注册表格式属于 Claude Code 内部实现，升级后可能需要调整。
- 会话进程被强杀时注册表文件会残留，但进程判活会把它过滤掉。

## 构建与启动

需要 macOS 和 Xcode Command Line Tools（提供 Swift 编译器）。

```sh
./build.command
open 'Claude Activity.app'
```

`build.command` 只编译、跑自检、生成应用包并做本地 ad-hoc 签名。安装（拷到 `~/Applications`、写登录自启、启动）用 `./install.command`；重复执行会先停掉旧实例再重装，改完代码重跑一次就生效。

`LaunchAgent.plist` 是模板，安装时把 `__HOME__` 替换成当前用户目录后写入 `~/Library/LaunchAgents/`，所以仓库里不含任何与本机路径绑定的内容。

## 登录自启

`~/Library/LaunchAgents/local.claude.activity.plist` 通过 launchd 在登录时启动，与 Codex Activity 用的是同一套方式（`LimitLoadToSessionType=Aqua`、`ProcessType=Interactive`、`RunAtLoad=true`）。

手动管理：

```sh
launchctl print  "gui/$(id -u)/local.claude.activity"   # 查看状态
launchctl kickstart -k "gui/$(id -u)/local.claude.activity"  # 重启
launchctl bootout "gui/$(id -u)/local.claude.activity"  # 停用自启
```

没有设 `KeepAlive`：菜单里手动退出后不会被立刻拉起来，下次登录才回来。这与 Codex Activity 的行为一致。

## 源码与验证

`main.swift` 是完整源码，只依赖 AppKit、CoreText 与 Darwin，没有第三方库。`build.command` 重建并签名应用。

可执行文件支持四个参数：

- `--self-test`：单元验证空闲会话不入数字、对话才计数并转绿、对话结束归零回落。
- `--check`：读取真实注册表并输出当前状态，读不到时退出码为 1。
- `--render [--out 文件] [--scale 倍数] [--both]`：把五种状态渲染成一张 PNG，不启动应用。
- `--mark cc|burst`：选标记，默认 `cc`；`burst` 是上一版八射线标记，只为对比保留。

用夹具验证时可以用 `CLAUDE_CONFIG_DIR` 指向临时目录，避免动到真实注册表：

```sh
T=$(mktemp -d); mkdir -p "$T/sessions"
# 写入 <pid>.json 夹具…
CLAUDE_CONFIG_DIR="$T" 'Claude Activity.app/Contents/MacOS/ClaudeActivity' --check
```

单实例由 `flock` 保证（`$TMPDIR/local.claude.activity.lock`）。launchd 直接执行 Mach-O，进程可能没有 bundle identifier，`NSRunningApplication` 查不到，所以不能用它做守卫。
