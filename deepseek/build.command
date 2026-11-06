#!/bin/zsh
set -eu
DIR="${0:A:h}"
cd "$DIR"
APP='DeepSeek Harness Activity.app'
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp Resources/Info.plist "$APP/Contents/Info.plist"
cp Resources/WhaleTemplate.png "$APP/Contents/Resources/WhaleTemplate.png"
swiftc main.swift -o "$APP/Contents/MacOS/DeepSeekHarnessActivity" -framework AppKit -swift-version 5 -O
"$APP/Contents/MacOS/DeepSeekHarnessActivity" --self-test
codesign --force --deep --sign - "$APP"
echo "built: $DIR/$APP"
