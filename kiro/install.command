#!/bin/zsh
# Kiro 桌宠没有编译步骤：建 venv、装 PyObjC 依赖、写登录自启、启动。
# 参数透传给 scripts/install.sh（支持 --no-autostart）。
set -eu
cd "${0:A:h}"
exec ./scripts/install.sh "$@"
