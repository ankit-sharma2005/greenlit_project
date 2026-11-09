#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# Disposable end-to-end stack for the GreenLit Playwright suite. It brings up a
# fresh Postgres + Redis, applies migrations, starts the API, worker and web on
# host ports, runs Playwright and the live CI-runner check, then stops the
# containers while preserving the database volume.
#
# Host targets (used by the fake apps the tests start on the host):
#   E2E_API_BIND  - "localhost" / "0.0.0.0" (API listen address)
#   E2E_WEB_BIND - web listen address
#   E2E_DEMO_GOOD_PORT / E2E_DEMO_BROKEN_PORT - the two demo helpdesk servers
#
# The suite can also point at an already-running dev stack if E2E_BASE_URL and
# E2E_API_URL are set and the script is told to skip the local stack.

set -euo pipefail

ROOTDIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOTDIR"

# Every port here is deliberately different from the dev stack in
# docker-compose.yml (5436/6382/8003/5177), so a run never touches it.
API_PORT="${E2E_API_PORT:-8103}"
WEB_PORT="${E2E_WEB_PORT:-5277}"
PG_PORT="${E2E_POSTGRES_PORT:-5536}"
REDIS_PORT="${E2E_REDIS_PORT:-6482}"
DEMO_GOOD_PORT="${E2E_DEMO_GOOD_PORT:-9501}"
DEMO_BROKEN_PORT="${E2E_DEMO_BROKEN_PORT:-9502}"
REFUSAL_PORT="${E2E_REFUSAL_PORT:-9503}"
# The adversarial spec starts its own "evil" counter on this port; a leftover
# server there would make "zero requests reached it" meaningless, so it is checked.
EVIL_PORT="${E2E_EVIL_PORT:-9504}"
E2E_BASE_URL="${E2E_BASE_URL:-http://localhost:${WEB_PORT}}"
E2E_API_URL="${E2E_API_URL:-http://localhost:${API_PORT}}"
E2E_API_BIND="${E2E_API_BIND:-0.0.0.0}"
E2E_WEB_BIND="${E2E_WEB_BIND:-0.0.0.0}"
COMPOSE_PROJECT="greenlit-e2e-${$}-$(date +%s)"

export E2E_BASE_URL
export E2E_API_URL
export E2E_API_BIND
export E2E_WEB_BIND
export VITE_API_BASE_URL="http://localhost:${API_PORT}"
export E2E_REFUSAL_URL="http://127.0.0.1:${REFUSAL_PORT}"
export E2E_EVIL_PORT="${EVIL_PORT}"
# The check panel is only offered for a target that is not "on my computer",
# so its spec reaches the same server through the host's own name (the API runs
# on this host, and the demo servers are bound the same way).
export E2E_REFUSAL_CHECK_URL="http://host.docker.internal:${REFUSAL_PORT}"

# The API, worker and migrations all run from backend/ on the host, so they need
# the e2e datastores rather than the dev ones. Real environment beats the .env
# file, so these win over whatever backend/.env holds.
export DATABASE_URL="postgresql+psycopg://greenlit:greenlit@localhost:${PG_PORT}/greenlit"
export REDIS_URL="redis://localhost:${REDIS_PORT}/0"
export WEB_ORIGIN="http://localhost:${WEB_PORT}"
export APP_ENV="development"

PYTHON="${PYTHON:-${ROOTDIR}/backend/runner/Scripts/python.exe}"
# One spec file (or a Playwright filter) can be passed as the first argument:
#   bash scripts/run-e2e.sh tests/e2e-baseline.spec.ts
TESTS="${1:-${TESTS:-.}}"

PIDS=()

log() { echo "==> $*" >&2; }

# Only this invocation's uniquely named e2e project is stopped. Its named
# volumes are intentionally preserved, and the dev stack is never mentioned.
cleanup() {
  log "Stopping host processes"
  for pid in "${PIDS[@]:-}"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true

  if [ -z "${SKIP_STACK:-}" ] && [ -n "${COMPOSE_FILE:-}" ]; then
    log "Stopping the disposable ${COMPOSE_PROJECT} stack (preserving volumes)"
    docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" down --remove-orphans \
      >>"${ROOTDIR}/e2e-docker.log" 2>&1 || true
  fi
}
trap cleanup EXIT

