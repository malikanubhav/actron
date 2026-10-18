#!/usr/bin/env bash
# Whole test suite with a summary of counts per level (PROMPT 9 and 15). Needs the compose stack (`make up`):
# the stores for the backend tests and the e2e stack, and the running frontend and backend for Lighthouse.
#
# Levels, in order:
#   backend   ruff, mypy --strict, then pytest per level (unit, property, integration, contract, workflows, api,
#             eval) with line coverage across all of them; live tests are deselected (scripts/live_smoke.sh)
#   frontend  typecheck, lint, unit tests with coverage, fixture e2e (MSW build in .next-fixtures),
#             stack e2e (real backend, worker and frontend against fake Slack, GitHub, Linear and Jev, fake Pi;
#             scripts/e2e_stack.sh, a fresh e2e world every run), Lighthouse CI desktop and mobile against :3000
#   spec      scripts/spec_coverage.py (every acceptance id named by a test)
# Environment: SKIP_BACKEND=1, SKIP_FRONTEND=1, SKIP_STACK_E2E=1, SKIP_LIGHTHOUSE=1, SKIP_COVERAGE=1,
#   ACTRON_TEST_REDIS_DB (default 15). Logs go to .actron/test-all/<UTC time>/ (or TEST_ALL_LOG_DIR).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_DIR="${TEST_ALL_LOG_DIR:-$ROOT/.actron/test-all/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$LOG_DIR"
summary=()
failed=0
started=$(date +%s)

record() { # name, exit code, detail
  local name="$1" code="$2" detail="$3"
  if [ "$code" -eq 0 ]; then
    summary+=("$(printf 'pass  %-26s %s' "$name" "$detail")")
  elif [ "$code" -eq 5 ]; then
    summary+=("$(printf 'none  %-26s %s' "$name" 'no tests collected')")
  else
    summary+=("$(printf 'FAIL  %-26s %s' "$name" "$detail")")
    failed=1
  fi
}
skip() { summary+=("$(printf 'skip  %-26s %s' "$1" "$2")"); }

# Counts from each runner's own summary line.
pytest_counts() { grep -E '[0-9]+ (passed|failed|error)' "$1" | tail -1 | sed -E 's/^=+ //; s/ =+$//; s/ in [0-9.]+s.*$//'; }
vitest_counts() { grep -E '^ +Tests +[0-9]+' "$1" | tail -1 | sed -E 's/^ +Tests +//'; }
playwright_counts() { grep -E '^ +[0-9]+ (passed|failed|flaky|skipped|did not run|interrupted)' "$1" | sed -E 's/^ +//; s/ \(.*\)$//' | paste -sd ', ' -; }

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
stores_up() { port_open 6389 && port_open 5433 && port_open 6380 && port_open 7233; }

run_logged() { # name, log file, command...
  local name="$1" log="$2"
  shift 2
  echo "== $name"
  "$@" >"$log" 2>&1
  local code=$?
  tail -3 "$log"
  return $code
}

# ------------------------------------------------------------------ backend
pytest_level() { # name, path
  local name="$1" path="$2"
  if [ ! -d "backend/$path" ] || [ -z "$(find "backend/$path" -name 'test_*.py' -print -quit 2>/dev/null)" ]; then
    summary+=("$(printf 'none  %-26s %s' "backend $name" "no test files in backend/$path")")
    return
  fi
  local log="$LOG_DIR/backend-$name.log" cov=()
  if [ "${SKIP_COVERAGE:-0}" != "1" ]; then
    cov=(--cov=actron --cov-append --cov-report=)
  fi
  run_logged "backend $name" "$log" bash -c "cd backend && uv run pytest $path -q -p no:cacheprovider --timeout 300 ${cov[*]:-}"
  record "backend $name" $? "$(pytest_counts "$log")"
}

