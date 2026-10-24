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

## M4a — Datasets (upload, column detection, versioning)

### D4.1 XLSX parsing uses openpyxl
XLSX is a required upload format, so `openpyxl` (plus `types-openpyxl` for mypy) was added
instead of hand-rolling the zip/XML format. pandas would be far heavier than the job needs.

### D4.2 Services add to the caller's transaction
Matching the audit helper: `create_dataset` / `add_dataset_version` flush but never commit;
the API layer (M4b) or the test commits. This keeps one transaction per request.

### D4.3 Column detection is two-pass with strict required roles
Pass 1 matches exact column names case-insensitively per role (input, output, id,
retrieved_context, latency_ms, tokens_in, tokens_out, in priority order); pass 2 accepts a
substring match over columns no role claimed. `input` and `output` are required — otherwise
the upload fails with `missing_columns` and the available columns are listed. Explicit user
overrides are validated strictly (naming a column that does not exist is an error).

### D4.4 Version 1 is created at upload; later versions must keep the mapped columns
`create_dataset` parses the file, stores the bytes and SHA-256 hash, and writes the mapping,
version 1 and the items in one transaction. `add_dataset_version` appends version N+1 with
its own hash/row count/column snapshot and items, and bumps the dataset's stored bytes.
A new version must contain the dataset's canonical required columns: the per-dataset mapping
is single and is not re-detected or overridable per version (a re-upload with different
columns belongs to a new dataset). Optional mapped columns absent from a new file are
dropped quietly.

### D4.5 `raw_content` never leaves the database
Upload responses are `DatasetRead` schemas that omit the bytes entirely; the columns exist
only for re-export and hashing.

### D4.6 Dataset endpoints are owner-scoped
`POST /api/v1/datasets` (multipart: file + name + optional JSON `column_overrides`),
`GET /api/v1/datasets` (paginated, newest first), `GET /api/v1/datasets/{id}` and
`GET /api/v1/datasets/{id}/versions`. Datasets are personal: every query filters by the
signed-in user and a missing or foreign dataset returns 404 so existence never leaks (even
for admins; dataset administration, if ever needed, arrives with a spec that asks for it).
`DatasetError` maps to the single error envelope: `duplicate_name` -> 409, everything else
-> 400, malformed `column_overrides` -> 422, files over 10 MB -> 413. `python-multipart` was
added as a dependency for the upload form.

### D4.7 Dataset lifecycle writes audit events
The endpoints append `dataset.upload`, `dataset.version_added` and `dataset.delete` events
through the existing audit helper, in the same transaction as the change (a failed upload
records nothing). The spec only mandates auditing for dataset *approval* (M4b); recording
the rest now is cheap and makes the append-only trail complete.

### D4.8 Dataset approval (M4b)
Migration `0005_dataset_approval` adds nullable `approved_by` (FK users, `SET NULL`) and
`approved_at` to `dataset_versions`. `POST /api/v1/datasets/{id}/versions/{no}/approve`
marks one version approved, once: re-approving is a 409 (`already_approved`), an unknown
version is a 404 (`version_not_found`). The dataset's owner approves — datasets are personal
in this design, so there is no separate approver role yet. Approval is audited as
`dataset.approved` (the event the spec requires). Runs (M6) may only use approved versions.

### D4.9 Generated test cases and preview (M4b)
Migration `0006_generated_flag` adds `generated` (bool, default false) to
`dataset_versions` — a version-level flag rather than a per-item tag, since generated
versions always contain only generated cases. `POST /api/v1/datasets/{id}/generate`
(provider_id, count 1-100 default 20, optional source_text) asks the provider for a JSON
array of `{question, answer, context, category}` cases (one retry on invalid JSON, per the
spec's judge rules) and stores them as a new *draft* version whose SHA-256 hash is computed
from the canonical case JSON; `GET .../versions/{no}/items` is the preview. Drafts are
approved through the existing approve endpoint, so "preview then approve" needs no extra
state. The model call is resolved through a `get_chat_fn` FastAPI dependency so tests
(and later the demo path) can swap it; provider failures map to 502 `generation_failed`.

### D4.10 LLMGateway (spec section 6)
All model calls go through `app/services/llm_gateway.py`: `chat(provider, messages,
temperature, max_tokens)` applies the provider's timeout, retries 429/5xx/timeouts with
exponential backoff (`backoff_factor * 2**attempt`, capped at 30 s, `max_retries` tries),
never retries 4xx, and enforces `rate_limit_per_minute` (default 30) through the existing
Redis `RateLimiter`, which fails open. `tokens_per_minute` is stored for display but not
enforced pre-call: a trustworthy limit needs a model-specific tokenizer before the request
exists. Generation now uses the gateway; `get_chat_fn` builds it with the request's rate
limiter, so tests still swap the chat call wholesale.

## M6a — Runs: models, migration, repository

### D6.1 Run tables and state storage
Migration `0008_runs` adds `runs`, `run_items` and `metric_results`. States are stored
as plain `String(20)` values with `RunState` / `RunItemState` str-enums as the single
source of truth (`queued, running, cancelling, cancelled, failed, completed` for runs;
items have no `cancelling`). `runs` carries the spec-8.1 fields: `settings_snapshot`
(connector + judge + thresholds JSON), `verdict`, `score`, `verdict_reason` and
`is_partial`, plus nullable `started_at` / `completed_at` and FKs to the dataset version
the run was built from (both dataset FKs are `SET NULL` so deleting a dataset never
deletes run history). `metric_results` is keyed by run and optionally by item (NULL =
run-level aggregate) and stores `instrumented` so M5 metrics that were not measurable
stay excluded from the score instead of reading as 0.

### D6.2 Repository convention
`app/services/run_repository.py` follows the dataset/audit convention: functions take an
open session and flush only — the caller owns the transaction. Updates go through field
whitelists and state validation, so a typo raises `RepositoryError` instead of silently
setting an unknown attribute; transition legality (queued → running → completed) is left
to the worker in M6b.
