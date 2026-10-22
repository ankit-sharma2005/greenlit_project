# GreenLit — Handover notes

> Living document. It is completed after M10 as required by the specification; this version
> reflects the repository as of M1 (accounts).

## How to run

```bash
cp .env.example .env      # optional; defaults work
docker compose up --build
```

| Service | URL | Container port | Host port (default) |
| --- | --- | --- | --- |
| Web UI | http://localhost:5177 | 5173 | `WEB_PORT=5177` |
| API | http://localhost:8003 | 8000 | `API_PORT=8003` |
| API docs | http://localhost:8003/docs | 8000 | `API_PORT=8003` |
| Postgres | `localhost:5436` | 5432 | `POSTGRES_PORT=5436` |
| Redis | `localhost:6382` | 6379 | `REDIS_PORT=6382` |

Ports are read from `.env`; updating `WEB_PORT`/`API_PORT` also requires updating
`WEB_ORIGIN` and `VITE_API_BASE_URL` because those are browser-facing. Internal compose
traffic keeps using the container ports.

## How to test

```bash
# backend
cd backend && ruff check . && ruff format --check . && mypy && pytest

# frontend
cd frontend && npm run lint && npm run format:check && npm run build && npm test
```

## Architecture (current)

- `backend/app`: FastAPI (sync SQLAlchemy 2 + psycopg 3), typed settings, single error
  envelope, health/readiness endpoints, accounts. Migrations `0001_initial` (pgcrypto) and
  `0002_accounts` (users, refresh_tokens, password_resets, audit_events).
- Auth: Argon2id passwords, 15-minute access JWT cookie, rotating 14-day hashed refresh token
  with family reuse detection, Redis login rate limit (fails open), RBAC and audit log.
  Password reset is API-only (no email provider): development returns `debug_token`.
- `backend/app/celery_app.py`: Celery wired to Redis; no tasks until M6.
- `frontend/src`: React 19 + TypeScript + Vite, React Router, CSS custom-property tokens
  (dark default/light theme), `Spinner`, `Button` (loading/slow label), `ProgressBar`,
  auth provider/route guard, login and register pages.
- `docker-compose.yml`: postgres, redis, api (migrates then serves), worker, web.

## Known limitations / next milestones

- Providers, connectors, datasets, runs, judges, safety, regression and reports are not
  built. They are visibly marked "Coming soon" in the UI and their milestones are recorded
  in `DECISIONS.md` and the build prompt.
- No email delivery, so password reset is only usable through the development `debug_token`.
- No UI for password reset, user administration or the audit log yet; those endpoints exist.
- Only containerised dev servers exist; no production build/deploy path yet.
- Playwright end-to-end tests arrive in M10.

## Coming soon connectors (registered but HTTP 501)

Python function, Built-in RAG app, Python SDK (traced), Docker image, Git repository,
CLI command, Proxy mode, Website URL, MCP server.
