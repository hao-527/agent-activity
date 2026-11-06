# Kiro Desktop Pet

一个原生 macOS 透明悬浮桌宠。它只在本机读取 Kiro 日志，将多个 AI 会话的运行状态实时转换为原创像素宠物逐帧动画，不修改 Kiro，也不上传日志。

## 已实现功能

### 状态展示
- PyObjC/Cocoa 原生透明无边框 `NSPanel`，浮在普通窗口上方，可跨桌面 Space / 全屏辅助显示
- 自适应状态气泡：卡片式列表，每行显示状态色点 + 真实任务名 + 已运行时长，行数随任务数增减，窗口按底部对齐伸缩，宠物本身不跳动
- 文本按实际宽度测量后截断，中文标题不会被裁掉半个字；超出条数显示「还有 N 个会话」
- 从 Kiro 本地状态库解析真实会话标题，兼容新版 `state.vscdb` 与旧版 `sessions.json`
- 按 `conversationId/sessionId` 聚合并行会话，显示运行数字角标
- 并行运行时某个会话完成/失败，会有局部庆祝或警示光点，不打断其他任务的运行动画
- 真实离线判定：检测 Kiro 进程是否在运行（日志文件残留不再让桌宠假装在工作）
- 三档尺寸（小/中/大）与深色/浅色/跟随系统外观
- 可插拔形象：内置手绘像素小狗，也可用一张宠物照片自动生成一套形象，菜单里随时切换
- 精灵帧位图缓存，待命和收起状态自动降帧

### 交互
- 拖动移动位置，位置跨重启持久化；拖动过程中靠近可吸附边缘会显示高亮预告
- 靠近屏幕左/右/下边缘松手自动吸附，收起为 36px 侧边栏；窗口同时缩到侧边栏大小并贴边，不会留下透明区域挡住点击
- 收起后仍是一个可读的状态条：迷你像素狗、随状态流动的脉冲光带、并行任务数角标、当前任务耗时
- 鼠标悬停侧边栏会滑出任务卡片，列出正在跑的任务与耗时，卡片里的任务名可直接点击跳转
- 任务完成、异常或取消时侧边栏会自动探头几秒展示结果，随后自动收回（可在菜单里关闭）
- 收起状态下可以沿边缘上下（或左右）拖动调整位置，不会被误拉回桌面中央，位置跨重启记忆
- 收起后单击展开，右键菜单照常可用
- 点击气泡里的任务名，直接跳到 Kiro 中对应的会话标签
- 单击宠物空白处展开/收起全部任务列表，悬停时临时展开
- 双击宠物打开 Kiro，右键打开完整控制菜单
- 可选全局快捷键 `⌥⌘P` 显示/隐藏桌宠（默认关闭，开启后需要系统「输入监控」权限）
- 外接显示器插拔或分辨率变化后自动回到可见区域

### 菜单栏
- 常驻状态项：Kiro 官方小恶灵标志 + 状态色圆点 + 运行任务数
- 圆点与 Claude / ChatGPT / DeepSeek Activity 统一为 8pt 底圈 + 6pt 实心点
- 颜色语义：紫=空闲，绿=运行/完成，黄=等待确认/取消，橙=异常，灰=离线
- 深色菜单栏自动显示白色小恶灵，浅色菜单栏自动转深色
- 菜单展示总览、Kiro 运行状态、今日统计和全部最近会话（点击即跳到该会话）
- 直接控制显示/隐藏、收起/展开、展开全部任务、通知开关、尺寸、外观、立即重扫
- 桌宠隐藏后菜单栏入口仍然可用

### 监控与统计
- 自动发现 Kiro 新窗口、新日志和后台会话
- 字节级增量读取，支持 UTF-8 半行、日志截断和 inode 轮转
- 严格校验 Kiro 日志来源组件，避免终端命令文本造成假会话
- 今日完成/异常/取消次数与累计工作时长，滚动保留 14 天
- 登录自动启动、进程异常退出自动恢复、单实例保护
- 与现有 `~/kiro-connection-notifier` 独立共存

## 宠物状态

