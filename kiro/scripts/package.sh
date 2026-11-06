#!/bin/zsh
# Build a shareable archive of the pet: source only, no virtualenv, no state.
set -euo pipefail
SELF="${0:A}"
ROOT="${SELF:h:h}"
VERSION="$(cat "$ROOT/VERSION" 2>/dev/null || echo 0.0.0)"
NAME="kiro-desktop-pet-$VERSION"
OUT_DIR="${1:-$HOME/Desktop}"
STAGE="$(mktemp -d)"
DEST="$STAGE/$NAME"

mkdir -p "$DEST"
for item in app.py requirements.txt VERSION AGENTS.md INSTALL.md README.md QUICKSTART.md kiro_pet launchd scripts; do
  [[ -e "$ROOT/$item" ]] && cp -R "$ROOT/$item" "$DEST/"
done
# Local build artefacts and personal state must never travel with the archive.
find "$DEST" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name "*.pyc" -delete 2>/dev/null || true
rm -rf "$DEST/.venv" "$DEST/previews"
chmod +x "$DEST/scripts/"*.sh

mkdir -p "$OUT_DIR"
ARCHIVE="$OUT_DIR/$NAME.tar.gz"
rm -f "$ARCHIVE"
tar -czf "$ARCHIVE" -C "$STAGE" "$NAME"
ZIP="$OUT_DIR/$NAME.zip"
rm -f "$ZIP"
(cd "$STAGE" && zip -qr "$ZIP" "$NAME")
rm -rf "$STAGE"

echo "已生成:"
echo "  $ARCHIVE"
echo "  $ZIP"
shasum -a 256 "$ARCHIVE" "$ZIP"
echo
echo "同事使用方式（自己装）:"
echo "  tar -xzf $NAME.tar.gz && cd $NAME && ./scripts/install.sh"
echo
echo "同事使用方式（交给 Kiro 自动装）:"
echo "  把压缩包拖进 Kiro 对话，说一句「按 AGENTS.md 安装这个桌宠」即可。"
