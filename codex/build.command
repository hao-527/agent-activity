#!/bin/zsh
set -eu
DIR="${0:A:h}"
cd "$DIR"
APP='Codex Activity.app'
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp Resources/Info.plist "$APP/Contents/Info.plist"
cp Resources/ChatGPTTemplate.png "$APP/Contents/Resources/ChatGPTTemplate.png"
swiftc main.swift -o "$APP/Contents/MacOS/CodexActivity" -framework AppKit
"$APP/Contents/MacOS/CodexActivity" --self-test
codesign --force --deep --sign - "$APP"
echo "built: $DIR/$APP"
