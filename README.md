# GreenLit

GreenLit is an offline pre-launch evaluation platform for LLM-powered applications.
The current work covers the foundation plus the initial provider, project, and
connector setup flow.

## Quick start

1. Copy `.env.example` to `.env` and set local secrets (PowerShell: `Copy-Item .env.example .env`).
2. Run `docker compose up --build`.
3. Open `http://localhost:5173` for the web app and `http://localhost:8000/docs` for the API docs.

Compose waits for PostgreSQL and Redis before starting the API, then waits for the
API readiness check before starting the web app. The readiness check verifies a
database connection. Use `docker compose ps` to inspect service health and
`docker compose down` to stop the stack without deleting the database volume.

The login and signup screens use the API at `VITE_API_URL` (default:
`http://localhost:8000`). Access tokens remain in memory; refresh tokens are
sent as httpOnly cookies and rotated by `POST /api/v1/auth/refresh`. In
development, password-reset instructions are printed to the API console. For
SMTP delivery, set `SMTP_HOST` and `SMTP_FROM_EMAIL`; optionally set
`SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_PORT`.

## Stack
- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, Celery
- Frontend: React + TypeScript + Vite + CSS design system

## Roadmap status

Phase 1 is DONE. It delivers the app shell, authentication, workspaces, RBAC,
audit events, migrations, Compose stack, and verified dark/light and keyboard
navigation behavior. The UI smoke check is not a full WCAG accessibility audit.

The web shell supports API-backed signup, login, session restoration, workspace
listing, logout, and password reset. Password reset uses a one-time expiring token,
stored hashed, and invalidates existing refresh sessions. Workspace role checks use
the user's role in that workspace membership. Alembic has an initial schema migration
and Compose applies it before starting the API.

Phase 2 is complete with documented limitations. Provider configurations (GitHub
Models, Ollama, and custom OpenAI-compatible endpoints), workspace projects, app
versions, judge profiles, connector validation/test calls, secret encryption,
trace responses, Prompt App, built-in RAG and Agent, and the 13-type entry-point
registry are implemented. Connector configurations require a successful matching
test call before they can be saved. Python Function and Python SDK Traced are
disabled until a safe isolated execution runner is available; arbitrary user
Python is not executed.

The backend suite has 19 passing tests. Ruff, strict mypy, all configured
pre-commit hooks, ESLint, Prettier, frontend typecheck, and production build pass.
The provider rate limiter is process-local, so limits are not persisted across
restarts or coordinated across multiple API processes. Provider connection and
RAG tests use mocked provider responses; configure real credentials/endpoints to
test external providers. See [Phase 2 evidence and limitations](docs/PROGRESS.md).
Phase 3 has not started and requires explicit approval.

### Local checks

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Push-Location backend
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy --strict app alembic tests
.\.venv\Scripts\python.exe -m pytest -q tests
Pop-Location
npm ci --prefix frontend
npm --prefix frontend run lint
npm --prefix frontend run format:check
npm --prefix frontend run typecheck
npm --prefix frontend run build
$env:PATH = (Resolve-Path 'backend\.venv\Scripts').Path + ';' + $env:PATH
.\backend\.venv\Scripts\python.exe -m pre_commit validate-config
.\backend\.venv\Scripts\python.exe -m pre_commit run --all-files
```

Install the repository hooks with
`.\backend\.venv\Scripts\python.exe -m pre_commit install`.
