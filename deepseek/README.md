# DeepSeek Harness Activity

macOS 菜单栏里的 DeepSeek Harness 活动指示器。图标使用本机官方 `DeepSeek Harness.app` 图标提取出的透明小鲸鱼主体，右下状态点显示会话状态。

- 绿：至少一个会话正在生成、执行工具或运行任务。
- 黄：至少一个会话正在等待用户确认或选择。
- 紫：Harness 正在运行，但所有会话均空闲。
- 灰：DeepSeek Harness 桌面应用没有运行。
- 橙：无法读取会话投影缓存。

数字只显示正在工作或等待确认的会话数，空闲时隐藏。每 2 秒读取一次 `~/.dsh/storages/session_projcache/sessions/*.json`，只使用 `sessionStats.openStep`、`pendingCalls`、`userQuestions.active`、标题和工作目录等投影字段，不读取压缩对话正文。

## 构建、预览与安装

```sh
./build.command
./DeepSeek\ Harness\ Activity.app/Contents/MacOS/DeepSeekHarnessActivity \
  --render --out /tmp/deepseek-harness-activity.png
./install.command      # 编译 + 安装到 ~/Applications + 登录自启
```

安装目标为 `~/Applications/DeepSeek Harness Activity.app`，登录启动项标签为 `local.deepseek.harness.activity`。`LaunchAgent.plist` 是模板，安装时把 `__HOME__` 替换成当前用户目录，仓库里不含本机路径。菜单里可以直接打开官方 DeepSeek Harness，也可以单独退出 Activity；退出 Activity 不会关闭 Harness。
