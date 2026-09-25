#!/usr/bin/env bash
# Run a UI scenario through the platform's own mechanism: a test manager
# (/TestManager) drives a test client (/TestClient -Tport <port>).
#
# The client starts empty — the scenario opens the forms it needs itself with
# ТестируемоеОкноКлиентскогоПриложения.ВыполнитьКоманду("e1cib/...") (ITS 31.7.4).
# The manager runs the test with
#   /C"УИМенеджер|<port>|<client address>|<protocol file>|<project root>|<publication>|<test>"
# and the extension of its own infobase dispatches by the test name.
#
# Requires a running X server (DISPLAY): both sessions are ordinary 1C windows.
#
# Usage:
#   run-ui-test.sh [<port>] --test <test name> [--via-manager]
#
# Every test of the project lives in one extension of the manager infobase, which
# build-test-extension.py rebuilds when the sources change. Protocol and log file names are
# derived from the test name, so runs of different tests do not overwrite each other.
#
# The run does not start on a locked screen: under the lock screen the test client
# does not open forms and the scenario fails on waits, not on assertions.
#
# Fail fast: when the manager has not connected to the client within CONNECT_TIMEOUT,
# the protocol has no line within FIRST_STEP_TIMEOUT, or the protocol has not grown for
# STALL_TIMEOUT (a scenario hanging after its first steps), the run is stopped, the 1C
# sessions are killed and diagnostics are printed: UI_TEST_DIAG_CMD when set, otherwise
# scripts/ib-errors.py of the sibling 1c-test-debug skill when it is installed — a scenario
# module that does not compile shows up there as _$PerformError$_. Limits are overridden with
# UI_TEST_CONNECT_TIMEOUT, UI_TEST_FIRST_STEP_TIMEOUT, UI_TEST_STALL_TIMEOUT and UI_TEST_MANAGER_TIMEOUT.
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

# The manager works in an infobase of its own whose extension holds every test of the project;
# the test is picked by name (docs/test-extension.md).
TEST_NAME=""
if [ "${2:-}" = "--test" ]; then
  TEST_NAME="${3:-}"
fi
if [ -z "$TEST_NAME" ]; then
  echo "Usage: run-ui-test.sh [<port>] --test <test name> [--via-manager]" >&2
  echo "The name is a directory under openspec/tests/*/{ui,e2e} or a file under unit/" >&2
  exit 1
fi
# The manager infobase is a file one: a thick client cannot connect to a standalone server, and
# the `Обработки` collection a test is invoked through exists only on a thick client.
MANAGER_BASE_DIR="${UI_TEST_MANAGER_DIR:-base-tests}"

get_env_value() {
  sed -n "s/^$1=//p" .dev.env | tail -1
}

PLATFORM_PATH="$(get_env_value PLATFORM_PATH)"
INFOBASE_PATH="$(get_env_value INFOBASE_PATH)"
INFOBASE_KIND="$(get_env_value INFOBASE_KIND)"
# Passed to the scenario as the sixth element of its launch parameter: server-side steps of a
# scenario reach the infobase through the debug services at this address.
INFOBASE_PUBLISH_URL="$(get_env_value INFOBASE_PUBLISH_URL)"
IB_USER="$(get_env_value IB_USER)"
IB_PASSWORD="$(get_env_value IB_PASSWORD)"

# How the sessions reach the infobase.
#
# A served infobase (INFOBASE_KIND=server) keeps its connection string in INFOBASE_PATH
# (`<host>[:<gate port>]\<name>`, a slash is accepted too) and is reached by the **thin** client:
# a thick one cannot connect to a standalone server at all. A file infobase is unchanged.
if [ "$INFOBASE_KIND" = "server" ]; then
  IB_SERVER="${INFOBASE_PATH%[\\/]*}"
  IB_REF="${INFOBASE_PATH##*[\\/]}"
  if [ -z "$IB_SERVER" ] || [ -z "$IB_REF" ] || [ "$IB_SERVER" = "$INFOBASE_PATH" ]; then
    echo "INFOBASE_KIND=server, but INFOBASE_PATH is not a connection string: $INFOBASE_PATH" >&2
    echo "Expected <host>[:<gate port>]\\<infobase name>" >&2
    exit 1
  fi
  IB_ARGS=(-ClientKind thin -InfoBaseServer "$IB_SERVER" -InfoBaseRef "$IB_REF")
  CLIENT_BINARY="1cv8c"
  echo "Infobase: server $IB_SERVER, base $IB_REF (thin client)"