| 状态 | 日志依据 | 动画表现 |
|---|---|---|
| 离线 | 未发现日志，或 Kiro 未运行且无近期活动 | 灰色睡眠、Z 动画 |
| 待命 | 有日志但无近期任务 | 呼吸、眨眼、摆尾 |
| 运行中 | `ACP session/prompt` / `Sending GenerateAssistantResponse` | 打字、屏幕光点、气泡活动点 |
| 多会话 | 同时有 2 个及以上会话运行 | 打字、彩色轨道光点、会话数字角标 |
| 等待确认 | `ToolApproval effect=ask` | 专注姿态 + 黄色确认提示 |
| 成功 | `[ACPEventAdapter] Execution succeeded` 显式执行边界 | 跳跃、笑脸、彩纸 |
| 错误 | `[ACPEventAdapter] Execution failed`（兼容旧错误事件） | 左右抖动、红色警告、叉眼 |
| 取消 | `[ACPEventAdapter] Execution aborted` / ACP cancel | 低落表情 |

> Kiro 的 `Execution began/succeeded` 日志只带 `executionId`，不带会话 ID，归属靠邻近日志推断。一旦结束事件缺失或归错会话，会话会一直显示「运行中」。为此桌宠会每 4 秒读一次 Kiro 自己的会话存档 `~/.kiro/sessions/<工作区>/<会话>/messages.jsonl` 尾部：最后一条是 `turn_end` 即判定该会话已结束并转为待命，是 `turn_start` 则保持运行中，所以长时间思考不会被误杀。另外「Kiro 进程退出」和「日志文件消失（重启或轮转）」也会让残留的运行中会话降级，`running_stale_timeout=5min` 只作最后兜底。

> 成功状态只由 Kiro 的 `[ACPEventAdapter] Execution succeeded` 显式事件触发。`Processing model response stream`、`Execution yielded` 和 `Execution resumed` 仅作为运行活动信号，不会触发完成；失败和取消分别使用 `Execution failed` 与 `Execution aborted`。并行运行时完成事件不会抢走 multi 状态，而是以局部光点提示。

## 操作

- **拖动宠物**：移动位置；靠近左/右/下边缘会先显示吸附预告，松手后收起为 36px 页签
- **点击任务名**：跳到 Kiro 里对应的会话标签，鼠标移上去会高亮并变成手型光标
- **单击宠物**：展开或收起全部任务列表
- **悬停宠物**：临时展开全部任务；悬停收起后的页签会多露出一截
- **单击侧边栏**：展开并恢复到对应边缘内侧，另一轴沿用收起前位置
- **拖动侧边栏**：沿当前边缘滑动调整位置，松手保持收起
- **悬停侧边栏**：滑出任务卡片；点卡片里的任务名跳到该会话，点其他区域再单击即展开
- **双击宠物**：打开或切回 Kiro
- **菜单栏 Kiro 小恶灵**：查看总览、今日统计与全部会话，控制显示/隐藏、收起/展开、展开全部任务、通知、尺寸、外观、重扫，打开 Kiro/日志或退出
- **右键宠物**：完整菜单，额外包含状态气泡、始终置顶、暂停监控、全局快捷键开关、发送测试通知、打开状态 JSON

从菜单正常退出后，launchd 不会立即把它重新拉起；下次登录仍会自动启动。也可以随时运行 `scripts/start.sh`。

## 源码住在哪里

这份代码的唯一改动源头是 Skill 目录 `~/.kiro/skills/kiro-desktop-pet/app/`，本目录（`~/kiro-desktop-pet`）是由 `install-pet.sh` 覆盖生成的**运行目录**，在这里改会被下次部署覆盖。改代码、部署和发版流程见 Skill 目录里的 `references/maintain.md`。

## 安装与分发

项目可以放在任意目录，所有路径都从脚本和模块自身位置推导。

```bash
# 首次安装：选 Python、建虚拟环境、装依赖、配置登录自启并启动
./scripts/install.sh

# 只安装不自启
./scripts/install.sh --no-autostart

```

分发靠 Skill：在 Skill 目录执行 `./scripts/package-skill.sh` 生成打包目录，装上 Skill 后说一句「安装 Kiro 桌宠」即可。只拿到本目录、没有 Skill 时，按 `AGENTS.md` 的降级流程安装。

