#!/usr/bin/env bash
# The e2e stack for Playwright (PROMPT 9.6): a separate backend and worker against fake Slack, GitHub and Linear,
# with the fake Pi image. Needs the stores from `make up-deps` and the image actron-fake-pi:test.
#   scripts/e2e_stack.sh run      # foreground (Playwright's webServer uses this)
#   scripts/e2e_stack.sh start    # background; waits until ready
#   scripts/e2e_stack.sh stop | status
# Extra arguments go to the launcher (--build-frontend, --no-frontend). Logs: .actron/e2e/logs/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E2E="$ROOT/.actron/e2e"
PIDFILE="$E2E/launch.pid"
cmd="${1:-run}"
shift || true

ensure_image() {
  if ! docker image inspect actron-fake-pi:test >/dev/null 2>&1; then
    docker build -q -t actron-fake-pi:test "$ROOT/backend/tests/fakes/fake_pi" >/dev/null
  fi
}

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "$cmd" in
  run)
    ensure_image
    cd "$ROOT/backend"
    exec uv run python -m tests.e2e_stack.launch "$@"
    ;;
  start)
    if running; then echo "e2e stack already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    ensure_image
    mkdir -p "$E2E/logs"
    (cd "$ROOT/backend" && setsid nohup uv run python -m tests.e2e_stack.launch "$@" </dev/null >"$E2E/logs/launch.log" 2>&1 &)
    for _ in $(seq 1 300); do
      if grep -q 'E2E STACK READY' "$E2E/logs/launch.log" 2>/dev/null; then
        grep 'E2E STACK READY' "$E2E/logs/launch.log"; exit 0
      fi
      if grep -qE 'Traceback|exited with' "$E2E/logs/launch.log" 2>/dev/null; then
        tail -30 "$E2E/logs/launch.log" >&2; exit 1
      fi
      sleep 2
    done
    echo "e2e stack did not become ready; see $E2E/logs" >&2
    exit 1
    ;;
  stop)
    if running; then
      pid="$(cat "$PIDFILE")"
      kill -TERM "$pid"
      for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    fi
    echo "e2e stack stopped"
    ;;
  status)
    if running; then echo "running (pid $(cat "$PIDFILE"))"; else echo "stopped"; exit 1; fi
    ;;
  *)
    echo "usage: $0 run|start|stop|status [launcher args]" >&2; exit 2
    ;;
esac
