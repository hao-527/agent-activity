# agent-activity

四个 AI 编码终端的本地活动指示器，一个仓库按端分包：

| 目录 | 终端 | 形态 | 应用 / 进程 | 自启 Label | 数据源 |
|---|---|---|---|---|---|
| [`claude/`](claude/) | Claude Code | 菜单栏（Swift） | `Claude Activity.app` | `local.claude.activity` | `~/.claude/sessions/<pid>.json` |
| [`codex/`](codex/) | ChatGPT 桌面 / Codex CLI | 菜单栏（Swift） | `Codex Activity.app` | `local.codex.activity` | `~/.codex/sessions/**`、`state_*.sqlite` |
| [`deepseek/`](deepseek/) | DeepSeek Harness | 菜单栏（Swift） | `DeepSeek Harness Activity.app` | `local.deepseek.harness.activity` | `~/.dsh/storages/session_projcache/sessions/*.json` |
| [`kiro/`](kiro/) | Kiro | 桌面桌宠（Python） | `Kiro Desktop Pet` | `com.kiro-desktop-pet` | `~/.kiro/sessions/**`、`state.vscdb`、Kiro 日志 |

前三端是独立的 Swift 单文件工程（只依赖 AppKit，Claude 额外用 CoreText），编译出各自的 `.app`，互不依赖，可以只装其中一个。

`kiro/` 形态不同：它是 PyObjC 写的透明悬浮桌宠，用像素小狗显示每个 Kiro 会话在跑什么、跑了多久、成功还是报错。它自带 `scripts/` 安装/卸载/自检脚本，首次安装需要 Python 3.10+ 和 pip 源。

四者行为一致：无 Dock 图标、无通知打扰（Kiro 有可关闭的完成/异常通知）、只读本机会话状态，不修改被监视的应用、不读凭据、不发送数据。

## 状态语义

菜单栏三端的通用约定：**数字 = 正在工作或等待确认的会话数**，空闲时隐藏数字；圆点/状态灯表示聚合状态。

| 端 | 绿 | 黄 | 紫 | 其它 |
|---|---|---|---|---|
| Claude | 至少一个会话正在对话 | — | 没有对话中的会话 | 橙：读不到注册表 |
| Codex | 有未结束任务且 120 秒内有记录 | 有未结束任务但 120 秒无新记录 | 没有进行中的任务 | 黄 + 提示：记录目录不可读 |
| DeepSeek | 正在生成/执行工具/跑任务 | 正在等待用户确认 | Harness 在跑但全部空闲 | 灰：Harness 未运行；橙：读不到缓存 |

Kiro 桌宠按会话逐条展示，状态包括：离线、待命、运行中、多会话并行、等待批准、成功、错误、取消，每种有独立动画与配色，详见 [kiro/README.md](kiro/README.md)。

## 快速开始

要求 macOS + Xcode Command Line Tools（提供 `swiftc`）。

```sh
git clone https://github.com/hao-527/agent-activity.git
cd agent-activity
./build-all.command          # 只编译 claude / codex / deepseek，不安装
```

按需安装（编译 + 拷到 `~/Applications` + 写登录自启项 + 启动）：

```sh
cd claude   && ./install.command
cd codex    && ./install.command
cd deepseek && ./install.command
```

Kiro 桌宠：

```sh
cd kiro && ./install.command     # 建 venv、装 PyObjC、写自启、启动
cd kiro && ./scripts/verify.sh   # 自检，退出码 0 且无 [FAIL] 即成功
```

只重编不安装：`cd <端> && ./build.command`。

## 安装位置与卸载

| 端 | 应用位置 | 自启文件 | 日志 |
|---|---|---|---|
| claude / codex / deepseek | `~/Applications/<App>.app` | `~/Library/LaunchAgents/local.<端>.activity.plist` | `~/Library/Logs/<App>.log` |
| kiro | 仓库内 `kiro/.venv`（就地运行） | `~/Library/LaunchAgents/com.kiro-desktop-pet.plist` | `~/Library/Logs/Kiro Desktop Pet/` |

菜单栏端的卸载：

```sh
launchctl bootout "gui/$(id -u)/local.claude.activity"
rm -rf "$HOME/Applications/Claude Activity.app"
rm -f "$HOME/Library/LaunchAgents/local.claude.activity.plist"
```

（`codex` / `deepseek` 换成对应 Label 与应用名即可。）Kiro 用 `kiro/scripts/uninstall.sh`。

## 使用与调试

- 菜单里可以查看当前会话、直接打开对应终端，或单独退出指示器；退出指示器不影响终端本身。
- 三个 Swift 可执行文件都支持 `--self-test`（状态机自检）和 `--check`（读取真实数据并打印状态）。
- Claude 与 DeepSeek 还支持 `--render --out <png>`，把各状态渲染成图片，不需要启动应用。
- Kiro 桌宠的调试见 [kiro/QUICKSTART.md](kiro/QUICKSTART.md) 与 `kiro/scripts/`。

## 仓库说明

- 前身是 `codex-activity`（只有 Codex 一端）。重命名并拆分后，GitHub 上旧链接会自动跳转到本仓库。
- `kiro/` 收录的是本机实际运行版本（1.7.1，含 `waiting` 状态与 `status_icon`）。原独立仓库 `hao-527/kiro-desktop-pet` 已转为私有、仅作归档，后续唯一的源码入口是本仓库的 `kiro/`。
- 编译产物（`*.app`）、Python 虚拟环境（`.venv/`）、`__pycache__/` 均不入库。

## 免责

这是本机活动指示器，不是任务健康保证。只能覆盖当前用户本机的会话存档，看不到其他机器或纯云端的任务；会话记录格式属于各终端内部实现，终端升级后可能需要适配。
