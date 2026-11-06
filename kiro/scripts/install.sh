#!/bin/zsh
# One-command install: virtualenv, dependencies, login item, start.
set -euo pipefail
SELF="${0:A}"
ROOT="${SELF:h:h}"
source "${SELF:h}/common.sh"

AUTOSTART=1
for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    -h|--help)
      echo "用法: install.sh [--no-autostart]"
      exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

echo "安装目录: $ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "桌宠只支持 macOS。" >&2
  exit 1
fi

# 1) pick an interpreter: newest available first.
# PyObjC 12 wheels require Python 3.10+, and macOS still ships 3.9 in the Xcode
# command line tools, so a version check has to gate the choice. Without it pip
# fails with a bare "No matching distribution found" that looks like a network
# problem.
MIN_PY_LABEL="3.10"
CANDIDATES=(
  /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11
  /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11
  /opt/homebrew/bin/python3 /usr/local/bin/python3
)
if command -v python3 >/dev/null 2>&1; then
  CANDIDATES+=("$(command -v python3)")
fi
CANDIDATES+=(/usr/bin/python3)

python_new_enough() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

pick_python() {
  local candidate
  for candidate in "${CANDIDATES[@]}"; do
    [[ -x "$candidate" ]] || continue
    python_new_enough "$candidate" && { echo "$candidate"; return 0; }
  done
  return 1
}

report_python_missing() {
  echo "找不到 Python $MIN_PY_LABEL 或更高版本。" >&2
  echo "桌宠依赖 PyObjC 12，它只提供 Python $MIN_PY_LABEL+ 的安装包；macOS 自带的 /usr/bin/python3 通常是 3.9，用不了。" >&2
  echo "本机检测到的解释器：" >&2
  local candidate seen=""
  for candidate in "${CANDIDATES[@]}"; do
    [[ -x "$candidate" ]] || continue
    case " $seen " in *" $candidate "*) continue ;; esac
    seen="$seen $candidate"
    echo "  $candidate  $("$candidate" -V 2>&1)" >&2
  done
  echo "请任选一种方式装一个新版 Python 后重跑本脚本：" >&2
  echo "  brew install python@3.13" >&2
  echo "  或从 https://www.python.org/downloads/macos/ 下载安装包" >&2
}

# An existing virtualenv built on 3.9 would fail the same way, so rebuild it.
if [[ -x "$PYBIN" ]] && ! python_new_enough "$PYBIN"; then
  echo "已有虚拟环境的 Python 版本过低（$("$PYBIN" -V 2>&1)），将重建。"
  rm -rf "$ROOT/.venv"
fi

if [[ ! -x "$PYBIN" ]]; then
  BASE_PYTHON="$(pick_python)" || { report_python_missing; exit 1; }
  echo "使用 Python: $BASE_PYTHON ($("$BASE_PYTHON" -V 2>&1))"
  "$BASE_PYTHON" -m venv "$ROOT/.venv"
fi

mkdir -p "$HOME/Library/LaunchAgents" "$SUPPORT_DIR" "$LOG_DIR"

# 2) dependencies
"$PYBIN" -m pip install --quiet --disable-pip-version-check --no-input --upgrade pip
"$PYBIN" -m pip install --disable-pip-version-check --no-input --requirement "$ROOT/requirements.txt"

# 3) sanity check: Cocoa must be importable, otherwise the window never shows
if ! "$PYBIN" -c 'import AppKit, objc' >/dev/null 2>&1; then
  echo "PyObjC 安装失败：请检查网络或 pip 源后重试。" >&2
  exit 1
fi
"$PYBIN" -m compileall -q "$ROOT/app.py" "$ROOT/kiro_pet" >/dev/null

# 4) render the launch agent for this machine
TEMPLATE="$ROOT/launchd/com.kiro-desktop-pet.plist.template"
TMP_PLIST="$(mktemp)"
sed -e "s|__LABEL__|$LABEL|g" -e "s|__ROOT__|$ROOT|g" -e "s|__LOGDIR__|$LOG_DIR|g" "$TEMPLATE" > "$TMP_PLIST"
plutil -lint "$TMP_PLIST" >/dev/null

# 5) drop any older install (including the pre-1.0 personal label)
# One user runs one pet; make it obvious when an install moves directories.
if [[ -f "$PLIST" ]] && ! grep -q "$ROOT" "$PLIST" 2>/dev/null; then
  PREVIOUS=$(sed -n 's|.*<string>\(/.*\)/app\.py</string>.*|\1|p' "$PLIST" 2>/dev/null | head -1 || true)
  echo "注意: 已存在安装于 ${PREVIOUS:-其它目录}，将切换到当前目录（每个用户只保留一份）。"
fi
for legacy in ${LEGACY_LABELS[@]:-}; do
  launchctl bootout "$DOMAIN/$legacy" >/dev/null 2>&1 || true
  rm -f "$HOME/Library/LaunchAgents/$legacy.plist"
done
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
# bootout is asynchronous. Bootstrapping the same label while the old job is
# still winding down fails with "Input/output error" (5), which is what happens
# when an install moves to a different directory.
for _ in {1..40}; do
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
  sleep 0.25
done
install -m 0644 "$TMP_PLIST" "$PLIST"
rm -f "$TMP_PLIST"
chmod +x "$ROOT/scripts/"*.sh

KIRO_APP=""
for candidate in /Applications/Kiro.app "$HOME/Applications/Kiro.app"; do
  [[ -d "$candidate" ]] && { KIRO_APP="$candidate"; break; }
done
if [[ -n "$KIRO_APP" ]]; then
  echo "已检测到 Kiro.app（$KIRO_APP）"
else
  echo "提示: 未找到 Kiro.app，桌宠会显示为离线状态。"
fi

if (( AUTOSTART )); then
  if ! launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
    echo "登录项注册被占用，重试一次..."
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    sleep 2
    launchctl bootstrap "$DOMAIN" "$PLIST"
  fi
  sleep 1
  launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|pid =|last exit code' || true
  echo "安装完成，桌宠已启动，下次登录会自动运行。"
else
  echo "安装完成（未自动启动）。运行 $ROOT/scripts/start.sh 启动。"
fi
echo "可选: 安装 terminal-notifier 获得可点击的常驻通知 —— brew install terminal-notifier"