else
  IB_ARGS=(-InfoBasePath "$INFOBASE_PATH")
  CLIENT_BINARY="1cv8 ENTERPRISE"
  echo "Infobase: file $INFOBASE_PATH"
fi

RUN_NAME="${TEST_NAME//\//_}"

# Patterns for killing the sessions: the client binary differs by infobase kind, the manager is
# always a thick client of the file base.
CLIENT_PATTERN="$CLIENT_BINARY.*-Tport $TEST_PORT"
MANAGER_PATTERN="1cv8 ENTERPRIS[E].*$MANAGER_BASE_DIR"

RESULT_FILE="$PROJECT_ROOT/tmp/$RUN_NAME.result.txt"
CLIENT_LOG="tmp/$RUN_NAME.client.log"
MANAGER_LOG="tmp/$RUN_NAME.manager.log"

# db-run.py belongs to the 1c-metadata-manage skill, installed as a sibling of
# this one under the active tool's skills directory. DB_RUN overrides the lookup.
DB_RUN="${DB_RUN:-$SCRIPT_DIR/../../1c-metadata-manage/tools/1c-db-ops/scripts/db-run.py}"

CLIENT_READY_TIMEOUT=120                                  # wait for the test client to open its port, s
CONNECT_TIMEOUT="${UI_TEST_CONNECT_TIMEOUT:-240}"         # manager connects to the client, s
FIRST_STEP_TIMEOUT="${UI_TEST_FIRST_STEP_TIMEOUT:-360}"   # first protocol line, s
STALL_TIMEOUT="${UI_TEST_STALL_TIMEOUT:-300}"             # no protocol growth after the first line, s
MANAGER_TIMEOUT="${UI_TEST_MANAGER_TIMEOUT:-1800}"        # hard limit on the manager session, s

if [ ! -f "$DB_RUN" ]; then
  echo "db-run.py not found: $DB_RUN (install the 1c-metadata-manage skill, or set DB_RUN)" >&2
  exit 1
fi
# A unit check on the fast path opens no window: the same file goes to Dbg_Executor over HTTP.
# Neither guard below applies to it. The kind is read from the sources, because the manifest
# that the run itself uses appears only after the build further down.
NEEDS_CLIENT=1
if [ "${4:-}" != "--via-manager" ] && compgen -G "openspec/tests/*/unit/$TEST_NAME.bsl" >/dev/null; then
  NEEDS_CLIENT=0
fi

