#!/usr/bin/env bash
# Runs an OpenSpec agent (openspec-tester, openspec-implementer) non-interactively with `claude -p`.
#
# Usage:
#   run-agent.sh <agent> <task file> [<session id to resume>]
#
# The script appends the mandatory session protocol (../session-protocol.md) to the system prompt,
# connects the project MCP servers (.mcp.json), sets the permission mode and the allowed and denied
# commands of the role. Nobody sees permission prompts: whatever is not allowed is denied at once.
#
# Model: RUN_AGENT_MODEL, otherwise SUBAGENT_MODEL_CODING from .dev.env, otherwise the agent
# definition decides. Claude binary: CLAUDE_BIN, otherwise `claude` from PATH.
#
# The session log is tmp/agents/<agent>-<time>.jsonl (stream-json). Each turn ends with a `result`
# event; the work is over when the process exits. At the end the script prints the session id,
# turns, cost, denials and the last result text.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# The project root is the nearest ancestor of the working directory holding .dev.env.
find_project_root() {
  local dir="$PWD"
  while [ "$dir" != "/" ]; do
    if [ -f "$dir/.dev.env" ]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

PROJECT_ROOT="$(find_project_root)" || {
  echo ".dev.env not found: run from inside the project" >&2
  exit 2
}
cd "$PROJECT_ROOT"

AGENT="${1:-}"
TASK_FILE="${2:-}"
RESUME_ID="${3:-}"

if [ -z "$AGENT" ] || [ -z "$TASK_FILE" ]; then
  echo "Usage: run-agent.sh <agent> <task file> [<session id>]" >&2
  exit 2
fi
if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE" >&2
  exit 2
fi

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
if [ -z "$CLAUDE_BIN" ]; then
  echo "claude not found: set CLAUDE_BIN" >&2
  exit 2
fi

# Skills directory relative to the project root, for permission rules on skill scripts.
SKILLS_REL="$(realpath --relative-to="$PROJECT_ROOT" "$SKILLS_DIR" 2>/dev/null || echo "$SKILLS_DIR")"

# Every MCP server of the project (.mcp.json) is allowed; its name is the permission prefix.
MCP_ALLOWED=()
if [ -f .mcp.json ]; then
  while IFS= read -r SERVER; do
    [ -n "$SERVER" ] && MCP_ALLOWED+=("mcp__${SERVER}__*")
  done < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1], encoding="utf-8-sig")).get("mcpServers", {})))' .mcp.json)
fi

COMMON_ALLOWED=(
  "Read" "Edit" "Write" "Glob" "Grep" "Skill" "TodoWrite"
  "${MCP_ALLOWED[@]}"
  "Bash(python3:*)" "Bash(timeout:*)"
  "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Bash(tail:*)" "Bash(grep:*)" "Bash(find:*)"
  "Bash(wc:*)" "Bash(mkdir:*)" "Bash(echo:*)" "Bash(diff:*)"
  "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git check-ignore:*)"
)
COMMON_DISALLOWED=(
  "Bash(git add:*)" "Bash(git commit:*)" "Bash(git push:*)" "Bash(git reset:*)"
  "Bash(git checkout:*)" "Bash(pkill:*)" "Bash(kill:*)" "Agent"
  # The session and the machine belong to the operator: no screen unlocking, no services.
  "Bash(loginctl:*)" "Bash(systemctl:*)" "Bash(xdg-screensaver:*)"
  # Connection settings and credentials are read by the skill scripts, never by the agent; the
  # environment summary comes from check-services.py of 1c-test-debug. The Bash pattern covers any
  # command naming the file, by any path.
  "Read(**/.dev.env)" "Edit(**/.dev.env)" "Write(**/.dev.env)" "Bash(*.dev.env*)"
  # HTTP to the infobase goes through ib-http.py of 1c-test-debug: with curl the password ends up
  # on the command line and in the session log.
  "Bash(curl:*)" "Bash(wget:*)"
  # Waiting through a scheduled wake-up or a monitor is unreliable in -p mode: the process may exit
  # and kill the agent's background tasks. Long commands run in the foreground.
  "ScheduleWakeup" "CronCreate" "Monitor"
)

case "$AGENT" in
  openspec-tester)
    ROLE_ALLOWED=("Bash($SKILLS_REL/1c-ui-testing/scripts/run-ui-test.sh:*)" "Bash(chmod:*)" "Bash(cp:*)")
    ;;
  openspec-implementer)
    ROLE_ALLOWED=()
    ;;
  *)
    echo "No permission set for agent $AGENT in run-agent.sh" >&2
    exit 2
    ;;
esac

# Last value of a .dev.env key, without surrounding quotes.
get_env_value() {
  sed -n "s/^$1[[:space:]]*=[[:space:]]*//p" .dev.env | tail -1 | tr -d '\r' \
    | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}
MODEL="${RUN_AGENT_MODEL:-$(get_env_value SUBAGENT_MODEL_CODING)}"

mkdir -p tmp/agents
LOG="tmp/agents/$AGENT-$(date +%Y%m%d-%H%M%S).jsonl"

ARGS=(
  -p "$(cat "$TASK_FILE")"
  --agent "$AGENT"
  --append-system-prompt "$(cat "$SCRIPT_DIR/../session-protocol.md")"
  --permission-mode acceptEdits
  --permission-prompts none
  --allowedTools "${COMMON_ALLOWED[@]}" "${ROLE_ALLOWED[@]}"
  --disallowedTools "${COMMON_DISALLOWED[@]}"
  --output-format stream-json
  --verbose
)
[ -f .mcp.json ] && ARGS+=(--mcp-config .mcp.json)
[ -n "$MODEL" ] && ARGS+=(--model "$MODEL")
[ -n "$RESUME_ID" ] && ARGS+=(--resume "$RESUME_ID")

echo "Agent: $AGENT"
echo "Task: $TASK_FILE"
echo "Model: ${MODEL:-from the agent definition}"
echo "Log: $LOG"

"$CLAUDE_BIN" "${ARGS[@]}" </dev/null >"$LOG" 2>"$LOG.err"
RC=$?

python3 - "$LOG" <<'PYEOF'
import json, sys
last = None
for raw in open(sys.argv[1], encoding='utf-8'):
    try:
        event = json.loads(raw)
    except ValueError:
        continue
    if event.get('type') == 'result' and (event.get('num_turns') or 0) > 0:
        last = event
if last:
    print('session_id:', last.get('session_id'))
    print('turns:', last.get('num_turns'), 'cost:', last.get('total_cost_usd'),
          'denials:', len(last.get('permission_denials') or []))
    print(last.get('result') or '')
PYEOF

exit "$RC"
