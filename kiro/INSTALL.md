# 安装说明

macOS 专用。三步装完：

```bash
cd agent-activity/kiro                 # 本仓库中的 kiro 目录
./install.command                      # 等价于 ./scripts/install.sh
```

前置要求：macOS，Python 3.10 或更高（依赖 PyObjC 12 不支持 macOS 自带的 3.9，脚本会检测并给出安装方式）。

装完验证：

```bash
./scripts/verify.sh
```

退出码 0 且没有 `[FAIL]` 就算装好；`[WARN]` 是可选项缺失，不影响使用。

项目可以放在任意目录（建议 `~/Applications` 或家目录，不要放 `/tmp`），所有路径都会自动适配。

## 安装脚本做了什么

1. 挑选可用的 python3：优先 Homebrew 的 3.13 / 3.12 / 3.11，其次 PATH 中的 python3，最后系统自带的 `/usr/bin/python3`
2. 在项目目录下建立独立虚拟环境 `.venv`，不污染系统 Python
3. 安装唯一依赖 `pyobjc-framework-Cocoa`（固定版本）
4. 校验 Cocoa 可导入、全模块可编译
5. 按当前路径生成 launchd 登录自启配置并校验格式
6. 清理旧版本安装，启动桌宠

不需要 sudo，不修改系统设置。

## 参数

```bash
./scripts/install.sh                 # 安装并启动，配置登录自启
./scripts/install.sh --no-autostart  # 只安装，不启动、不配置自启
```

## 常用命令

```bash
./scripts/status.sh      # 运行状态与当前会话
./scripts/verify.sh      # 安装自检
./scripts/start.sh       # 启动 / 重启
./scripts/stop.sh        # 停止
./scripts/uninstall.sh   # 移除登录自启（保留设置和日志）
```

## 两个可选授权

- **点任务名跳转到会话**：需在「系统设置 → 隐私与安全性 → 辅助功能」允许项目目录下的 `.venv/bin/python`。未授权则降级为只激活 Kiro。
- **可点击的常驻通知**：`brew install terminal-notifier`。未安装则使用系统通知，无法点击跳转。

## 卸载

```bash
./scripts/uninstall.sh          # 停止并移除登录自启
rm -rf "<项目目录>"              # 删除程序本体
rm -rf ~/Library/Application\ Support/Kiro\ Desktop\ Pet   # 可选：清理设置与统计
rm -rf ~/Library/Logs/Kiro\ Desktop\ Pet                   # 可选：清理日志
```

功能说明见 `QUICKSTART.md`，完整文档见 `README.md`。
