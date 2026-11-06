#!/bin/zsh
set -euo pipefail
SELF="${0:A}"
ROOT="${SELF:h:h}"
source "${SELF:h}/common.sh"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$DOMAIN/$LABEL"
  echo "Kiro Desktop Pet 已停止"
else
  echo "Kiro Desktop Pet 当前未运行"
fi