if [ "${SKIP_BACKEND:-0}" != "1" ]; then
  export ACTRON_TEST_REDIS_DB="${ACTRON_TEST_REDIS_DB:-15}"
  run_logged "backend ruff" "$LOG_DIR/backend-ruff.log" bash -c "cd backend && uv run ruff check actron tests"
  record "backend ruff" $? "$(tail -1 "$LOG_DIR/backend-ruff.log")"
  run_logged "backend mypy" "$LOG_DIR/backend-mypy.log" bash -c "cd backend && uv run mypy actron"
  record "backend mypy --strict" $? "$(tail -1 "$LOG_DIR/backend-mypy.log")"
  rm -f backend/.coverage
  pytest_level unit        tests/unit
  pytest_level property    tests/property
  pytest_level integration tests/integration
  pytest_level contract    tests/contract
  pytest_level workflows   tests/workflows
  pytest_level api         tests/api
  pytest_level eval        tests/eval
  if [ "${SKIP_COVERAGE:-0}" != "1" ] && [ -f backend/.coverage ]; then
    (cd backend && uv run coverage report --skip-covered --skip-empty) >"$LOG_DIR/backend-coverage.log" 2>&1
    total="$(grep -E '^TOTAL' "$LOG_DIR/backend-coverage.log" | awk '{print $NF " of " $2 " statements"}')"
    summary+=("$(printf 'info  %-26s %s' "backend line coverage" "${total:-unknown}")")
  fi
fi

