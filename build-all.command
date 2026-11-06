#!/bin/zsh
# 依次编译 claude / codex / deepseek 三个菜单栏指示器（只编译，不安装）。
set -eu
cd "${0:A:h}"
for d in claude codex deepseek; do
  echo "==> $d"
  "./$d/build.command"
done
echo "all built"
