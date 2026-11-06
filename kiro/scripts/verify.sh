#!/bin/zsh
# Post-install self-check. Machine friendly: [PASS]/[WARN]/[FAIL] lines,
# non-zero exit when something is actually broken.
set -u
SELF="${0:A}"
ROOT="${SELF:h:h}"
source "${SELF:h}/common.sh"

FAILED=0
PASSED=0
WARNED=0
pass() { echo "[PASS] $1"; PASSED=$((PASSED + 1)) }
warn() { echo "[WARN] $1"; WARNED=$((WARNED + 1)) }
fail() { echo "[FAIL] $1"; FAILED=1 }

echo "安装目录: $ROOT"

if [[ "$(uname -s)" == "Darwin" ]]; then
  pass "系统为 macOS"
else
  fail "只支持 macOS，当前为 $(uname -s)"
fi

if [[ -x "$PYBIN" ]]; then
  if "$PYBIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    pass "虚拟环境就绪 ($("$PYBIN" -V 2>&1))"
  else
    fail "虚拟环境的 Python 版本过低（$("$PYBIN" -V 2>&1)），PyObjC 需要 3.10+，请重新运行 ./scripts/install.sh"
  fi
else
  fail "缺少虚拟环境，请运行 ./scripts/install.sh"
fi

if [[ -x "$PYBIN" ]] && "$PYBIN" -c 'import AppKit, objc' >/dev/null 2>&1; then
  pass "PyObjC 可用"
else
  fail "PyObjC 不可用，请重新运行 ./scripts/install.sh"
fi

if [[ -x "$PYBIN" ]] && "$PYBIN" -m compileall -q "$ROOT/app.py" "$ROOT/kiro_pet" >/dev/null 2>&1; then
  pass "全部模块可编译"
else
  fail "模块编译失败"
fi

if [[ -f "$PLIST" ]]; then
  if grep -q "$ROOT" "$PLIST" 2>/dev/null; then
    pass "登录自启配置指向当前目录"
  else
    fail "登录自启配置指向其它目录，请重新运行 ./scripts/install.sh"
  fi
else
  warn "未配置登录自启（如使用了 --no-autostart，属正常）"
fi

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  pass "launchd 服务已加载"
else
  warn "launchd 服务未加载，可运行 ./scripts/start.sh"
fi

PID="$(pet_pid || true)"
if [[ -n "$PID" ]]; then
  pass "桌宠进程运行中 (pid=$PID)"
else
  warn "桌宠进程未运行，可运行 ./scripts/start.sh"
fi

if [[ -n "$PID" && -f "$STATUS_FILE" ]]; then
  if "$PYBIN" "$ROOT/scripts/check_status_fresh.py" "$STATUS_FILE" 120; then
    pass "状态文件在持续更新"
  else
    fail "状态文件长时间未更新，请查看 $APP_LOG"
  fi
fi

if [[ -f "$APP_LOG" ]] && tail -200 "$APP_LOG" | grep -q "Traceback"; then
  fail "运行日志中存在异常，请查看 $APP_LOG"
else
  pass "运行日志无异常"
fi

if [[ -d /Applications/Kiro.app || -d "$HOME/Applications/Kiro.app" ]]; then
  pass "已安装 Kiro.app"
else
  warn "未找到 Kiro.app，桌宠会显示离线状态"
fi

if [[ -x /opt/homebrew/bin/terminal-notifier || -x /usr/local/bin/terminal-notifier ]]; then
  pass "terminal-notifier 可用（通知可点击跳转）"
else
  warn "未安装 terminal-notifier，将使用系统通知（不可点击跳转）"
fi

echo
# [WARN] means an optional extra is missing (terminal-notifier, Kiro.app, login
# item), not a broken install: only [FAIL] and the exit code decide.
if (( FAILED )); then
  echo "结论: 安装存在问题，请按上面的 [FAIL] 处理。（通过 $PASSED 项，提示 $WARNED 项）"
  exit 1
fi
echo "结论: 安装正常。（通过 $PASSED 项，提示 $WARNED 项，无 [FAIL]）"
if (( WARNED )); then
  echo "提示: [WARN] 是可选项缺失（如未装 terminal-notifier、未安装 Kiro、未配置登录自启），不影响桌宠正常工作。"
fi
echo "提示: 首次点击任务名跳转会话时，需在 系统设置 > 隐私与安全性 > 辅助功能 中允许 $ROOT/.venv/bin/python"
