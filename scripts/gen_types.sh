#!/usr/bin/env bash
# Refreshes the frontend API types from the backend OpenAPI document.
# 1. Fetch /api/openapi.json from a running backend ($ACTRON_API_URL, default http://127.0.0.1:${ACTRON_PORT:-8080});
# 2. otherwise build it in-process from actron.api.app (when that module exists).
# Writes frontend/lib/api/openapi.json, then runs openapi-typescript into frontend/lib/api/openapi.d.ts
# (the name frontend/package.json and ESLint use) and copies it to frontend/lib/api/schema.d.ts.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
API_URL="${ACTRON_API_URL:-http://127.0.0.1:${ACTRON_PORT:-8080}}"
OUT_DIR="frontend/lib/api"
SPEC="$OUT_DIR/openapi.json"
mkdir -p "$OUT_DIR"

if curl -fsS --max-time 5 "$API_URL/api/openapi.json" -o "$SPEC.tmp" 2>/dev/null; then
  echo "fetched OpenAPI from $API_URL"
elif [ -f backend/actron/api/app.py ]; then
  echo "backend not reachable at $API_URL; generating OpenAPI in-process"
  (cd backend && uv run python -c "
import json
from actron.api.app import app
print(json.dumps(app.openapi(), indent=2, sort_keys=True))
") > "$SPEC.tmp"
else
  echo "no running backend and backend/actron/api/app.py does not exist yet; nothing to generate" >&2
  exit 1
fi
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SPEC.tmp"
mv "$SPEC.tmp" "$SPEC"

BIN="frontend/node_modules/.bin/openapi-typescript"
if [ ! -x "$BIN" ]; then
  echo "openapi-typescript is not installed; run 'npm ci' in frontend first" >&2
  exit 1
fi
"$BIN" "$SPEC" -o "$OUT_DIR/openapi.d.ts"
cp "$OUT_DIR/openapi.d.ts" "$OUT_DIR/schema.d.ts"
echo "wrote $SPEC, $OUT_DIR/openapi.d.ts and $OUT_DIR/schema.d.ts"
