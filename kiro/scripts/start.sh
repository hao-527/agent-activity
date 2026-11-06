#!/bin/zsh
set -euo pipefail
SELF="${0:A}"
ROOT="${SELF:h:h}"
source "${SELF:h}/common.sh"
require_venv

if [[ ! -f "$PLIST" ]]; then
  echo "未安装登录自启配置，请先运行: $ROOT/scripts/install.sh" >&2
  exit 1
fi
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl kickstart -k "$DOMAIN/$LABEL"
else
  launchctl bootstrap "$DOMAIN" "$PLIST"
fi
sleep 1
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|pid =|last exit code' || true
