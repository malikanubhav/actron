#!/usr/bin/env bash
# One-server deploy: build images, migrate, start the production stack, check health.
# Usage: scripts/deploy.sh [path/to/.env]     (default: .env in the repository root)
# Needs infra/compose.prod.yaml. The .env is copied to infra/.env.prod next to it (mode 600, git-ignored).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SRC_ENV="${1:-$ROOT/.env}"
COMPOSE_FILE="infra/compose.prod.yaml"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${ACTRON_PORT:-8080}/api/health}"
TIMEOUT="${DEPLOY_HEALTH_TIMEOUT:-180}"

[ -f "$COMPOSE_FILE" ] || { echo "$COMPOSE_FILE does not exist yet" >&2; exit 1; }
[ -f "$SRC_ENV" ] || { echo "no env file at $SRC_ENV (copy .env.example and fill it in)" >&2; exit 1; }

install -m 600 "$SRC_ENV" infra/.env.prod
COMPOSE=(docker compose --env-file infra/.env.prod -f "$COMPOSE_FILE")

VERSION="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
export ACTRON_VERSION="$VERSION"
echo "== build ($VERSION)"
"${COMPOSE[@]}" build

echo "== stores and Temporal"
"${COMPOSE[@]}" up -d --wait --wait-timeout 180 falkordb postgres redis temporal

echo "== migrate"
"${COMPOSE[@]}" run --rm --no-deps backend alembic -c actron/db/alembic.ini upgrade head

echo "== start"
"${COMPOSE[@]}" up -d

echo "== health"
deadline=$((SECONDS + TIMEOUT))
until body="$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null)"; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "health check did not pass within ${TIMEOUT}s: $HEALTH_URL" >&2
    "${COMPOSE[@]}" ps >&2 || true
    exit 1
  fi
  sleep 3
done
echo "$body"
echo "deployed $VERSION"
