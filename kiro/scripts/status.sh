#!/bin/zsh
set -u
SELF="${0:A}"
ROOT="${SELF:h:h}"
source "${SELF:h}/common.sh"

echo "[目录] $ROOT"
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "[launchd] 已加载"
  launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|pid =|last exit code' || true
else
  echo "[launchd] 未加载"
fi
PID="$(pet_pid || true)"
[[ -n "$PID" ]] && echo "[process] pid=$PID" || echo "[process] 未运行"
if [[ -f "$STATUS_FILE" && -x "$PYBIN" ]]; then
  "$PYBIN" "$ROOT/scripts/print_status.py" "$STATUS_FILE"
else
  echo "[state] 尚未生成"
fi
if [[ -f "$APP_LOG" ]]; then
  echo "[log] 最近 5 行"
  tail -5 "$APP_LOG"
fi
