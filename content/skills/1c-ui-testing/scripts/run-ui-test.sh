#!/usr/bin/env bash
# Run a UI scenario through the platform's own mechanism: a test manager
# (/TestManager) drives a test client (/TestClient -Tport <port>).
#
# The client starts empty — the scenario opens the forms it needs itself with
# ТестируемоеОкноКлиентскогоПриложения.ВыполнитьКоманду("e1cib/...") (ITS 31.7.4).
# The manager runs the scenario data processor with
#   /Execute <epf> /C"УИМенеджер|<port>|<client address>|<protocol file>"
#
# Requires a running X server (DISPLAY): both sessions are ordinary 1C windows.
#
# Usage:
#   run-ui-test.sh [<port>] [<scenario epf>]
#
# The scenario is resolved in this order: the second argument, then
# UI_TEST_SCENARIO from .dev.env. Protocol and log file names are derived from
# the EPF base name, so runs of different scenarios do not overwrite each other.
#
# Exit codes: 0 — every step [OK]; 1 — a [FAIL], or no protocol was produced.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The project root is the nearest ancestor of the current directory holding
# .dev.env — the skill may be installed under any tool directory, so the root
# is never derived from this script's own location.
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
  echo "No .dev.env found in the current directory or above it — run from the project" >&2
  exit 1
}
cd "$PROJECT_ROOT"

TEST_PORT="${1:-1538}"
SCENARIO="${2:-}"

get_env_value() {
  sed -n "s/^$1=//p" .dev.env | tail -1
}

PLATFORM_PATH="$(get_env_value PLATFORM_PATH)"
INFOBASE_PATH="$(get_env_value INFOBASE_PATH)"
IB_USER="$(get_env_value IB_USER)"
IB_PASSWORD="$(get_env_value IB_PASSWORD)"

[ -n "$SCENARIO" ] || SCENARIO="$(get_env_value UI_TEST_SCENARIO)"
if [ -z "$SCENARIO" ]; then
  echo "No scenario given: pass the built .epf as the second argument, or set UI_TEST_SCENARIO in .dev.env" >&2
  exit 1
fi

