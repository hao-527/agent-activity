#!/bin/zsh
# Ask the running pet to exercise the auto-retry channel.
#
#   ./scripts/test-retry.sh <session_id>            # 演练：只把文字填进输入框，不发送
#   ./scripts/test-retry.sh <session_id> --send     # 真的发送（会向该会话发一条消息）
#   ./scripts/test-retry.sh --current               # 用状态文件里最近活动的会话
#
# Keystrokes only land from a process that has Accessibility permission, which is
# the launchd-started pet rather than this shell, so the pet performs the action.
set -euo pipefail
SELF="${0:A}"
ROOT="${SELF:h:h}"
source "${SELF:h}/common.sh"
REQUEST="$SUPPORT_DIR/retry-request.json"

SESSION=""
SEND="false"
PROMPT=""
for arg in "$@"; do
  case "$arg" in
    --send) SEND="true" ;;
    --current) SESSION="__current__" ;;
    --prompt=*) PROMPT="${arg#--prompt=}" ;;
    sess_*) SESSION="$arg" ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

if [[ -z "$SESSION" ]]; then
  echo "用法: test-retry.sh <sess_id|--current> [--send] [--prompt=文字]" >&2
  exit 2
fi
if [[ "$SESSION" == "__current__" ]]; then
  SESSION="$("$PYBIN" - "$STATUS_FILE" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
sessions = sorted(data.get("sessions", []), key=lambda s: s.get("updated_at", 0), reverse=True)
print(sessions[0]["session_id"] if sessions else "")
PY
)"
  [[ -n "$SESSION" ]] || { echo "状态文件里没有会话" >&2; exit 1; }
fi

"$PYBIN" - "$REQUEST" "$SESSION" "$SEND" "$PROMPT" <<'PY'
import json, sys
from pathlib import Path
path, session_id, send, prompt = sys.argv[1:5]
payload = {"session_id": session_id, "send": send == "true"}
if prompt:
    payload["prompt"] = prompt
Path(path).parent.mkdir(parents=True, exist_ok=True)
Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
print(f"已请求桌宠对 {session_id} 执行{'发送' if payload['send'] else '演练（只填入）'}")
PY
echo "桌宠会在下一个轮询周期执行；随后看日志："
echo "  tail -5 \"$APP_LOG\""
