#!/usr/bin/env bash
# Static checks: ruff and mypy --strict on the backend, typecheck and lint on the frontend, spec coverage.
# Usage: scripts/check.sh            (every check, exit 1 if any fails)
#        CHECK_ALLOW_GAPS=1 scripts/check.sh   (spec coverage gaps are reported but do not fail the run)
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

failures=()
results=()

step() {
  local name="$1"
  shift
  echo
  echo "== $name"
  if "$@"; then
    results+=("ok      $name")
  else
    results+=("FAILED  $name")
    failures+=("$name")
  fi
}

backend() { (cd backend && "$@"); }

step "backend ruff"      backend uv run ruff check actron tests
step "backend mypy"      backend uv run mypy actron

if [ -f frontend/package.json ]; then
  if [ ! -d frontend/node_modules ]; then
    echo "frontend/node_modules is missing; run 'npm ci' in frontend first" >&2
  fi
  step "frontend typecheck" bash -c 'cd frontend && npm run --silent typecheck'
  step "frontend lint"      bash -c 'cd frontend && npm run --silent lint'
else
  results+=("skipped frontend (no frontend/package.json)")
fi

if [ "${CHECK_ALLOW_GAPS:-0}" = "1" ]; then
  step "spec coverage (gaps allowed)" bash -c 'python3 scripts/spec_coverage.py || true'
else
  step "spec coverage" python3 scripts/spec_coverage.py
fi

echo
echo "== summary"
printf '%s\n' "${results[@]}"
if [ "${#failures[@]}" -gt 0 ]; then
  echo
  echo "check failed: ${failures[*]}"
  exit 1
fi
echo "all checks passed"