if [ "$NEEDS_CLIENT" = 1 ]; then
  if [ -z "${DISPLAY:-}" ]; then
    echo "DISPLAY is not set: the test client and manager both need an X server" >&2
    exit 1
  fi

  # Is the lock screen up? Two sources disagree, and the order matters.
  #
  # logind's LockedHint is what the desktop *told* logind, and it goes stale: KDE leaves it
  # at "yes" after `loginctl unlock-session`, so the hint alone refuses runs on an unlocked
  # screen. The freedesktop ScreenSaver interface answers for the locker itself, so it wins
  # whenever it answers at all; the hint is the fallback for a desktop that has no such bus.
  SCREEN_LOCKED=""
  if command -v dbus-send >/dev/null 2>&1; then
    LOCK_ANSWER="$(XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" timeout 10 dbus-send \
      --session --print-reply --dest=org.freedesktop.ScreenSaver /ScreenSaver \
      org.freedesktop.ScreenSaver.GetActive 2>/dev/null | tail -1)"
    case "$LOCK_ANSWER" in
      *"boolean true") SCREEN_LOCKED="yes" ;;
      *"boolean false") SCREEN_LOCKED="no" ;;
    esac
  fi
  if [ -z "$SCREEN_LOCKED" ] && command -v loginctl >/dev/null 2>&1; then
    for SESSION_ID in $(loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$(id -un)" '$3==u {print $1}'); do
      SESSION_TYPE="$(loginctl show-session "$SESSION_ID" -p Type --value 2>/dev/null)"
      SESSION_LOCKED="$(loginctl show-session "$SESSION_ID" -p LockedHint --value 2>/dev/null)"
      if { [ "$SESSION_TYPE" = "x11" ] || [ "$SESSION_TYPE" = "wayland" ]; } && [ "$SESSION_LOCKED" = "yes" ]; then
        SCREEN_LOCKED="yes"
      fi
    done
  fi
  if [ "$SCREEN_LOCKED" = "yes" ]; then
    echo "The screen is locked: the test client does not open forms under the lock screen. Run not started. Do not unlock the screen and do not repeat the run - report it to the operator." >&2
    exit 3
  fi
fi

mkdir -p tmp
rm -f "$RESULT_FILE"

SESSIONS_SCRIPT="$SCRIPT_DIR/../../1c-ibsrv-ops/scripts/ib-sessions.py"
# Sessions of killed runs hold licenses, and the next manager gets «Файл программной лицензии
# не найден». Only the sessions that appeared during this run are terminated: other sessions of
# the tested base are the operator's.
SESSIONS_BEFORE=""
if [ -n "$TEST_NAME" ] && [ -f "$SESSIONS_SCRIPT" ]; then
  SESSIONS_BEFORE="$(timeout 120 python3 "$SESSIONS_SCRIPT" auto ids 2>/dev/null)"
fi

CLIENT_PID=""
MANAGER_PID=""

# db-run.py starts 1cv8 as a child process, so the wrapper alone is not enough:
# killing it leaves the test client alive holding the port. The manager infobase itself is
# long-lived and is not stopped by a run - it is started and stopped like the tested one.
cleanup() {
  if [ -n "$CLIENT_PID" ] && kill -0 "$CLIENT_PID" 2>/dev/null; then
    kill "$CLIENT_PID" 2>/dev/null
  fi
  if [ -n "$MANAGER_PID" ] && kill -0 "$MANAGER_PID" 2>/dev/null; then
    kill "$MANAGER_PID" 2>/dev/null
  fi
  pkill -f "$CLIENT_PATTERN" 2>/dev/null
  pkill -f "$MANAGER_PATTERN" 2>/dev/null
  sleep 2
  pkill -9 -f "$CLIENT_PATTERN" 2>/dev/null
  pkill -9 -f "$MANAGER_PATTERN" 2>/dev/null
  if [ -n "$SESSIONS_BEFORE" ] || [ -n "$TEST_NAME" ]; then
    local ours
    ours="$(timeout 120 python3 "$SESSIONS_SCRIPT" auto ids 2>/dev/null | tr ' ' '\n' \
      | grep -vxF -e "$(printf '%s\n' $SESSIONS_BEFORE)" 2>/dev/null | tr '\n' ' ')"
    if [ -n "$ours" ]; then
      timeout 120 python3 "$SESSIONS_SCRIPT" auto terminate $ours >/dev/null 2>&1
    fi
  fi
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
  pkill -f "$CLIENT_PATTERN" 2>/dev/null
  sleep 3
  pkill -9 -f "$CLIENT_PATTERN" 2>/dev/null
  sleep 2
  if ss -ltn 2>/dev/null | grep -q ":$TEST_PORT\b"; then
    echo "Port $TEST_PORT is held by a foreign process and could not be freed. Run cancelled." >&2
    exit 1
  fi
fi

# --- test client -----------------------------------------------------------

# Sessions of killed clients survive in a served infobase and hold their licenses: the next client
# is then refused with «лицензия не обнаружена» or «вход в приложение невозможен». The runner only
# reports them — someone else's client may be open on purpose.
if [ "$INFOBASE_KIND" = "server" ] && [ -f "$SESSIONS_SCRIPT" ]; then
  SESSIONS="$(timeout 120 python3 "$SESSIONS_SCRIPT" auto list 2>/dev/null | tail -1)"
  case "$SESSIONS" in
    *": 0"|"") : ;;
    *) echo "Infobase sessions before the run — $SESSIONS"
       echo "  a run refused by licensing is cured by: python3 $SESSIONS_SCRIPT auto terminate-all" ;;
  esac
