#!/bin/zsh
set -eu
DIR="${0:A:h}"
cd "$DIR"
mkdir -p 'Claude Activity.app/Contents/MacOS'
cp Resources/Info.plist 'Claude Activity.app/Contents/Info.plist'
swiftc main.swift -o 'Claude Activity.app/Contents/MacOS/ClaudeActivity' \
  -framework AppKit -swift-version 5 -O
'Claude Activity.app/Contents/MacOS/ClaudeActivity' --self-test
codesign --force --deep --sign - 'Claude Activity.app'
echo "built: $DIR/Claude Activity.app"
