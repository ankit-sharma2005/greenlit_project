# Decisions

Decisions are recorded here as they are made, with the simplest sensible option chosen
whenever the specification is silent.

## M0 — Foundation

### D0.1 Repository root is the app root
The spec suggested a `greenlit/` folder; the workspace *is* that folder, so `backend/`,
`frontend/`, `demo/`, `docs/` and the compose file live directly at the repository root.
This keeps `docker compose up --build` working from the folder the user unzips.

### D0.2 Logo source files were not present
The prompt says to copy `GreenLit_mark.png` and `GreenLit_logo_full_light_bg.png` into the
project root first. They are absent from this workspace, so the brand assets are
**generated programmatically** by `scripts/generate_brand_assets.py` (Pillow, no network):
a green ring-shaped "G" arm combined with a dark slate "L" and a glowing green dot. The
script writes the root PNGs, `frontend/public/` favicons (16, 32, 180, `favicon.ico`) and
`frontend/src/assets/greenlit-mark.png`. If the real artwork arrives later, drop it in and
re-run the script (it will be overwritten only when `--force` is passed).
Brand colours: green `#1ac03a`, dark slate `#28313a`, as CSS variables in
`frontend/src/styles/tokens.css`.

### D0.3 Database access style
Sync SQLAlchemy 2.0 with `psycopg` 3 (`postgresql+psycopg://`). The workload is ordinary
CRUD plus background jobs; async SQLAlchemy would add complexity without a measured need.
FastAPI endpoints that touch the database later in the project are plain `def` handlers so
the sync session runs in the threadpool. Alembic uses the same URL.

### D0.4 Migration baseline
`alembic/versions/0001_initial.py` creates the `pgcrypto` extension only. Domain tables
start arriving with M1 (accounts), so no speculative tables are added in M0. This gives a
real, runnable migration to prove the pipeline end to end.

### D0.5 Health endpoints
- `GET /healthz` — process liveness, no dependencies, always 200 while the process serves.
- `GET /readyz` — checks Postgres (`SELECT 1`) and Redis (`PING`), returns 200 with
  per-dependency status, or 503 when a dependency is down. Docker healthchecks use
  `/healthz` for the API and `pg_isready`/`redis-cli ping` for the datastores.

### D0.6 Error envelope from day one
A single exception handler emits `{"error": {"code", "message", "fields"}}` for every
HTTP error, so later milestones do not have to retrofit the contract. Internal exceptions
are logged and returned as `internal_error` without leaking details.

### D0.7 Worker container exists but has no tasks yet
`app/celery_app.py` configures Celery against Redis and the `worker` service starts it.
There are no task modules in M0; tasks arrive with M6 (runs).

### D0.8 Frontend stack
Vite + React 19 + TypeScript, React Router, plain CSS with custom properties. No UI
framework, as the spec permits. Theme is a `data-theme` attribute on `<html>` persisted in
`localStorage`; dark is the default. ESLint (flat config, typescript-eslint + react-hooks)
and Prettier enforce style; Vitest + Testing Library cover components.

### D0.9 Docker dev experience
`api` runs `uvicorn --reload` with `backend/` bind-mounted. `web` runs Vite dev with
`--host 0.0.0.0` and a bind mount for `frontend/`, but **no anonymous volume over
`node_modules`** (explicit pitfall in the spec); dependencies are baked at image build with
`npm ci`. `worker`, `api` and `web` get `extra_hosts: host.docker.internal:host-gateway`.

### D0.10 Not-yet-built features are visibly marked
The shell ships the four pages, but only the shell exists in M0. Panels that are not built
carry an explicit "Coming soon" tag instead of fake controls, per rule 3.

### D0.11 Slow actions announce themselves on the button
`Button` switches its accessible label and tooltip to "Still working…" after 10 s of loading
(exported as `SLOW_ACTION_MS`); the visible label stays hidden so the button keeps its width
and no layout jump occurs. The visible "still working" message belongs to the page-level
action that owns the button, not to the button itself. Tests cover the switch.

### D0.12 Tests run without Vitest globals
Vitest is configured with `globals: false`; `src/test/setup.ts` registers Testing Library
cleanup explicitly. This keeps component test files import-explicit and avoids the
"multiple elements found" failure caused by skipped cleanup.

### D0.13 Local port conflicts during verification
Other Docker projects on this machine already published 5173, 8000, 5432 and 6379 during
M0, so the first verification used a temporary override (5175/8002/5434/6381). That
situation is resolved permanently in D0.16.