# ------------------------------------------------------------------ frontend
if [ "${SKIP_FRONTEND:-0}" != "1" ] && [ -f frontend/package.json ]; then
  run_logged "frontend typecheck" "$LOG_DIR/fe-typecheck.log" bash -c "cd frontend && npm run --silent typecheck"
  record "frontend typecheck" $? "tsc --noEmit"
  run_logged "frontend lint" "$LOG_DIR/fe-lint.log" bash -c "cd frontend && npm run --silent lint"
  record "frontend lint" $? "eslint --max-warnings 0"
  run_logged "frontend unit" "$LOG_DIR/fe-unit.log" bash -c "cd frontend && npm run --silent test:coverage"
  code=$?
  record "frontend unit" $code "$(vitest_counts "$LOG_DIR/fe-unit.log")"
  lines="$(grep -E '^Lines' "$LOG_DIR/fe-unit.log" | tail -1 | sed -E 's/^Lines +: //')"
  [ -n "$lines" ] && summary+=("$(printf 'info  %-26s %s' "frontend line coverage" "$lines (components and lib)")")

  run_logged "frontend fixture build" "$LOG_DIR/fe-fixture-build.log" bash -c "cd frontend && npm run --silent build:fixtures"
  code=$?
  if [ $code -ne 0 ]; then
    record "frontend fixture build" $code "see $LOG_DIR/fe-fixture-build.log"
  else
    run_logged "frontend e2e (fixtures)" "$LOG_DIR/fe-e2e-fixtures.log" bash -c "cd frontend && npx playwright test"
    record "frontend e2e (fixtures)" $? "$(playwright_counts "$LOG_DIR/fe-e2e-fixtures.log")"
  fi

  if [ "${SKIP_STACK_E2E:-0}" = "1" ]; then
    skip "frontend e2e (stack)" "SKIP_STACK_E2E=1"
  elif ! stores_up; then
    skip "frontend e2e (stack)" "stores are not running (make up-deps)"
  else
    scripts/e2e_stack.sh stop >/dev/null 2>&1
    run_logged "e2e stack start" "$LOG_DIR/e2e-stack-start.log" scripts/e2e_stack.sh start --build-frontend
    code=$?
    if [ $code -ne 0 ]; then
      record "frontend e2e (stack)" $code "the e2e stack did not start; see .actron/e2e/logs"
    else
      run_logged "frontend e2e (stack)" "$LOG_DIR/fe-e2e-stack.log" bash -c "cd frontend && npm run --silent test:e2e-stack"
      record "frontend e2e (stack)" $? "$(playwright_counts "$LOG_DIR/fe-e2e-stack.log")"
      cp -r .actron/e2e/logs "$LOG_DIR/e2e-stack-logs" 2>/dev/null
    fi
    scripts/e2e_stack.sh stop >/dev/null 2>&1
  fi

  if [ "${SKIP_LIGHTHOUSE:-0}" = "1" ]; then
    skip "frontend lighthouse" "SKIP_LIGHTHOUSE=1"
  elif ! port_open 3000 || ! port_open 8080; then
    skip "frontend lighthouse" "the compose frontend (:3000) and backend (:8080) are not running (make up)"
  else
    # Lighthouse CI needs a Chrome; use the one Playwright installed unless CHROME_PATH is set.
    if [ -z "${CHROME_PATH:-}" ]; then
      CHROME_PATH="$(cd frontend && node -e "console.log(require('@playwright/test').chromium.executablePath())" 2>/dev/null)"
      export CHROME_PATH
    fi
    jar="$LOG_DIR/lhci-cookies.txt"
    curl -fsS -c "$jar" -H 'Content-Type: application/json' -d '{"name":"Dev user"}' \
      http://127.0.0.1:8080/api/auth/dev-login >/dev/null 2>&1
    session="$(awk '$6 == "actron_session" {print $7}' "$jar" 2>/dev/null)"
    rm -f "$jar"
    # The compose frontend behind Caddy with production's compression, on :3400 (infra/lhci/Caddyfile).
    docker rm -f actron-lhci-proxy >/dev/null 2>&1
    docker run -d --rm --name actron-lhci-proxy --network host \
      -v "$ROOT/infra/lhci/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.10.2 >/dev/null 2>&1
    for _ in $(seq 1 30); do port_open 3400 && break; sleep 1; done
    scores() { # newest N reports in a folder -> "url perf/a11y/bp" list
      (cd "frontend/$1" && ls -t ./*.report.json 2>/dev/null | head -"$2" | xargs -r python3 -c '
import json, sys
for f in sys.argv[1:]:
    d = json.load(open(f)); c = d["categories"]; u = d["finalDisplayedUrl"].split(":3400")[-1]
    p = round(c["performance"]["score"] * 100); a = round(c["accessibility"]["score"] * 100)
    print(u, "P%d A%d" % (p, a), end="; ")')
    }
    run_logged "frontend lighthouse" "$LOG_DIR/fe-lighthouse.log" bash -c \
      "cd frontend && LHCI_SESSION='$session' npx lhci autorun --config=lighthouserc.json"
    record "frontend lighthouse desktop" $? "$(scores .lighthouseci 4)"
    run_logged "frontend lighthouse mobile" "$LOG_DIR/fe-lighthouse-mobile.log" bash -c \
      "cd frontend && npx lhci autorun --config=lighthouserc.mobile.json"
    record "frontend lighthouse mobile" $? "$(scores .lighthouseci/mobile 1)"
    docker rm -f actron-lhci-proxy >/dev/null 2>&1
  fi
fi

# ------------------------------------------------------------------ spec coverage
run_logged "spec coverage" "$LOG_DIR/spec.log" python3 scripts/spec_coverage.py --quiet
record "spec coverage" $? "$(awk 'NR > 1 && NF == 4 {printf "%s %s/%s covered; ", $1, $3, $2}' "$LOG_DIR/spec.log")"

elapsed=$(( $(date +%s) - started ))
{
  echo
  echo "================ summary ($(date -u +%Y-%m-%dT%H:%MZ), $((elapsed / 60)) min $((elapsed % 60)) s) ================"
  printf '%s\n' "${summary[@]}"
  echo "logs: $LOG_DIR"
  if [ "$failed" -ne 0 ]; then echo "RESULT: FAILED"; else echo "RESULT: PASSED"; fi
} | tee "$LOG_DIR/summary.txt"
exit "$failed"
