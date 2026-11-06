# agent-activity

三个 AI 编码终端的 macOS 菜单栏活动指示器，一个仓库按端分包：

| 目录 | 终端 | 应用 | 自启 Label | 数据源 |
|---|---|---|---|---|
| [`claude/`](claude/) | Claude Code | `Claude Activity.app` | `local.claude.activity` | `~/.claude/sessions/<pid>.json` |
| [`codex/`](codex/) | ChatGPT 桌面 / Codex CLI | `Codex Activity.app` | `local.codex.activity` | `~/.codex/sessions/**`、`state_*.sqlite` |
| [`deepseek/`](deepseek/) | DeepSeek Harness | `DeepSeek Harness Activity.app` | `local.deepseek.harness.activity` | `~/.dsh/storages/session_projcache/sessions/*.json` |

每个包都是独立的 Swift 工程：单文件 `main.swift`、只依赖 AppKit（Claude 额外用 CoreText），编译出各自独立的 `.app`。三个包互不依赖，可以只装其中一个。

三者行为一致：无 Dock 图标、无通知、无声音，只读本机会话状态，不修改被监视的应用、不读凭据、不发送数据。

## 状态语义

通用约定：**数字 = 正在工作或等待确认的会话数**，空闲时隐藏数字；圆点/状态灯表示聚合状态。

| 端 | 绿 | 黄 | 紫 | 其它 |
|---|---|---|---|---|
| Claude | 至少一个会话正在对话 | — | 没有对话中的会话 | 橙：读不到注册表 |
| Codex | 有未结束任务且 120 秒内有记录 | 有未结束任务但 120 秒无新记录 | 没有进行中的任务 | 黄 + 提示：记录目录不可读 |
| DeepSeek | 正在生成/执行工具/跑任务 | 正在等待用户确认 | Harness 在跑但全部空闲 | 灰：Harness 未运行；橙：读不到缓存 |

各端的判定细节、菜单行为、局限见各自目录下的 README。

## 快速开始

要求 macOS + Xcode Command Line Tools（提供 `swiftc`）。

```sh
git clone https://github.com/hao-527/agent-activity.git
cd agent-activity
./build-all.command          # 只编译三个应用，不安装
```

按需安装（编译 + 拷到 `~/Applications` + 写登录自启项 + 启动）：

```sh
cd claude   && ./install.command
cd codex    && ./install.command
cd deepseek && ./install.command
```

只重编不安装：`cd <端> && ./build.command`。

## 安装位置与卸载

- 应用：`~/Applications/<App>.app`
- 自启：`~/Library/LaunchAgents/local.<端>.activity.plist`
- 日志：`~/Library/Logs/<App>.log`、`<App>.error.log`

卸载某一端：

```sh
launchctl bootout "gui/$(id -u)/local.claude.activity"
rm -rf "$HOME/Applications/Claude Activity.app"
rm -f "$HOME/Library/LaunchAgents/local.claude.activity.plist"
```

（`codex` / `deepseek` 换成对应 Label 与应用名即可。）

## 使用与调试

- 菜单里可以查看当前会话、直接打开对应终端，或单独退出 Activity；退出 Activity 不影响终端本身。
- 三个可执行文件都支持 `--self-test`（状态机自检）和 `--check`（读取真实数据并打印状态）。
- Claude 与 DeepSeek 还支持 `--render --out <png>`，把各状态渲染成图片，不需要启动应用。

## 仓库说明

- 前身是 `codex-activity`（只有 Codex 一端）。重命名并拆分后，GitHub 上旧链接会自动跳转到本仓库。
- Kiro 暂未纳入：它的本地指示器是独立仓库 [kiro-desktop-pet](https://github.com/hao-527/kiro-desktop-pet)，形态是桌面宠物（Python/PyObjC），不是菜单栏 Activity。
- `.app` 等编译产物不入库，由各目录的 `build.command` 现场生成。

## 免责

这是本机活动指示器，不是任务健康保证。只能覆盖当前用户本机的会话存档，看不到其他机器或纯云端的任务；会话记录格式属于各终端内部实现，终端升级后可能需要适配。