安装要求：macOS，**Python 3.10 或更高**（依赖 PyObjC 12 只提供 3.10+ 的包，macOS 自带的 3.9 用不了，`install.sh` 会检测并给出安装指引）。

面向人的说明见 `QUICKSTART.md` 与 `INSTALL.md`，安装自检用 `./scripts/verify.sh`。

## 常用命令

```bash
./scripts/status.sh      # 查看服务、进程和当前会话状态
./scripts/verify.sh      # 安装自检，输出 PASS/WARN/FAIL
./scripts/start.sh       # 启动或重启
./scripts/stop.sh        # 停止并从当前 launchd 会话卸载
./scripts/install.sh     # 重新安装依赖与登录自启配置
./scripts/uninstall.sh   # 移除登录自启（保留项目、设置和日志）
```

## 动画演示

演示前先停止正式桌宠，避免单实例锁冲突：

```bash
./scripts/stop.sh
./scripts/demo.sh multi 12
./scripts/start.sh
```

可选状态：`offline`、`idle`、`running`、`multi`、`success`、`error`、`cancelled`。

## 安装和运行位置

| 内容 | 路径 |
|---|---|
| 项目 | 任意目录，示例 `~/kiro-desktop-pet` |
| Python 虚拟环境 | 安装目录下的 `.venv` |
| 登录自启配置 | `~/Library/LaunchAgents/com.kiro-desktop-pet.plist`（安装时按实际目录生成） |
| 用户设置 | `~/Library/Application Support/Kiro Desktop Pet/settings.json` |
| 当前聚合状态 | `~/Library/Application Support/Kiro Desktop Pet/status.json` |
| 今日/历史统计 | `~/Library/Application Support/Kiro Desktop Pet/stats.json` |
| 形象包 | `~/Library/Application Support/Kiro Desktop Pet/pets/<id>/` |
| 通知点击的跳转请求 | `~/Library/Application Support/Kiro Desktop Pet/jump-request.json` |
| 应用日志 | `~/Library/Logs/Kiro Desktop Pet/pet.log` |
| launchd 输出 | `~/Library/Logs/Kiro Desktop Pet/launchd.out.log` / `launchd.err.log` |

依赖固定为：

```text
pyobjc-framework-Cocoa==12.2.1
```

依赖只安装在项目 `.venv`，不会污染系统 Python。

## 项目结构

```text
kiro-desktop-pet/
├── app.py                         # 应用入口、单实例、演示状态
├── requirements.txt
├── VERSION
├── AGENTS.md                       # 给 AI 助手的安装执行指令
├── INSTALL.md                      # 安装说明与卸载步骤
├── QUICKSTART.md                   # 三步上手说明
├── kiro_pet/
│   ├── config.py                  # 路径、参数、设置、日志
│   ├── events.py                  # 严格日志事件分类
│   ├── keys.py                    # 只向单个进程投递按键的 CoreGraphics 封装
│   ├── session_jump.py            # 定位并跳转到指定 Kiro 会话标签
│   ├── skins.py                   # 可插拔形象包的发现与加载
│   ├── layout.py                  # 尺寸档位、全部绘制矩形与吸附几何
│   ├── monitor.py                 # 多文件增量 tail、标题刷新、统计与长任务提醒
│   ├── notify.py                  # 通知分级、持续强提醒、勿扰时段
│   ├── presence.py                # Kiro 进程存活检测
│   ├── render.py                  # 气泡/精灵/页签绘制与帧位图缓存
│   ├── session_activity.py        # 读会话存档 turn_start/turn_end 校正运行状态
│   ├── session_titles.py          # 只读解析 Kiro 新旧会话标题存储
│   ├── sprites.py                 # 原创像素帧生成
│   ├── state.py                   # 多会话状态机与 JSON 发布
│   ├── stats.py                   # 每日完成/异常/取消与工作时长
│   ├── textkit.py                 # 字体、文本测量与中文安全截断
│   ├── theme.py                   # 深浅主题与状态配色
│   └── ui.py                      # Cocoa 窗口、交互与菜单栏
├── launchd/
│   └── com.kiro-desktop-pet.plist.template
└── scripts/
    ├── common.sh                   # 共享标签与路径推导
    ├── verify.sh                   # 安装自检
    ├── check_status_fresh.py
    ├── install.sh
    ├── start.sh
    ├── stop.sh
    ├── status.sh
    ├── print_status.py
    ├── demo.sh
    ├── request-jump.sh
    ├── export_sprite_preview.py
    ├── export_ui_preview.py        # 导出文档用的界面预览图
    ├── make_photo_pet.py           # 一张照片生成一套形象包
    └── uninstall.sh
```

