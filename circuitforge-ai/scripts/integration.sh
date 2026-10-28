#!/usr/bin/env bash
# Starts the real backend on a temporary migrated SQLite DB and runs the frontend integration test against it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; TMP="$(mktemp -d)"; PORT="${PORT:-8799}"
export DATABASE_URL="sqlite:///$TMP/cf.db" ARTIFACT_DIR="$TMP/art" PYTHONPATH="$ROOT/backend"
cd "$ROOT/backend" && alembic upgrade head >/dev/null
uvicorn app.main:app --port "$PORT" >"$TMP/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 0.5; done
cd "$ROOT/frontend" && CF_API="http://127.0.0.1:$PORT" npx vitest run src/tests/integration.test.tsx
