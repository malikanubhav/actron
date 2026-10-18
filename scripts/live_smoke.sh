#!/usr/bin/env bash
# Runs `pytest -m live` for each provider whose key is present in .env, and says which ran.
# Keys are read from .env without printing them. Providers without a key are reported as skipped.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

has_key() { # true when VAR=<non-empty> is in .env or the environment
  local var="$1" value=""
  if [ -f "$ENV_FILE" ]; then
    value="$(grep -E "^${var}=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r')"
  fi
  [ -n "$value" ] || [ -n "${!var:-}" ]
}

load_env() { # exports KEY=value lines of .env without sourcing it (values may contain spaces)
  local line key value
  [ -f "$ENV_FILE" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    key="${line%%=*}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    value="${line#*=}"
    value="${value%$'\r'}"
    case "$value" in \"*|\'*) ;; *) value="${value%%[[:space:]]#*}"; value="${value%"${value##*[![:space:]]}"}" ;; esac # inline comment
    case "$value" in \"*\") value="${value:1:${#value}-2}" ;; \'*\') value="${value:1:${#value}-2}" ;; esac
    export "$key=$value"
  done < "$ENV_FILE"
}

ran=()
skipped=()
failed=()

run_provider() { # name, test file, key vars...
  local name="$1" file="$2"
  shift 2
  local present=0 var
  for var in "$@"; do
    if has_key "$var"; then present=1; fi
  done
  if [ "$present" -ne 1 ]; then
    skipped+=("$name (no $*)")
    return
  fi
  if [ ! -f "backend/$file" ]; then
    skipped+=("$name (backend/$file does not exist yet)")
    return
  fi
  echo "== live: $name"
  if (cd backend && load_env; uv run pytest "$file" -m live -q -p no:cacheprovider); then
    ran+=("$name: passed")
  else
    ran+=("$name: FAILED")
    failed+=("$name")
  fi
}

run_provider models tests/live/test_models_live.py GEMINI_API_KEY DEEPSEEK_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GROQ_API_KEY
run_provider github tests/live/test_github_live.py GITHUB_TOKEN
run_provider slack  tests/live/test_slack_live.py  SLACK_BOT_TOKEN
run_provider linear tests/live/test_linear_live.py LINEAR_API_KEY
run_provider jev    tests/live/test_jev_live.py    TYPESAFE_API_KEY
run_provider pi     tests/live/test_pi_live.py     ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY GROQ_API_KEY DEEPSEEK_API_KEY

echo
echo "================ live smoke ================"
if [ "${#ran[@]}" -gt 0 ]; then printf 'ran      %s\n' "${ran[@]}"; else echo "ran      nothing (no provider key in $ENV_FILE)"; fi
if [ "${#skipped[@]}" -gt 0 ]; then printf 'skipped  %s\n' "${skipped[@]}"; fi
[ "${#failed[@]}" -eq 0 ]