case "$SCENARIO" in
  /*) EPF="$SCENARIO" ;;
  *)  EPF="$PROJECT_ROOT/$SCENARIO" ;;
esac
RUN_NAME="$(basename "$EPF" .epf)"

RESULT_FILE="$PROJECT_ROOT/tmp/$RUN_NAME.result.txt"
CLIENT_LOG="tmp/$RUN_NAME.client.log"
MANAGER_LOG="tmp/$RUN_NAME.manager.log"

# db-run.py belongs to the 1c-metadata-manage skill, installed as a sibling of
# this one under the active tool's skills directory. DB_RUN overrides the lookup.
DB_RUN="${DB_RUN:-$SCRIPT_DIR/../../1c-metadata-manage/tools/1c-db-ops/scripts/db-run.py}"

CLIENT_READY_TIMEOUT=120  # wait for the test client to open its port, s
MANAGER_TIMEOUT=1800      # hard limit on the manager session, s

if [ ! -f "$DB_RUN" ]; then
  echo "db-run.py not found: $DB_RUN (install the 1c-metadata-manage skill, or set DB_RUN)" >&2
  exit 1
fi
if [ ! -f "$EPF" ]; then
  echo "Scenario not built: $EPF (build it with 1c-epf-build)" >&2
  exit 1
fi
if [ -z "${DISPLAY:-}" ]; then
  echo "DISPLAY is not set: the test client and manager both need an X server" >&2
  exit 1
fi

mkdir -p tmp
rm -f "$RESULT_FILE"

CLIENT_PID=""

# db-run.py starts 1cv8 as a child process, so the wrapper alone is not enough:
# killing it leaves the test client alive holding the port.
cleanup() {
  if [ -n "$CLIENT_PID" ] && kill -0 "$CLIENT_PID" 2>/dev/null; then
    kill "$CLIENT_PID" 2>/dev/null
  fi
  pkill -f "1cv8 ENTERPRISE.*-Tport $TEST_PORT" 2>/dev/null
  sleep 2
  pkill -9 -f "1cv8 ENTERPRISE.*-Tport $TEST_PORT" 2>/dev/null
  return 0
}
trap cleanup EXIT

# --- pre-flight port check -------------------------------------------------

# A run killed by a timeout leaves the test client alive, still holding the port.
# The next manager then silently attaches to THAT client: the scenario executes
# in a foreign session and no protocol is written at all — the failure looks like
# an unexplained hang. So an occupied port is cleared before the start, and the
# run is cancelled when it cannot be cleared.
if ss -ltn 2>/dev/null | grep -q ":$TEST_PORT\b"; then
  echo "Port $TEST_PORT is busy — killing the leftover test client"
  pkill -f "1cv8 ENTERPRISE.*-Tport $TEST_PORT" 2>/dev/null
  sleep 3
  pkill -9 -f "1cv8 ENTERPRISE.*-Tport $TEST_PORT" 2>/dev/null
  sleep 2
  if ss -ltn 2>/dev/null | grep -q ":$TEST_PORT\b"; then
    echo "Port $TEST_PORT is held by a foreign process and could not be freed. Run cancelled." >&2
    exit 1
  fi
fi

# --- test client -----------------------------------------------------------

echo "Scenario: $EPF"
echo "Starting the test client, port $TEST_PORT"
python3 "$DB_RUN" \
  -V8Path "$PLATFORM_PATH" \
  -InfoBasePath "$INFOBASE_PATH" \
  -UserName "$IB_USER" \
  -Password "$IB_PASSWORD" \
  -AdditionalV8Arguments "/TestClient,-Tport,$TEST_PORT" \
  -Out "$CLIENT_LOG" \
  >"$CLIENT_LOG.run" 2>&1 &
CLIENT_PID=$!

# The manager only connects to a listening port; starting it early wastes its
# retry budget against a closed one.
echo -n "Waiting for the client"
READY=0
for _ in $(seq 1 "$CLIENT_READY_TIMEOUT"); do
  if ss -ltn 2>/dev/null | grep -q ":$TEST_PORT\b"; then
    READY=1
    break
  fi
  echo -n "."
  sleep 1
done
echo

if [ "$READY" -ne 1 ]; then
  echo "Port $TEST_PORT did not open within $CLIENT_READY_TIMEOUT s. Log: $CLIENT_LOG" >&2
  exit 1
fi

# --- test manager ----------------------------------------------------------

echo "Starting the test manager"
timeout "$MANAGER_TIMEOUT" python3 "$DB_RUN" \
  -V8Path "$PLATFORM_PATH" \
  -InfoBasePath "$INFOBASE_PATH" \
  -UserName "$IB_USER" \
  -Password "$IB_PASSWORD" \
  -Execute "$EPF" \
  -CParam "УИМенеджер|$TEST_PORT|localhost|$RESULT_FILE" \
  -AdditionalV8Arguments "/TestManager" \
  -Out "$MANAGER_LOG" \
  -Wait \
  >"$MANAGER_LOG.run" 2>&1
MANAGER_RC=$?

if [ "$MANAGER_RC" -eq 124 ]; then
  echo "The test manager did not finish within $MANAGER_TIMEOUT s" >&2
fi

# --- verdict ---------------------------------------------------------------

if [ ! -f "$RESULT_FILE" ]; then
  echo "No protocol produced: $RESULT_FILE is missing (manager rc $MANAGER_RC)" >&2
  echo "Logs: $CLIENT_LOG, $MANAGER_LOG" >&2
  exit 1
fi

echo "--- $RESULT_FILE ---"
cat "$RESULT_FILE"

if grep -q '^\[FAIL\]' "$RESULT_FILE"; then
  exit 1
fi
exit 0