if [ -z "${SKIP_STACK:-}" ]; then
  log "Bringing up the disposable stack (Postgres + Redis, project ${COMPOSE_PROJECT})"

  # Only the datastores: docker-compose.e2e.yml has no api/worker/web services,
  # so this can never rebuild or restart the stack used in the browser.
  COMPOSE_FILE="${ROOTDIR}/docker-compose.e2e.yml"

  if [ ! -f "$COMPOSE_FILE" ]; then
    echo "No docker-compose.e2e.yml found in ${ROOTDIR}; cannot start the local stack." >&2
    echo "Set SKIP_STACK=1 and provide E2E_BASE_URL / E2E_API_URL to target an existing stack." >&2
    exit 1
  fi

  E2E_POSTGRES_PORT="$PG_PORT" E2E_REDIS_PORT="$REDIS_PORT" \
    docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" up -d --wait --wait-timeout 180 \
    >>"${ROOTDIR}/e2e-docker.log" 2>&1 || {
      echo "The e2e datastores did not become healthy; see ${ROOTDIR}/e2e-docker.log" >&2
      tail -n 30 "${ROOTDIR}/e2e-docker.log" >&2
      exit 1
    }

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

  # Sites that refuse a request (403/429, CSRF, a challenge page), served from
  # the same shapes the backend tests use: the browser proof needs a real
  # server answering, not a stub inside the page.
  log "Starting the refusal server on :${REFUSAL_PORT}"
  if curl -sf "http://127.0.0.1:${REFUSAL_PORT}/_health" >/dev/null 2>&1; then
    echo "Refusal port ${REFUSAL_PORT} is already in use; set E2E_REFUSAL_PORT." >&2
    exit 1
  fi
  (cd backend && exec "$PYTHON" tests/support/refusal_server.py --port "$REFUSAL_PORT" --host 0.0.0.0) \
    >"${ROOTDIR}/e2e-refusal.log" 2>&1 &
  PIDS+=($!)
  for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${REFUSAL_PORT}/_health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -sf "http://127.0.0.1:${REFUSAL_PORT}/_health" >/dev/null; then
    echo "The refusal server did not become healthy; see ${ROOTDIR}/e2e-refusal.log" >&2
    tail -n 30 "${ROOTDIR}/e2e-refusal.log" >&2
    exit 1
  fi

  if curl -s -o /dev/null "http://127.0.0.1:${EVIL_PORT}/" 2>/dev/null; then
    echo "Evil-counter port ${EVIL_PORT} is already in use; set E2E_EVIL_PORT." >&2
    exit 1
  fi

  log "Starting API on :${API_PORT}"
  (cd backend && exec "$PYTHON" -m uvicorn app.main:app --host "$E2E_API_BIND" --port "$API_PORT") \
    >"${ROOTDIR}/e2e-api.log" 2>&1 &
  PIDS+=($!)

  # Runs never leave `queued` without a worker, and the prefork pool cannot take
  # tasks on Windows (billiard semaphores fail with PermissionError), so the host
  # worker uses solo. See DECISIONS.md D6.7.
  log "Starting the Celery worker (--pool=solo)"
  (cd backend && exec "$PYTHON" -m celery -A app.celery_app.celery worker --loglevel=INFO --pool=solo) \
    >"${ROOTDIR}/e2e-worker.log" 2>&1 &
  PIDS+=($!)

  log "Starting web on :${WEB_PORT} (VITE_API_BASE_URL=http://localhost:${API_PORT})"
  (cd frontend && VITE_API_BASE_URL="http://localhost:${API_PORT}" exec node node_modules/vite/bin/vite.js --host "$E2E_WEB_BIND" --port "$WEB_PORT") \
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
  if grep -q "Port ${WEB_PORT} is already in use" "${ROOTDIR}/e2e-web.log"; then
    echo "Web port ${WEB_PORT} is already in use; choose another E2E_WEB_PORT." >&2
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

  # A worker that dies on startup would turn every run into a timeout, so fail
  # here with the log rather than 90 seconds later inside a test.
  for i in $(seq 1 30); do
    if grep -q 'ready' "${ROOTDIR}/e2e-worker.log" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if ! grep -q 'ready' "${ROOTDIR}/e2e-worker.log" 2>/dev/null; then
    echo "The Celery worker did not become ready; see ${ROOTDIR}/e2e-worker.log" >&2
    tail -n 30 "${ROOTDIR}/e2e-worker.log" >&2
    exit 1
  fi
fi

log "Running Playwright tests (${TESTS}) against ${E2E_BASE_URL} (fresh database)"
cd frontend
if [ "$TESTS" = "." ]; then
  npm run e2e
else
  npm run e2e -- "$TESTS"
fi

if [ -z "${SKIP_STACK:-}" ]; then
  log "Checking the GreenLit CI runner against the healthy demo app"
  (
    cd "${ROOTDIR}/backend"
    GREENLIT_CI_E2E_API_URL="$E2E_API_URL" \
      GREENLIT_CI_E2E_TARGET="$DEMO_APP_URL" \
      "$PYTHON" -m pytest -q tests/test_greenlit_ci_e2e.py
  )
fi

log "E2E suite finished. Logs:"
for f in "${ROOTDIR}"/e2e-*.log; do
  # Skip this script's own output: tailing it would copy itself into itself.
  case "$f" in
    */e2e-run*.log) continue ;;
  esac
  [ -f "$f" ] && echo "--- $f ---" && tail -n 30 "$f"
done