fi

if [ -n "$TEST_NAME" ]; then
  echo "Test extension: checking that it matches the sources"
  EXTENSION_BUILD="$SCRIPT_DIR/build-test-extension.py"
  if [ ! -f "$EXTENSION_BUILD" ]; then
    echo "build-test-extension.py not found next to the runner" >&2
    exit 1
  fi
  if ! python3 "$EXTENSION_BUILD" --data-dir "$MANAGER_BASE_DIR" >"tmp/$RUN_NAME.extension.log" 2>&1; then
    echo "The test extension was not built, see tmp/$RUN_NAME.extension.log" >&2
    tail -5 "tmp/$RUN_NAME.extension.log" >&2
    exit 1
  fi
  tail -2 "tmp/$RUN_NAME.extension.log"
  # The manifest lists what the loaded extension actually holds; the build log may say
  # nothing when the build was skipped as up to date.
  # The manifest is keyed by the qualified id `<capability>/<kind>/<name>`, which is also what
  # the dispatcher branches on. A short name is accepted while it names exactly one test; when
  # two capabilities use it, the runner refuses and prints both ids rather than guessing.
  RESOLVED="$(python3 -c "import json,sys
tests = json.load(open('$MANAGER_BASE_DIR/tests.manifest.json'))['tests']
want = '$TEST_NAME'
hits = [i for i in tests if i == want] or [i for i, t in tests.items() if t['name'] == want]
if len(hits) == 1:
    print('\t'.join([hits[0], tests[hits[0]]['kind'], tests[hits[0]]['name'],
                     tests[hits[0]].get('module', '')]))
elif hits:
    sys.stderr.write('ambiguous\n' + '\n'.join('  ' + i for i in sorted(hits)) + '\n')
" 2>"tmp/resolve.$$")"
  if [ -z "$RESOLVED" ]; then
    if grep -q ambiguous "tmp/resolve.$$" 2>/dev/null; then
      echo "The name $TEST_NAME belongs to more than one test — repeat it as <capability>/<kind>/<name>:" >&2
      grep -v ambiguous "tmp/resolve.$$" >&2
    else
      echo "No test named $TEST_NAME in the extension — check openspec/tests/*/{ui,e2e,unit}" >&2
    fi
    rm -f "tmp/resolve.$$"
    exit 1
  fi
  rm -f "tmp/resolve.$$"
  TEST_ID="$(printf '%s' "$RESOLVED" | cut -f1)"
  TEST_KIND="$(printf '%s' "$RESOLVED" | cut -f2)"
  TEST_SHORT="$(printf '%s' "$RESOLVED" | cut -f3)"
  TEST_MODULE_PATH="$(printf '%s' "$RESOLVED" | cut -f4)"
  RUN_NAME="$TEST_SHORT"
  RESULT_FILE="$PROJECT_ROOT/tmp/$RUN_NAME.result.txt"
  CLIENT_LOG="tmp/$RUN_NAME.client.log"
  MANAGER_LOG="tmp/$RUN_NAME.manager.log"
  rm -f "$RESULT_FILE"

  # A unit check needs no client and no manager: the same file goes straight to Dbg_Executor of
  # the tested base. --via-manager forces the long way, the one the extension provides.
  if [ "$TEST_KIND" = "unit" ] && [ "${4:-}" != "--via-manager" ]; then
    TEST_MODULE="$TEST_MODULE_PATH"
    EXEC_SCRIPT="$SCRIPT_DIR/../../1c-test-debug/scripts/ib-http.py"
    if [ ! -f "$EXEC_SCRIPT" ]; then
      echo "ib-http.py of the 1c-test-debug skill not found: $EXEC_SCRIPT" >&2
      exit 1
    fi
    echo "Unit check $TEST_NAME: $TEST_MODULE through Dbg_Executor"
    ANSWER="$(python3 "$EXEC_SCRIPT" --exec "$TEST_MODULE" --timeout 600)"
    # A check has as many steps as it needs, and the one that failed is as likely to be the
    # last as the first — so the answer is summarised, not truncated: every failed step in
    # full, and the counts. The whole answer stays in the log for anything else.
    printf '%s\n' "$ANSWER" >"tmp/$RUN_NAME.result.json"
    python3 - "tmp/$RUN_NAME.result.json" <<'SUMMARY'
