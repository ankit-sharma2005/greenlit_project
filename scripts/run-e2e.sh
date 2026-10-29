#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# Disposable end-to-end stack for the GreenLit Playwright suite. It brings up a
# fresh Postgres + Redis, applies migrations, starts the API, worker and web on
# host ports, then runs the whole suite against that stack and tears everything
# down afterwards. The suite's own Playwright process is `npm run e2e`.
#
# Host targets (used by the fake apps the tests start on the host):
#   E2E_API_BIND  - "localhost" / "0.0.0.0" (API listen address)
#   E2E_WEB_BIND - web listen address
#   E2E_DEMO_GOOD_PORT / E2E_DEMO_BROKEN_PORT - the two demo helpdesk servers
#
# The suite can also point at an already-running dev stack if E2E_BASE_URL and
# E2E_API_URL are set and the script is told to skip the local stack.

set -euo pipefail

if command -v winpty >/dev/null 2>&1; then
  SUDO=winpty
elif command -v sudo >/dev/null 2>&1; then
  SUDO=sudo
fi

ROOTDIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOTDIR"

E2E_BASE_URL="${E2E_BASE_URL:-http://localhost:5177}"
E2E_API_URL="${E2E_API_URL:-http://localhost:8003}"
E2E_API_BIND="${E2E_API_BIND:-0.0.0.0}"
E2E_WEB_BIND="${E2E_WEB_BIND:-0.0.0.0}"
API_PORT="${E2E_API_PORT:-8003}"
WEB_PORT="${E2E_WEB_PORT:-5177}"
DEMO_GOOD_PORT="${E2E_DEMO_GOOD_PORT:-9501}"
DEMO_BROKEN_PORT="${E2E_DEMO_BROKEN_PORT:-9502}"
export E2E_BASE_URL
export E2E_API_URL
export E2E_API_BIND
export E2E_WEB_BIND
export VITE_API_BASE_URL="http://localhost:${API_PORT}"

PYTHON="${PYTHON:-${ROOTDIR}/backend/runner/Scripts/python.exe}"
TESTS="${TESTS:-.}"

log() { echo "==> $*" >&2; }

cleanup() {
  log "Tearing down the disposable e2e stack"
  if [ -n "${COMPOSE_PID:-}" ]; then
    if kill -0 "$COMPOSE_PID" 2>/dev/null; then
      log "Stopping Docker Compose"
      kill "$COMPOSE_PID" 2>/dev/null || true
      wait "$COMPOSE_PID" 2>/dev/null || true
    fi
  fi
  log "Stopping host processes"
  for pid in "${PIDS[@]}"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT

if [ -z "${SKIP_STACK:-}" ]; then
  log "Bringing up the disposable stack (Postgres + Redis)"

  # The Compose file is the env-friendly version of the project's normal stack.
  COMPOSE_FILE="${ROOTDIR}/docker-compose.yml"
  if [ ! -f "$COMPOSE_FILE" ]; then
    COMPOSE_FILE="${ROOTDIR}/docker-compose.e2e.yml"
  fi

  if [ ! -f "$COMPOSE_FILE" ]; then
    echo "No docker-compose.yml found in ${ROOTDIR}; cannot start the local stack." >&2
    echo "Set SKIP_STACK=1 and provide E2E_BASE_URL / E2E_API_URL to target an existing stack." >&2
    exit 1
  fi

  "$SUDO" docker compose -f "$COMPOSE_FILE" up -d --wait --wait-timeout 120 >"${ROOTDIR}/e2e-docker.log" 2>&1 &
  COMPOSE_PID=$!
  log "Docker Compose starting in background (pid ${COMPOSE_PID})"

  # Give Compose time to pull and start Postgres/Redis
  for i in $(seq 1 90); do
    if grep -qi 'healthy\|started\|created' "${ROOTDIR}/e2e-docker.log" 2>/dev/null; then
      break
    fi
    sleep 2
  done

  log "Applying migrations to the fresh database"
  (cd backend && exec "$PYTHON" -m alembic upgrade head)

  # The demo helpdesk that "Try the demo" runs. This stack runs the API on the
  # host, so the two demo servers run here too (the same module Compose uses under
  # the `demo` profile) and the API is told where they are.
  export DEMO_APP_URL="http://127.0.0.1:${DEMO_GOOD_PORT}/chat"
  export DEMO_APP_BROKEN_URL="http://127.0.0.1:${DEMO_BROKEN_PORT}/chat"

  log "Starting the demo helpdesk on :${DEMO_GOOD_PORT} (good) and :${DEMO_BROKEN_PORT} (broken)"
  (cd backend && MODE=good exec "$PYTHON" -m uvicorn app.demo_server:app --host 0.0.0.0 --port "$DEMO_GOOD_PORT") \
    >"${ROOTDIR}/e2e-demo-good.log" 2>&1 &
  PIDS+=($!)
  (cd backend && MODE=broken exec "$PYTHON" -m uvicorn app.demo_server:app --host 0.0.0.0 --port "$DEMO_BROKEN_PORT") \
    >"${ROOTDIR}/e2e-demo-broken.log" 2>&1 &
  PIDS+=($!)

  log "Starting API on :${API_PORT}"
  (cd backend && exec "$PYTHON" -m uvicorn app.main:app --host "$E2E_API_BIND" --port "$API_PORT") \
    >"${ROOTDIR}/e2e-api.log" 2>&1 &
  PIDS+=($!)

  log "Starting web on :${WEB_PORT} (VITE_API_BASE_URL=http://localhost:${API_PORT})"
  (cd frontend && VITE_API_BASE_URL="http://localhost:${API_PORT}" exec npm run dev -- --host "$E2E_WEB_BIND" --port "$WEB_PORT") \
    >"${ROOTDIR}/e2e-web.log" 2>&1 &
  PIDS+=($!)

  log "Waiting for API and web to answer"
  for i in $(seq 1 60); do
    if curl -sf "http://localhost:${API_PORT}/healthz" >/dev/null 2>&1 && \
       curl -sf "http://localhost:${WEB_PORT}/" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -sf "http://localhost:${API_PORT}/healthz" >/dev/null; then
    echo "API did not become healthy; see ${ROOTDIR}/e2e-api.log" >&2
    exit 1
  fi
  if ! curl -sf "http://localhost:${WEB_PORT}/" >/dev/null; then
    echo "Web did not become healthy; see ${ROOTDIR}/e2e-web.log" >&2
    exit 1
  fi

  for demo_port in "$DEMO_GOOD_PORT" "$DEMO_BROKEN_PORT"; do
    for i in $(seq 1 60); do
      if curl -sf "http://localhost:${demo_port}/healthz" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    if ! curl -sf "http://localhost:${demo_port}/healthz" >/dev/null; then
      echo "The demo app on :${demo_port} did not become healthy; see ${ROOTDIR}/e2e-demo-*.log" >&2
      exit 1
    fi
  done
  log "Demo helpdesk ready at ${DEMO_APP_URL} and ${DEMO_APP_BROKEN_URL}"
fi

log "Running the whole Playwright suite against ${E2E_BASE_URL} (fresh database)"
cd frontend
npm run e2e -- --project="${TESTS}"

log "E2E suite finished. Logs:"
for f in "${ROOTDIR}"/e2e-*.log; do
  [ -f "$f" ] && echo "--- $f ---" && tail -n 30 "$f"
done
