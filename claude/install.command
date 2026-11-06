#!/bin/zsh
# 构建并安装到 ~/Applications，同时写入登录自启项 local.claude.activity。
set -eu
cd "${0:A:h}"
./build.command

APP='Claude Activity.app'
TARGET="$HOME/Applications/$APP"
PLIST="$HOME/Library/LaunchAgents/local.claude.activity.plist"

launchctl bootout "gui/$(id -u)/local.claude.activity" 2>/dev/null || true
pkill -f 'Applications/Claude Activity.app/Contents/MacOS/ClaudeActivity' 2>/dev/null || true
sleep 0.3
mkdir -p "$HOME/Applications"
rm -rf "$TARGET"
cp -R "$APP" "$TARGET"
codesign --force --deep --sign - "$TARGET"
mkdir -p "$(dirname "$PLIST")"
sed "s|__HOME__|$HOME|g" LaunchAgent.plist > "$PLIST"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: $TARGET (auto-start enabled)"