### D0.16 Host ports are configurable and no longer clash
Host-side ports default to web **5177**, API **8003**, Postgres **5436** and Redis **6382**,
set from `WEB_PORT`, `API_PORT`, `POSTGRES_PORT` and `REDIS_PORT` with those defaults in
`docker-compose.yml`. The ports **inside** the containers stay 5173/8000/5432/6379, so
inter-service URLs (`postgres:5432`, `redis:6379`, healthchecks) are unchanged. CORS
(`WEB_ORIGIN`, default `http://localhost:5177`), the app settings defaults, and the browser
API base URL (`VITE_API_BASE_URL`, default `http://localhost:8003`) follow the host ports.
Playwright does not exist yet (M10) and there are no URL-bearing test configs to update;
the Vitest suite runs without host URLs. `HANDOVER.md` now records the ports for handover.

### D0.17 Frontend keeps its own dev port
Vite's in-container port stays 5173 and is published as `${WEB_PORT}`. When running the
frontend outside Docker, start it with `npm run dev -- --port 5177` so the browser origin
matches `WEB_ORIGIN`.

### D0.18 API base URL is available before the first API client
`VITE_API_BASE_URL` is declared in `.env.example` and passed to the `web` service so the M1
API client uses the host API port without touching the compose file.

## M1 — Accounts

### D1.1 Password hashing
Argon2id via `argon2-cffi` (default parameters). Verification never raises on malformed
hashes; it returns False so login keeps a generic error.

### D1.2 Session model
A short-lived access JWT (HS256, 15 min) and an opaque 64-byte refresh token (14 days) are
both set as httpOnly cookies. Refresh tokens are stored as SHA-256 hashes and rotate on every
refresh inside a family. Presenting a revoked token is treated as theft: the entire family is
revoked and the client gets 401. Only hashes are ever stored; access tokens are stateless so
their JWT `jti` is not tracked.

### D1.3 Cookie flags
`HttpOnly`, `SameSite=Lax`, `Path=/`. `Secure` comes from `COOKIE_SECURE` when set, otherwise
from the request scheme / `X-Forwarded-Proto`. Lax is enough because the UI and API share the
`localhost` site even on different ports; there is no cross-site embedding.

### D1.4 Login rate limiting
Redis fixed-window counter keyed by lower-cased email + client IP: 5 attempts / 15 minutes by
default. It fails open when Redis is unavailable — Argon2 verification remains the real gate,
and a cache outage must not lock every user out. Tests inject an in-memory limiter.

### D1.5 Password reset delivery
There is no mail provider in this milestone, so a development environment returns the reset
token as `debug_token` in the request response. Tokens are hashed, single-use and expire in 30
minutes; requesting a new one invalidates earlier unused tokens, and a completed reset revokes
all refresh tokens. Wiring email delivery (and removing `debug_token`) is required before
production.

### D1.6 RBAC and the last admin
The first registered account becomes `admin`; later registrations are `member`. Roles are
checked server-side by dependencies (`require_roles`). Admin user/audit endpoints return 403
for other roles. Demoting the last admin returns 409 so a workspace cannot lock itself out.

### D1.7 Test database
Backend integration tests use an in-memory SQLite database with the real models and the real
FastAPI app, with `get_db` and the rate limiter overridden. This keeps CI fast and hermetic;
Postgres-specific behaviour is covered by the migrated Compose stack in verification.

### D1.8 CORS with cookies
`allow_credentials=True` with explicit origins (`http://localhost:5177` by default). No
wildcard origins, because credentialed CORS forbids them. Tests assert allowed and rejected
origins.

### D1.9 Audit actions in M1
`auth.register`, `auth.sign_in`, `auth.sign_in_failed`, `auth.sign_out`,
`auth.refresh_reuse`, `auth.password_reset_requested`, `auth.password_reset_completed`,
`user.role_changed`. The table is append-only from the application: there is no update or
delete endpoint.

### D1.10 Frontend auth UX
The app shell is protected by `RequireAuth`, which shows the `xl` spinner while the session is
checked and redirects to `/login` with the intended path. Login and register pages use the
brand mark, labelled 44px inputs, `Button loading` and the API's plain-language errors. The
API client sends `credentials: "include"` to the base URL from `VITE_API_BASE_URL`.

### D1.11 Fast-refresh split
The auth context object/hook live in `auth/authContext.ts`; `AuthProvider.tsx` exports only a
component. Splitting keeps `react-refresh/only-export-components` clean (and Windows cannot
host `AuthContext.ts` next to `authContext.ts`).

### D0.14 Frontend mounts are file-level
`web` mounts `src`, `public`, `index.html`, `vite.config.ts` and `tsconfig.json` instead of
the whole `frontend/` directory, so image-installed `node_modules` is never hidden.

### D0.15 `.freebuff/` stays out of the repository
`.freebuff/` holds workspace metadata (including the build prompt) and is git-ignored.
