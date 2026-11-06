# Shared settings for the Kiro Desktop Pet scripts.
# Sourced by every script; ROOT must already point at the project directory.
LABEL="com.kiro-desktop-pet"
# Older personal labels to clean up on install; empty for public builds.
LEGACY_LABELS=()
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SUPPORT_DIR="$HOME/Library/Application Support/Kiro Desktop Pet"
LOG_DIR="$HOME/Library/Logs/Kiro Desktop Pet"
STATUS_FILE="$SUPPORT_DIR/status.json"
APP_LOG="$LOG_DIR/pet.log"
PYBIN="$ROOT/.venv/bin/python"
APP="$ROOT/app.py"

pet_pid() {
  pgrep -f "$APP" | head -1
}

require_venv() {
  if [[ ! -x "$PYBIN" ]]; then
    echo "未找到虚拟环境：请先运行 $ROOT/scripts/install.sh" >&2
    exit 1
  fi
}
