# GreenLit

Pre-launch testing and evaluation for LLM-powered applications. GreenLit tests the
**application** — its prompt, retrieval, tools and guardrails — and combines quality,
safety and operational checks into one decision: **GO / REVIEW / NO-GO**, with evidence and
suggested fixes.

> Status: M6 (runs), M8 (safety) and M7 (judge) are complete: accounts, providers, the three
> connectors, datasets, metrics/decision engine, worker-executed runs with live progress and
> cancel, the built-in safety module (a versioned attack set, a safe-prompt set,
> `attack_resisted` / `over_refusal`, and a hard-gate NO-GO on a critical failure), and the
> judge (saved judge profiles in Settings → Judge, per-answer scoring at temperature 0 with
> stored provenance, and REVIEW when the judge is unavailable or unsure). A run's verdict card
> shows which judge and rubric scored it, plus a dedicated Safety section. Regression and
> reports arrive in later milestones; anything not built yet is visibly marked "Coming soon".

## Quick start

Requirements: Docker Desktop (WSL2 on Windows) with Compose v2.

```bash
cp .env.example .env       # optional; compose has working defaults
docker compose up --build
```

Then open:

| Service  | URL                            |
| -------- | ------------------------------ |
| Web UI   | http://localhost:5177          |
| API      | http://localhost:8003          |
| API docs | http://localhost:8003/docs     |

Host ports are configurable through `.env` without editing the compose file:
`WEB_PORT` (5177), `API_PORT` (8003), `POSTGRES_PORT` (5436), `REDIS_PORT` (6382).
The ports inside the containers stay 5173, 8000, 5432 and 6379, so services keep talking to
each other on the internal ones. `WEB_ORIGIN` (CORS) and `VITE_API_BASE_URL` must follow the
host ports if you change them.

Health checks: `GET /healthz` (liveness) and `GET /readyz` (Postgres + Redis readiness).

Open the app and create the first account: it becomes the **admin**. Later accounts are
**members** unless an admin changes their role. Roles are `admin`, `member` and `reviewer`.

## Accounts and sessions

- Passwords are hashed with Argon2id. Sign-in is rate limited per email + IP address.
- Sessions use an httpOnly, SameSite=Lax access token (15 minutes) plus a rotating refresh
token (14 days). The refresh token is stored hashed in Postgres; replaying a rotated token
revokes the whole token family. Cookies get `Secure` automatically over HTTPS.
- Admins can list users, change roles and read the append-only audit log. The last admin
cannot be demoted.
- Password reset creates a hashed, single-use token. **No email provider is configured yet**, so
in development (APP_ENV=development or DEBUG=true) the API returns `debug_token` from
`POST /api/v1/auth/password-reset/request`; production needs an email integration.

The `debug_token` is only returned when `APP_ENV=development` or `DEBUG=true`;
it is never returned in production.

Auth endpoints: `POST /api/v1/auth/register`, `/login`, `/refresh`, `/logout`,
`/password-reset/request`, `/password-reset/confirm`, and `GET /api/v1/auth/me`. Admin
endpoints: `GET /api/v1/users`, `PATCH /api/v1/users/{id}/role`, `GET /api/v1/audit`.

## Repository layout

```
backend/    FastAPI app, SQLAlchemy, Alembic migrations, tests
frontend/   React + TypeScript + Vite UI
demo/       Built-in demo app and sample data (later milestone)
docs/       Documentation, brand assets
scripts/    Developer utilities (brand asset generation)
```

## Local development without Docker

Backend:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm ci
npm run dev -- --port 5177
```

Run the API outside Docker against the Compose datastores (host ports 5436 and 6382) with
the defaults already in `app/config.py`, or point `DATABASE_URL`/`REDIS_URL` at them.

## Quality checks

```bash
# backend
cd backend && ruff check . && ruff format --check . && mypy && pytest

# frontend
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

### End-to-end tests

```bash
bash scripts/run-e2e.sh
```

The script creates a **disposable** stack and drops it afterwards, so it never restarts or
rebuilds the docker stack you use in the browser:

- Postgres + Redis run in their own compose project (`greenlit-e2e`) on ports 5536/6482 with
  a fresh volume — the e2e database is empty every run, so the first registered user is
  asserted to be `admin` on that clean database;
- the API (8103), Celery worker and Vite dev server (5277) start as local processes and are
  killed on exit;
- two demo helpdesk servers (healthy on 9501, broken on 9502) start the same way, since the
  disposable stack runs the API on the host and "Try the demo" needs somewhere to point;
- Playwright runs the whole suite in `frontend/tests` (`e2e-admin`, `e2e-demo`, `e2e-judge`,
  `e2e-prompt-app`, `e2e-safety`, `e2e-upload-outputs`) against `http://localhost:5277`
  (`E2E_BASE_URL`), then the script tears the project down with `docker compose down -v`.

To run the suite against an already-running dev stack instead:

```bash
cd frontend && npm run e2e   # defaults to http://localhost:5177
```

CI runs the same commands on every push (see `.github/workflows/ci.yml`).

## Run GreenLit in CI

Everything works through the API alone. `POST /api/v1/quick-test` creates what a test needs
(connector settings, dataset, approved version and the run) and returns the run id at once;
the Celery worker executes the cases and `GET /api/v1/runs/{id}` returns the stored verdict.

```bash
API=http://localhost:8003
JAR=$(mktemp)

# 1. Sign in (register first on a fresh database).
curl -sS -c "$JAR" -H 'Content-Type: application/json' \
  -d '{"email":"ci@example.com","password":"correct horse battery"}' \
  "$API/api/v1/auth/login"

# 2. Start a test. Send `csv` (question,answer columns) or `dataset_id` to skip generation.
RUN=$(curl -sS -b "$JAR" -H 'Content-Type: application/json' \
  -d '{"entry_point":"http_endpoint","target":"http://localhost:9000/chat","tests":["quality","operations"],"csv":"question,answer\nHow do I reset my password?,Use the reset link on the sign-in page.\n"}' \
  "$API/api/v1/quick-test" | python -c 'import json,sys; print(json.load(sys.stdin)["run"]["id"])')

# 3. Poll until the worker finishes (live counters: /api/v1/runs/$RUN/progress).
for _ in $(seq 1 120); do
  curl -sS -b "$JAR" "$API/api/v1/runs/$RUN" > /tmp/greenlit-run.json
  grep -qE '"state":"(completed|cancelled|failed)"' /tmp/greenlit-run.json && break
  sleep 1
done

# 4. Fail the pipeline on anything but GO.
python -c 'import json,sys; run=json.load(open("/tmp/greenlit-run.json")); print(run["verdict"], run["score"], run["verdict_reason"]); sys.exit(0 if run["verdict"] == "GO" else 1)'
```

## Brand assets

The logo mark and favicons are generated by `scripts/generate_brand_assets.py`
(Pillow). See [DECISIONS.md](DECISIONS.md) for why they are generated rather than copied.

![GreenLit](docs/greenlit-logo.png)

## Decisions

Product and engineering decisions are recorded in [DECISIONS.md](DECISIONS.md).
