#!/bin/zsh
set -euo pipefail
SELF="${0:A}"
ROOT="${SELF:h:h}"
source "${SELF:h}/common.sh"
require_venv

STATE="${1:-multi}"
DURATION="${2:-12}"
case "$STATE" in
  offline|idle|running|multi|success|error|cancelled) ;;
  *) echo "状态必须是: offline idle running multi success error cancelled" >&2; exit 2 ;;
esac
if [[ -n "$(pet_pid || true)" ]]; then
  echo "正式桌宠正在运行；请先执行 $ROOT/scripts/stop.sh 再运行演示。" >&2
  exit 1
fi
exec "$PYBIN" "$APP" --demo-state "$STATE" --smoke-seconds "$DURATION"