## 关键参数

位于 `kiro_pet/config.py` 的 `AppConfig`：

- `poll_interval=0.65`：增量读取周期
- `rescan_interval=5`：发现新 Kiro 窗口的周期
- `bootstrap_max_age=30min`：启动时回放近期日志以恢复现状
- `success_hold=28s` / `error_hold=180s` / `cancelled_hold=25s`：完成态保持时间
- `flash_hold=7s`：并行运行时局部庆祝/警示光点的持续时间
- `running_stale_timeout=5min`：兜底，未被会话存档覆盖时避免永久显示运行中
- `activity_probe_interval=4s`：读会话存档校正运行状态的周期
- `activity_confirm_delay=20s`：存档证据比日志旧时，需日志静默这么久才降级，避免误杀长思考
- `animation_interval=0.14s` / `idle_animation_interval=0.26s` / `docked_animation_interval=0.6s`：分状态帧率
- `compact_rows=3` / `detail_rows=8`：气泡默认与展开后的最大行数
- `collapsed_rows=3`：收起后任务卡片显示的最大行数
- `edge_tab_visible=36px`：收起后常驻侧边栏的厚度（随尺寸档位缩放）；收起时窗口会缩到侧边栏大小并贴住屏幕边缘，不遮挡下方内容
- `auto_peek_seconds=4.5`：自动探头停留时间
- `title_rescan_interval=3s`：本地会话标题刷新周期
- `presence_refresh_interval=2.5s`：Kiro 进程存活检测周期
- `edge_snap_distance=30px`：触发吸附的边缘距离阈值
- `status_refresh_interval=0.7s`：菜单栏状态刷新周期
- `jump_direct_keys=True`：跳转按键只投递给 Kiro 进程，避免被输入法等全局监听捕获
- `jump_global_fallback=True`：直投无效时允许改用系统级按键重试
- `stats_flush_interval=30s`：统计落盘周期
- `long_run_threshold=15min`：单个任务运行多久后提醒一次

用户设置存于 `settings.json`：`x`/`y`、`always_on_top`、`show_bubble`、`monitor_paused`、`notifications_enabled`、`pet_visible`、`docked_edge`、`dock_offset`、`auto_peek`、`pet_scale`、`skin`、`detail_expanded`、`hotkey_enabled`、`appearance`。

修改后执行：

```bash
./scripts/start.sh
```

## 点击任务跳转会话

气泡里的任务行、菜单里的会话行，以及桌宠发出的 macOS 通知，点击后都会切到 Kiro 中对应的那个聊天标签。

实现方式（Kiro 没有会话级 deep link，`kiro://` 只处理登录回调，`kiroAgent.viewSession` 也无法从外部调用）：

1. 从 `state.vscdb` 读出该会话所属工作区、聊天标签顺序（`sessionPanels.entries`）和当前标签（`sessionPanels.focused`）
2. 用 Kiro CLI 或 `open -b` 把承载这个工作区的窗口调到前台（已打开的窗口会被复用，不会新开）
3. 计算目标标签与当前标签的距离，发送 `⌘L` 聚焦聊天，再按次数发送 Kiro 自带的 `⌘⌥→` / `⌘⌥←` 切换标签；这些按键通过 `CGEventPostToPid` **只投递给 Kiro 进程**，不走系统级广播
4. 回读 `sessionPanels.focused` 确认；没命中就按最新状态重试一次

为什么要直投进程：系统级按键（osascript / System Events）会被所有全局事件监听看到，而输入法的语音快捷键正是用这种监听实现的。豆包输入法把 `⌘⌥` 这类修饰键组合注册成语音触发，所以早期版本每次跳转都会顺带唤起语音输入。改成只投给 Kiro 的进程后，其他监听者收不到这些按键。

