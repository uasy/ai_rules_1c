#!/usr/bin/env bash
# Run a UI scenario through the platform's own mechanism: a test manager
# (/TestManager) drives a test client (/TestClient -Tport <port>).
#
# The client starts empty — the scenario opens the forms it needs itself with
# ТестируемоеОкноКлиентскогоПриложения.ВыполнитьКоманду("e1cib/...") (ITS 31.7.4).
# The manager runs the scenario data processor with
#   /Execute <epf> /C"УИМенеджер|<port>|<client address>|<protocol file>|<project root>"
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
# The run does not start on a locked screen: under the lock screen the test client
# does not open forms and the scenario fails on waits, not on assertions.
#
# Fail fast: when the manager has not connected to the client within CONNECT_TIMEOUT,
# or the protocol has no line within FIRST_STEP_TIMEOUT, the run is stopped, the 1C
# sessions are killed and diagnostics are printed: UI_TEST_DIAG_CMD when set, otherwise
# scripts/ib-errors.py of the sibling 1c-test-debug skill when it is installed — a scenario
# module that does not compile shows up there as _$PerformError$_. Limits are overridden with UI_TEST_CONNECT_TIMEOUT,
# UI_TEST_FIRST_STEP_TIMEOUT and UI_TEST_MANAGER_TIMEOUT.
#
# Exit codes: 0 — every step [OK]; 1 — a [FAIL], or no protocol was produced;
# 3 — the screen is locked, the run was not started.

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

CLIENT_READY_TIMEOUT=120                                  # wait for the test client to open its port, s
CONNECT_TIMEOUT="${UI_TEST_CONNECT_TIMEOUT:-240}"         # manager connects to the client, s
FIRST_STEP_TIMEOUT="${UI_TEST_FIRST_STEP_TIMEOUT:-360}"   # first protocol line, s
MANAGER_TIMEOUT="${UI_TEST_MANAGER_TIMEOUT:-1800}"        # hard limit on the manager session, s

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

# Graphical sessions of this user flagged as locked.
if command -v loginctl >/dev/null 2>&1; then
  for SESSION_ID in $(loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$(id -un)" '$3==u {print $1}'); do
    SESSION_TYPE="$(loginctl show-session "$SESSION_ID" -p Type --value 2>/dev/null)"
    SESSION_LOCKED="$(loginctl show-session "$SESSION_ID" -p LockedHint --value 2>/dev/null)"
    if { [ "$SESSION_TYPE" = "x11" ] || [ "$SESSION_TYPE" = "wayland" ]; } && [ "$SESSION_LOCKED" = "yes" ]; then
      echo "The screen is locked (session $SESSION_ID): the test client does not open forms under the lock screen. Run not started." >&2
      exit 3
    fi
  done
fi

mkdir -p tmp
rm -f "$RESULT_FILE"

CLIENT_PID=""
MANAGER_PID=""

# db-run.py starts 1cv8 as a child process, so the wrapper alone is not enough:
# killing it leaves the test client alive holding the port.
cleanup() {
  if [ -n "$CLIENT_PID" ] && kill -0 "$CLIENT_PID" 2>/dev/null; then
    kill "$CLIENT_PID" 2>/dev/null
  fi
  if [ -n "$MANAGER_PID" ] && kill -0 "$MANAGER_PID" 2>/dev/null; then
    kill "$MANAGER_PID" 2>/dev/null
  fi
  pkill -f "1cv8 ENTERPRISE.*-Tport $TEST_PORT" 2>/dev/null
  pkill -f "1cv8 ENTERPRISE.*/Execute $EPF" 2>/dev/null
  sleep 2
  pkill -9 -f "1cv8 ENTERPRISE.*-Tport $TEST_PORT" 2>/dev/null
  pkill -9 -f "1cv8 ENTERPRISE.*/Execute $EPF" 2>/dev/null
  return 0
}
trap cleanup EXIT
# A stop by timeout (SIGTERM) or Ctrl+C also goes through cleanup, otherwise the 1C sessions stay alive.
trap 'exit 143' TERM
trap 'exit 130' INT

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
MANAGER_STARTED=$(date +%s)
python3 "$DB_RUN" \
  -V8Path "$PLATFORM_PATH" \
  -InfoBasePath "$INFOBASE_PATH" \
  -UserName "$IB_USER" \
  -Password "$IB_PASSWORD" \
  -Execute "$EPF" \
  -CParam "УИМенеджер|$TEST_PORT|localhost|$RESULT_FILE|$PROJECT_ROOT" \
  -AdditionalV8Arguments "/TestManager" \
  -Out "$MANAGER_LOG" \
  -Wait \
  >"$MANAGER_LOG.run" 2>&1 &
MANAGER_PID=$!

# Runs the project's diagnostics, if any. A manager session sitting on an error window keeps a
# file infobase busy, so it is called only after the sessions are killed.
IB_ERRORS="$SCRIPT_DIR/../../1c-test-debug/scripts/ib-errors.py"
run_diagnostics() {
  local minutes=$(( ($(date +%s) - MANAGER_STARTED) / 60 + 2 ))
  if [ -n "${UI_TEST_DIAG_CMD:-}" ]; then
    echo "--- diagnostics: $UI_TEST_DIAG_CMD ---" >&2
    timeout 90 bash -c "$UI_TEST_DIAG_CMD" >&2 || echo "diagnostics failed or timed out" >&2
  elif [ -f "$IB_ERRORS" ]; then
    echo "--- event-log errors for the last $minutes min (1c-test-debug ib-errors.py) ---" >&2
    timeout 90 python3 "$IB_ERRORS" "$minutes" 10 >&2 || echo "event log not read" >&2
  fi
}

CONNECTED=0
FAILED_EARLY=""
while kill -0 "$MANAGER_PID" 2>/dev/null; do
  ELAPSED=$(( $(date +%s) - MANAGER_STARTED ))
  if [ "$CONNECTED" -eq 0 ] && ss -tn state established 2>/dev/null | grep -q ":$TEST_PORT\b"; then
    CONNECTED=1
    echo "The manager connected to the client after $ELAPSED s"
  fi
  if [ "$CONNECTED" -eq 0 ] && [ "$ELAPSED" -ge "$CONNECT_TIMEOUT" ]; then
    FAILED_EARLY="the manager did not connect to the client within $CONNECT_TIMEOUT s"
    break
  fi
  if [ ! -s "$RESULT_FILE" ] && [ "$ELAPSED" -ge "$FIRST_STEP_TIMEOUT" ]; then
    FAILED_EARLY="no protocol line within $FIRST_STEP_TIMEOUT s"
    break
  fi
  if [ "$ELAPSED" -ge "$MANAGER_TIMEOUT" ]; then
    FAILED_EARLY="the test manager did not finish within $MANAGER_TIMEOUT s"
    break
  fi
  sleep 2
done

if [ -n "$FAILED_EARLY" ]; then
  echo "Run stopped: $FAILED_EARLY" >&2
  cleanup
  run_diagnostics
fi

# --- verdict ---------------------------------------------------------------

if [ ! -s "$RESULT_FILE" ]; then
  echo "No protocol produced: $RESULT_FILE is empty or missing" >&2
  echo "Logs: $CLIENT_LOG, $MANAGER_LOG" >&2
  if [ -z "$FAILED_EARLY" ]; then
    cleanup
    run_diagnostics
  fi
  exit 1
fi

echo "--- $RESULT_FILE ---"
cat "$RESULT_FILE"

if [ -n "$FAILED_EARLY" ] || grep -q '^\[FAIL\]' "$RESULT_FILE"; then
  exit 1
fi
exit 0
