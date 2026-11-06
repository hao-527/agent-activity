#!/bin/zsh
# Ask the running desktop pet to jump to one Kiro chat session.
# Used as the click action of the pet's macOS notifications: writing a request
# file keeps the accessibility permission on the pet process itself instead of
# asking for a second grant for terminal-notifier.
set -eu
SELF="${0:A}"
ROOT="${SELF:h:h}"

SID="${1:-}"
if [[ -z "$SID" || ! "$SID" =~ '^sess_[A-Za-z0-9-]{4,80}$' ]]; then
  echo "usage: request-jump.sh sess_<id>" >&2
  exit 1
fi

DIR="$HOME/Library/Application Support/Kiro Desktop Pet"
mkdir -p "$DIR"
TMP="$(mktemp "$DIR/.jump-request.XXXXXX")"
printf '{"session_id":"%s","at":%s}\n' "$SID" "$(date +%s)" > "$TMP"
mv "$TMP" "$DIR/jump-request.json"

# Without the pet there is nobody to walk the tabs, so at least surface Kiro.
if ! pgrep -f "$ROOT/app.py" >/dev/null 2>&1; then
  /usr/bin/open -b dev.kiro.desktop
fi
