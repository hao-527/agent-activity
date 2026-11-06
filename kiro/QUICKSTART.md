# Kiro 桌宠 · 快速开始

macOS 专用。把 Kiro 的运行状态变成桌面上的像素小狗：谁在跑、跑了多久、成功还是报错，一眼可见。

## 安装（约一分钟）

在 Kiro 里说一句「安装 Kiro 桌宠」，Skill 会自动装好。想手动装：

```bash
cd ~/.kiro/skills/kiro-desktop-pet
./scripts/install-pet.sh
```

只拿到源码目录、没有 Skill 时：

```bash
cd <源码目录>
./scripts/install.sh
```

需要 macOS 与 Python 3.10+（macOS 自带的 3.9 不行，脚本会提示怎么装）。

脚本会自己完成：挑选可用的 python3 → 建立独立虚拟环境 → 安装唯一依赖 PyObjC → 校验 Cocoa 可用 → 生成登录自启配置 → 启动桌宠。放在哪个目录都行，不必是家目录。

装完右下角就会出现小狗，顶部菜单栏出现小狗头图标。

## 常用命令

```bash
./scripts/status.sh      # 查看运行状态与当前会话
./scripts/start.sh       # 启动 / 重启
./scripts/stop.sh        # 停止
./scripts/uninstall.sh   # 移除登录自启（保留设置和日志）
./scripts/demo.sh multi  # 动画演示，需先 stop
```

## 怎么用

| 操作 | 效果 |
| --- | --- |
| 拖动小狗 | 移动位置；拖到左/右/下边缘松手自动缩成侧边栏 |
| 单击小狗 | 展开 / 收起全部任务列表 |
| 点任务名 | 跳到 Kiro 里对应的会话 |
| 双击小狗 | 打开或切回 Kiro |
| 右键小狗 | 完整菜单：尺寸、外观、通知、暂停监控等 |
| 悬停侧边栏 | 滑出任务卡片；单击展开回桌面 |
| 菜单栏 Kiro 小恶灵 | 总览、今日统计、全部会话（可点击跳转）、显示 / 隐藏桌宠 |

## 换成自己宠物的照片

```bash
./.venv/bin/python scripts/make_photo_pet.py --photo ~/Desktop/mycat.jpg --name 我家猫
```

十几秒后，菜单栏 Kiro 小恶灵 → 更换形象 → 选「我家猫」。想换回来就选「像素小狗」。

照片选正面、四肢可见、主体占画面一半以上的那种。照片形象没有表情变化和局部动作（摇尾巴之类），动作是整体的呼吸、弹跳、跳跃；要表情就用内置的像素小狗。

全程在本机跑，照片不上传。

## 两个可选增强

**可点击的常驻通知**

```bash
brew install terminal-notifier
```

没装也能用，会退回系统的 osascript 通知，只是不能点击跳转。装了之后建议在 系统设置 > 通知 > terminal-notifier 里把样式设为「提醒」，通知就不会自动消失。

**点击跳转到指定会话**

第一次点任务名时 macOS 会弹权限请求，需要在 系统设置 > 隐私与安全性 > 辅助功能 里允许桌宠的 Python 解释器（路径是安装目录下的 `.venv/bin/python`，实际指向 Homebrew 或系统的 python3）。未授权时会退化为只把 Kiro 调到前台，其他功能不受影响。

## 常见问题

**看不到小狗**：菜单栏 Kiro 小恶灵 → 显示桌宠；若在边缘收起状态，选择「展开桌宠」或单击侧边栏。

**一直显示离线**：确认 Kiro 已启动，且日志目录存在 `~/Library/Application Support/Kiro/logs/`。

**位置乱了**：`./scripts/stop.sh`，删除 `~/Library/Application Support/Kiro Desktop Pet/settings.json` 里的 `x`/`y`/`docked_edge`，再 `./scripts/start.sh`。

**排查**：

```bash
tail -30 ~/Library/Logs/'Kiro Desktop Pet'/pet.log
```

## 隐私

只在本机读取 Kiro 的日志和会话标题（SQLite 以只读方式打开），不修改 Kiro 数据，不上传任何内容，不发起网络请求。只有安装时会访问 pip 源下载 PyObjC。

详细功能说明见 `README.md`。
