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
Other Docker projects on this machine already publish 5173, 8000, 5432 and 6379. M0 was
verified with a temporary compose override that published 5175/8002/5434/6381 and is not
committed; the repository keeps the specified default ports. On a machine where those ports
are taken, stop the conflicting containers or adjust the port mappings.

### D0.14 Frontend mounts are file-level
`web` mounts `src`, `public`, `index.html`, `vite.config.ts` and `tsconfig.json` instead of
the whole `frontend/` directory, so image-installed `node_modules` is never hidden.

### D0.15 `.freebuff/` stays out of the repository
`.freebuff/` holds workspace metadata (including the build prompt) and is git-ignored.