降级行为：
- 目标已经是当前标签时，只激活 Kiro，不发送任何按键
- 本地状态库里找不到该标签，或标签开在编辑器区而非侧边栏时，只激活 Kiro 并在日志里说明
- 只有在**完全无法直投**时（CoreGraphics 不可用或找不到 Kiro 进程）才会改用系统级按键；直投已发出但持久化状态没确认时不会再补发全局按键，因此不会二次触发输入法语音。想彻底禁用降级可把 `jump_global_fallback` 设为 `False`
- 走位失败或权限不足时，只激活 Kiro，桌宠状态展示不受影响

第一次点击时 macOS 会请求权限。需要在 **系统设置 > 隐私与安全性 > 辅助功能** 里允许桌宠使用的 Python 解释器（`~/kiro-desktop-pet/.venv/bin/python`），并在 **自动化** 中允许它控制 Kiro 与「系统事件」。未授权时功能自动降级为激活 Kiro，日志里会给出提示。

跳转过程在后台线程执行，不会卡住动画；每次点击的结果都会写入 `pet.log`。

点击通知的链路稍有不同：通知用 `terminal-notifier -execute` 调用 `scripts/request-jump.sh`，脚本只是原子写入一个请求文件 `jump-request.json`，再由桌宠进程在 0.7 秒内读取并执行跳转。这样做是为了让辅助功能权限只需授给桌宠的 Python 解释器，不必再为 `terminal-notifier` 单独授权一次。请求带时间戳，超过 5 分钟的旧请求会被丢弃；桌宠没在运行时，脚本退化为直接激活 Kiro。少数拿不到会话 ID 的事件（例如只能定位到某个日志窗口的异常）仍然只是激活 Kiro。

## 自定义形象

内置形象是手绘像素小狗（`kiro_pet/sprites.py`，22×21 网格 62 帧）。此外可以用一张宠物照片自动生成一套形象：

```bash
./.venv/bin/python scripts/make_photo_pet.py --photo ~/Desktop/dog.jpg --name 我家狗
```

生成流程全部本地完成，依赖 macOS 自带框架：

1. Vision 前景实例蒙版抠出主体，并按暖色/冷色判据清掉背景残留
2. Vision 动物姿态识别拿到 24 个关节点（双眼、鼻子、耳朵三点、四爪、尾巴），用于定位分层与清理区域
3. 以整体仿射变换生成 6 种状态共 54 帧：呼吸、弹跳、跳跃挤压拉伸、抖动、垂头、压扁蜷卧
4. 写出皮肤包 `~/Library/Application Support/Kiro Desktop Pet/pets/<id>/`，含 `skin.json` 与 `frames/<state>/NN.png`

菜单里「更换形象」会扫描该目录，列出所有合法皮肤包；`multi` 状态自动复用 `running` 帧。删除目录即可移除形象。

照片形象的限制：**没有表情变化**（照片无法伪造眨眼与情绪）、**没有局部动作**（摇尾、单独抖耳会在位移时撕裂轮廓），这两项只有手绘像素风能做。

皮肤包格式是开放的，任何生成器只要写出同样的 `skin.json`（`states` 声明每个状态的帧数、`cell` 声明画布尺寸）和逐帧 PNG 就能被加载。

## 通知提醒

除了桌面上的像素动画，桌宠还会在关键节点发送原生 macOS 通知（优先使用 `terminal-notifier`，找不到时回退 `osascript`）。菜单里可用「通知提醒」开关整体开启或关闭，用「发送测试通知」快速验证效果。

| 类别 | 触发来源 | 默认声音 | 默认开关 |
|---|---|---|---|
| 成功 | `[ACPEventAdapter] Execution succeeded` | Glass | 开 |
| 异常 | `Execution failed` / `Completed with error`（非中断） | Basso | 开 |
| 中断 | `Completed with error` 且含 `connection was interrupted` | Sosumi | 开 |
| 取消 | `Execution aborted` / `Completed with abort` | Pop | 关 |
| 长任务 | 单个执行持续超过 `long_run_threshold` | Tink | 开 |
| 授权 | 无法从日志检测，仅用于手动测试 | Funk | 手动 |

