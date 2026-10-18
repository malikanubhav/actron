#!/usr/bin/env bash
# Prepares the local settings file (.env) for a first start.
#   - copies .env.example to .env when .env does not exist
#   - fills ACTRON_SECRET_KEY and SESSION_SECRET with new random values, only when they are empty
# It never overwrites a value that is already set and never prints a secret.
# Safe to run again. Needs python3 or openssl (almost every Linux and macOS machine has one).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env.example ]; then
  echo "Cannot find .env.example. Run this script from a full copy of the Actron folder." >&2
  exit 1
fi

# A Fernet key is 32 random bytes, encoded as URL-safe base64 (44 characters).
fernet_key() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
    echo
  else
    echo "Need python3 or openssl to make a key. Install one of them and run this again." >&2
    exit 1
  fi
}

session_secret() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os; print(os.urandom(32).hex())'
  else
    openssl rand -hex 32
  fi
}

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env 2>/dev/null || true
  echo "Created .env from .env.example."
else
  echo ".env already exists. Keeping it."
fi

# Sets NAME to a new value only when the line is missing or its value is empty.
# A trailing "# comment" on an empty line counts as empty.
fill() {
  local name="$1" make_value="$2" current value tmp
  current="$(grep -E "^${name}=" .env | head -n1 || true)"
  value="${current#*=}"
  value="${value%%#*}"
  value="$(printf '%s' "$value" | tr -d '[:space:]"'"'")"
  if [ -n "$value" ]; then
    echo "$name is already set. Keeping it."
    return 0
  fi
  value="$($make_value)"
  if [ -z "$current" ]; then
    printf '%s=%s\n' "$name" "$value" >> .env
  else
    tmp="$(mktemp .env.XXXXXX)"
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        "${name}="*) printf '%s=%s\n' "$name" "$value" ;;
        *) printf '%s\n' "$line" ;;
      esac
    done < .env > "$tmp"
    chmod 600 "$tmp" 2>/dev/null || true
    mv "$tmp" .env
  fi
  echo "$name was empty. Filled it with a new random value."
}

fill ACTRON_SECRET_KEY fernet_key
fill SESSION_SECRET session_secret

echo
echo "Done. Next step: run  make up"
