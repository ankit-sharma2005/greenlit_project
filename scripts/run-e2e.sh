#!/usr/bin/env bash
# Disposable end-to-end run: creates its own Postgres/Redis, runs the Playwright
# suite against locally started API/web/worker processes, then drops everything.
#
# It NEVER touches the dev docker stack (project `greenlit`): the datastore
# containers live in a separate compose project (`greenlit-e2e`) with their own
# ports and a fresh volume, so the first registered user is admin on a clean
# database and nothing you run in the browser is restarted or rebuilt.
#
# Usage: bash scripts/run-e2e.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$PWD"

PROJECT="greenlit-e2e"
export POSTGRES_PORT="${E2E_POSTGRES_PORT:-5536}"
export REDIS_PORT="${E2E_REDIS_PORT:-6482}"
API_PORT="${E2E_API_PORT:-8103}"
WEB_PORT="${E2E_WEB_PORT:-5277}"
export DATABASE_URL="postgresql+psycopg://greenlit:greenlit@localhost:${POSTGRES_PORT}/greenlit"
export REDIS_URL="redis://localhost:${REDIS_PORT}/0"
export WEB_ORIGIN="http://localhost:${WEB_PORT}"
export APP_ENV=development
export APP_SECRET_KEY="e2e-insecure-key-not-for-production"

# The fake app the auto-detect test starts lives on the host; a host-local API
# reaches it on 127.0.0.1. Override if you point E2E at a containerized API.
export E2E_BASE_URL="http://localhost:${WEB_PORT}"
export E2E_TARGET_HOST="${E2E_TARGET_HOST:-127.0.0.1}"

PY="$ROOT/backend/.venv/Scripts/python"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/bin/python"

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  docker compose -p "$PROJECT" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Starting disposable datastores (project $PROJECT, ports ${POSTGRES_PORT}/${REDIS_PORT})"
docker compose -p "$PROJECT" up -d postgres redis

echo "==> Waiting for Postgres"
until docker compose -p "$PROJECT" exec -T postgres pg_isready -U greenlit -d greenlit >/dev/null 2>&1; do
  sleep 1
done

echo "==> Applying migrations to the fresh database"
(cd backend && "$PY" -m alembic upgrade head)

echo "==> Starting API on :${API_PORT}"
(cd backend && exec "$PY" -m uvicorn app.main:app --port "$API_PORT") >"$ROOT/e2e-api.log" 2>&1 &
PIDS+=($!)

echo "==> Starting Celery worker"
(cd backend && exec "$PY" -m celery -A app.celery_app.celery worker --loglevel=INFO) \
  >"$ROOT/e2e-worker.log" 2>&1 &
PIDS+=($!)

echo "==> Starting web on :${WEB_PORT} (VITE_API_BASE_URL=http://localhost:${API_PORT})"
(cd frontend && VITE_API_BASE_URL="http://localhost:${API_PORT}" exec npm run dev -- --port "$WEB_PORT") \
  >"$ROOT/e2e-web.log" 2>&1 &
PIDS+=($!)

echo "==> Waiting for API and web to answer"
for _ in $(seq 1 60); do
  if curl -sf "http://localhost:${API_PORT}/healthz" >/dev/null 2>&1 &&
    curl -sf "http://localhost:${WEB_PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -sf "http://localhost:${API_PORT}/healthz" >/dev/null || {
  echo "API did not become healthy; see $ROOT/e2e-api.log" >&2
  exit 1
}
curl -sf "http://localhost:${WEB_PORT}/" >/dev/null || {
  echo "Web did not become healthy; see $ROOT/e2e-web.log" >&2
  exit 1
}

echo "==> Running Playwright against ${E2E_BASE_URL} (fresh database)"
cd frontend
npm run e2e