import json, sys
# ib-http.py prefixes the body with its status line ("HTTP 200"), so the JSON starts later.
raw = open(sys.argv[1], encoding="utf-8-sig").read()
start = raw.find("{")
try:
    answer = json.loads(raw[start:]) if start >= 0 else {}
except Exception:
    print(raw[:4000]); raise SystemExit
steps = answer.get("Шаги", [])
failed = [s for s in steps if not s.get("Успех")]
for s in failed:
    print("[FAIL] " + s.get("Текст", ""))
print("Steps: %d, failed: %d" % (len(steps), len(failed)))
SUMMARY
    echo "Full answer: tmp/$RUN_NAME.result.json"
    case "$ANSWER" in
      *'"ОбщийУспех": true'*) exit 0 ;;
      *) echo "Unit check failed (see the failed steps above)" >&2; exit 1 ;;
    esac
  fi
  # The manager infobase is a file one and has no users at all — credentials of the tested base
  # would be rejected there («Пользователь ИБ не идентифицирован»).
  MANAGER_ARGS=(-ClientKind thick -InfoBasePath "$PROJECT_ROOT/$MANAGER_BASE_DIR")
  MANAGER_AUTH=()
fi

echo "Test: $TEST_NAME (test extension of the manager infobase)"
echo "Starting the test client, port $TEST_PORT"
python3 "$DB_RUN" \
  -V8Path "$PLATFORM_PATH" \
  "${IB_ARGS[@]}" \
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
CPARAM="УИМенеджер|$TEST_PORT|localhost|$RESULT_FILE|$PROJECT_ROOT|$INFOBASE_PUBLISH_URL|$TEST_ID"
python3 "$DB_RUN" \
  -V8Path "$PLATFORM_PATH" \
  "${MANAGER_ARGS[@]}" \
  ${MANAGER_AUTH[@]+"${MANAGER_AUTH[@]}"} \
  -CParam "$CPARAM" \
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
LAST_SIZE=-1
LAST_GROWTH=$(date +%s)
while kill -0 "$MANAGER_PID" 2>/dev/null; do
  NOW=$(date +%s)
  ELAPSED=$(( NOW - MANAGER_STARTED ))
  SIZE=$( [ -f "$RESULT_FILE" ] && wc -c <"$RESULT_FILE" || echo 0 )
  if [ "$SIZE" -ne "$LAST_SIZE" ]; then
    LAST_SIZE=$SIZE
    LAST_GROWTH=$NOW
  fi
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
  if [ "$SIZE" -gt 0 ] && [ $(( NOW - LAST_GROWTH )) -ge "$STALL_TIMEOUT" ]; then
    FAILED_EARLY="the protocol has not grown for $STALL_TIMEOUT s"
    break
  fi
  if [ "$ELAPSED" -ge "$MANAGER_TIMEOUT" ]; then
    FAILED_EARLY="the test manager did not finish within $MANAGER_TIMEOUT s"
    break
  fi
  # Heartbeat: while the scenario runs it shows the runner is alive and how long the protocol
  # has not grown. Without it the runner's silence is indistinguishable from a stuck watchdog.
  if [ $(( ELAPSED % 60 )) -lt 2 ] && [ "$ELAPSED" -ge 60 ]; then
    echo "  waiting: ${ELAPSED}s, protocol ${SIZE}B, no growth for $(( NOW - LAST_GROWTH ))s"
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
