#!/bin/zsh
set -euo pipefail
SELF="${0:A}"
ROOT="${SELF:h:h}"
source "${SELF:h}/common.sh"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"
for legacy in ${LEGACY_LABELS[@]:-}; do
  launchctl bootout "$DOMAIN/$legacy" >/dev/null 2>&1 || true
  rm -f "$HOME/Library/LaunchAgents/$legacy.plist"
done
echo "已停止桌宠并移除登录自启配置。项目、设置和日志均已保留。"
echo "如需重新安装: $ROOT/scripts/install.sh"