- **点击通知跳到该会话**：完成、异常、中断、取消和长任务通知都带上触发它的会话，点一下直接切到那个聊天标签，详见上一节
- **连接中断是 CRITICAL 持续提醒**：检测到连接中断后，会按 `notify_repeat_interval` 周期重复提醒，直到你切回 Kiro 前台（自动停止）或到达 `notify_max_repeats` 上限；停止后有一段 `notify_rearm` 冷却期。
- **长任务只提醒一次**：同一次执行只提示一次，Kiro 在前台时不打扰。
- **勿扰时段**：把 `notify_quiet_start` / `notify_quiet_end` 设为小时数（支持跨夜，如 22 → 8）即可静音；连接中断属于例外，仍会提醒。
- **防回放（freshness）**：启动回放历史日志或新开 Kiro 窗口重放旧日志都不会误报，超过 `notify_max_age`（默认 90 秒）的事件会被忽略；统计同样只统计实时事件。
- **去抖**：同一会话同一类别在 `notify_debounce` 窗口内只发一条。
- **授权/待批准**：Autopilot 模式的敏感操作不会写入 exthost 日志，仍由你已有的 PreToolUse 钩子负责通知。

如果希望通知常驻、不自动消失，请在 **系统设置 > 通知 > terminal-notifier** 里把提醒样式设为「提醒(Alerts)」。

## 与异常常驻通知的关系

桌宠负责持续展示状态；原来的 `~/kiro-connection-notifier/watch.py` 继续负责 macOS 系统异常通知。两者独立读取日志，不共享进程和状态文件：

- 桌宠：视觉状态、多会话、交互、统计
- notifier：连接中断和持续系统通知

## 隐私与网络

运行时只读以下本地数据：

```text
~/Library/Application Support/Kiro/logs/*/window*/exthost/kiro.kiroAgent/Kiro Logs.log
~/Library/Application Support/Kiro/User/workspaceStorage/*/state.vscdb
~/Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent/workspace-sessions/*/sessions.json
```

`state.vscdb` / `sessions.json` 仅用于读取会话 ID、标题、聊天标签顺序和工作区路径，SQLite 以只读模式打开。进程存活检测只查询本机运行的应用列表。桌宠不会修改 Kiro 数据，不会上传日志、标题、会话内容或项目代码，也不发起网络请求。只有执行 `install.sh` 安装固定 PyObjC 依赖时会访问 Python 包源。

## 故障排查

```bash
# 看当前状态
./scripts/status.sh

# 看最近运行日志
tail -50 ~/Library/Logs/'Kiro Desktop Pet'/pet.log

# 检查 launchd
launchctl print gui/$(id -u)/com.kiro-desktop-pet

# 重装并重启
./scripts/install.sh
```

若宠物不可见，先从菜单栏 Kiro 小恶灵选择「显示桌宠」——「隐藏桌宠」会一直保留到下次手动显示，重启和重新登录都不会自动恢复；隐藏时会弹一条提示通知，菜单栏第三行与图标悬浮提示也会写明「桌宠已隐藏」。若处于边缘收起状态可选择「展开桌宠」或单击侧边栏。位置异常时可停止桌宠后删除 `settings.json` 中的 `x`/`y` 与 `docked_edge` 再启动，程序会回到主屏幕右下区域（外接屏拔插后保存的坐标若已不在任何屏幕上，启动时会自动纠正并写回设置，`pet.log` 有记录）。手改 `settings.json` 前务必先 `./scripts/stop.sh`，否则运行中的桌宠退出时会把旧设置写回覆盖。全局快捷键不生效时，请在 **系统设置 > 隐私与安全性 > 输入监控** 中授权当前 Python 解释器，或改用菜单栏控制。跳转时如果被输入法的语音功能打断，说明走了系统级按键的降级分支，`pet.log` 里会有「改用系统级按键」记录，把 `jump_global_fallback` 设为 `False` 即可只用直投。点击任务名没有切换会话时，先看 `pet.log`：提示权限问题就去 **辅助功能** 与 **自动化** 里授权；提示找不到标签则说明该会话已经不在 Kiro 的标签栏里。
