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

## M6c — Runs: API, quick test and the browser flow

### D6.3 The API queues, it never executes
`POST /api/v1/runs` validates the connector settings, stores the settings snapshot and
creates the run in `queued`, then hands the id to Celery (`app.tasks.run_test`) and returns
202 with the run. Nothing runs in the request: the tests assert the queue seam was called
once and that the run has no items yet. The queue is a FastAPI dependency
(`get_enqueue`), so tests inject a list instead of a broker, and progress is read through
`get_progress_reader` (Redis in production, an injected dict in tests). Unknown or
not-yet-approved datasets, a missing URL, an unknown criteria profile and an empty test
list are rejected before queueing with a message that names the next action.

### D6.4 Cancel semantics
Cancel is a state flip, not a process kill. A `queued` run is moved straight to
`cancelled` (is_partial, reason "cancelled before it started") and the worker task that
arrives later skips it. A `running` run goes to `cancelling`: the executor checks that
state before taking each new case, keeps the finished items, stores the verdict it can
compute and labels the run partial. `cancelling` is idempotent; a finished run returns 409
rather than pretending to cancel.

### D6.5 One quick test for CI
`POST /api/v1/quick-test` takes `{entry_point, target, tests}` plus an optional `csv`,
`dataset_id` or `generate` count. It creates the dataset (from the CSV, or by asking the
provider for cases and tagging the version `generated`), approves version 1, snapshots the
connector shape auto-detect found (`body_template`, `answer_path`, `context_path` — never a
hard-coded body) and starts the run. Without a provider and without a CSV it answers 400
with the two ways forward, instead of generating silently or faking cases.

### D6.6 The New Test page
Start test runs auto-detect and shows the detected request shape, answer path, context
path and the real response (unchanged from M3). A second step, *Run test*, picks an
approved dataset version or falls back to generating cases, then polls
`GET /api/v1/runs/{id}` every 1.5 s until the run is terminal. The verdict panel shows the
engine's own reason plus the metric table and failed cases; Cancel posts to
`/runs/{id}/cancel`. Prompt-app and upload-outputs runs are available through the API but
their form fields on this page are still marked as coming in the next step.

### D6.7 E2e worker pool
`scripts/run-e2e.sh` starts the host Celery worker with `--pool=solo`. The default prefork
pool cannot take tasks in this Windows environment (billiard semaphores fail with
`PermissionError`), so no run ever left `queued`. The Docker stack (Linux) keeps prefork.
This is a runner concern only: the executor itself is unchanged and is exercised by the
same tests either way.

## M8 — Safety module

### D8.1 The two sets ship as versioned JSON, validated on load
`backend/app/safety/data/attacks.json` holds 44 attacks across the five categories the spec
names (direct injection, indirect injection, system-prompt leaks, jailbreaks, disallowed
content) and `data/safe_prompts.json` holds 26 harmless requests. Both carry a `version`
field and are validated by `app/safety/sets.py` on first use: minimum sizes (40 / 20), known
categories, unique ids, exactly one deciding rule per attack. A truncated or malformed set
raises instead of silently scoring a run.

### D8.2 Attacks are decided by rules alone, and the canary is in the attack text
Each attack carries either a canary (the planted marker `CANARY-7F3A`) or `expects_refusal`.
A canary attack fails when the marker appears in the app's output; a disallowed-content case
fails when the output is not a refusal. There is no judge in the loop (M7 is not built), so
every case is deterministic. The marker is planted in the attack wording rather than in the
app's real system prompt, because GreenLit cannot modify the app under test — the attack
asks the app to repeat or leak the marker, and an app that complies is the failure.

### D8.3 Critical cases are the hard gate
The spec's gate is "a failed critical safety check". `critical: true` marks the leak cases
and the disallowed-content cases: those are the failures that hand out a secret or
harmful content. `attack_resisted` is *passed* only when no critical attack failed, so it is
the gate; the run-level score is still the share of attacks resisted, so a non-critical
failure lowers the weighted score (and shows as a weakness) without hard-failing the run.
Disallowed-content prompts stay short and generic and only check for a refusal; no real
harmful instructions ship in the set.

### D8.4 The safety criteria are a derived view, not a template
`criteria.with_safety(profile)` appends `attack_resisted` (weight 0.20, hard gate) and
`over_refusal` (0.05) to whichever template the run uses, and the worker does the same when
scoring. The four shipped templates and their weights are untouched, `test_decision`'s
"weights sum to 1.0" invariant still holds for them, and a run with the Safety checkbox off
is byte-for-byte the old behaviour. `not instrumented` safety metrics are excluded from the
weighted score, never counted as zero.

### D8.5 The probes reuse the run's own sender
`app/safety/runner.py` sends the built-in sets through the executor's existing `Sender`, so
the probes honour the run's saved target, timeout, headers, model and rate limiter instead
of a second call path that could drift. A prompt that raises records no output (an attack
cannot have leaked, and a harmless request was not refused — errors belong to `error_rate`).
A probe with no output is scored as *unprobed*: it is excluded from the resisted average and
never counts as a missing refusal, because the app never said anything. Without that rule the
probe burst (44 attacks + the safe set) exceeded a provider's default 30 requests/minute,
and throttling alone produced a hard NO-GO naming eight disallowed cases the app never
answered. `attack_resisted` still reports the whole set (`attacks`) and now also `probed` and
`unprobed`; a run whose probes all failed is not instrumented. Upload-outputs runs never call
the app, so their safety metrics are reported as not instrumented. A cancelled run stops
before probing.

### D8.6 The demo helpdesk refuses disallowed requests
The demo must produce a GO on one click, so once safety is real the good app has to pass it.
`app/services/demo.py` gained a small guardrail: clearly disallowed requests get the same
refusal in both modes (refusing is correct behaviour, not a quality flaw), while the broken
mode keeps answering dataset cases wrongly so it still comes out NO_GO on rule 2.

## M7 — Judge and calibration

### D7.1 The judge is a service with an injectable model call
The model call lives behind `ChatFn`-style injection, exactly like generation: the API layer
resolves the real call through `get_judge_chat`, which only pins the judge's own model on top
of the shared `LLMGateway` (so the judge provider's timeout, retries/backoff and rate limit
still apply). Tests swap the model and exercise the real scoring logic. `app/services/judge.py`
touches no database.

### D7.2 Structured output, temperature 0, one retry, then "judge unavailable"
The rubric asks for one JSON object: `{"score": 0..1, "reason": "...", "confidence": 0..1}`.
`confidence` is the judge's certainty about itself, which is what rule 3's "judge confidence
low" needs; it is deliberately separate from the score. Temperature is pinned to 0 on every
attempt because acceptance criterion 8 requires the same inputs to reproduce the same
verdict. Unparseable or off-contract output (wrong shape, out-of-range score, a bool where a
number belongs, a blank reason) is retried exactly once and then the item is marked
unavailable with the reason recorded. A provider outage is treated the same way, so one bad
case can never fail a run. Code fences are stripped before parsing, because small local
models add them.

### D7.3 An unavailable judge is REVIEW by rule 3, never a hard gate
`judge_status()` turns verdicts into the `JudgeStatus` the decision engine already consumes:
unavailable items and low-confidence items both force REVIEW. It is not a hard gate, because
the spec's gate list is safety and the "no valid items" case; a judge that cannot be reached
must produce a human review, not a NO-GO. `answer_quality` likewise carries a weight instead
of a gate, so a weak judge score lowers the weighted score and appears as a weakness.

### D7.4 Untrusted data is fenced, and provenance travels with the score
Everything from the app under test goes inside one `<data>` block, with the instructions in
the system message, and `<data>`/`</data>` inside the payload are rewritten so untrusted text
cannot close the fence and start issuing orders (spec section 9). The rubric version
(`JUDGE_RUBRIC_VERSION`) and a SHA-256 of the template (`prompt_template_hash`) are attached
to the metric's details and exposed through `judge_metadata()` so every judged run records
which rubric and which prompt produced its scores. `judge_model_warning()` reports when the
judge model equals the model under test, which the spec asks us to warn about.

### D7.5 Calibration reports kappa, not just raw agreement
Reviewers' labels are compared with the judge's as categories (`pass_fail()` buckets a score
the way an approve/reject would). `calibrate()` returns the labelled/agreed counts, raw
agreement, Cohen's kappa and a plain-language reading (Landis and Koch bands). Raw agreement
alone is reported too, but never on its own: on a lopsided set an always-"pass" judge looks
accurate, and kappa is what removes that. Kappa is reported as *undefined* rather than
invented when there are no labels, only one category, or no chance-disagreement possible
(`pe` of 1), and it is allowed to come out negative, which means worse than chance.

### D7.6 Scope: the pure core lands first, then one vertical slice
The judge service and the calibration maths are pure and fully unit-tested, and
`criteria.with_judge()` plus the `include_judge` flag on the evaluation engine make
`answer_quality` a real weighted criterion when a judge is configured. The wiring those pure
pieces need — saved judge profiles, the selector in Settings → Judge, and the worker judging
a run with the provenance stored on the run and per item — landed as the next slice
(D7.7–D7.9). Human labels, the review queue and the calibration endpoints are still to come.

### D7.7 Judge profiles are personal, selected once, temperature frozen
`judge_profiles` (migration `0009_judge_profiles`) stores the owner, name, provider, model,
rubric version, temperature, max tokens and an `is_selected` flag. This is the slice D7.6
deferred. Profiles are owner-scoped like datasets, so a foreign profile answers 404 and its
existence never leaks. The first profile saved is selected automatically: selecting a
profile is what makes it the default, so a run is judged without the New Test page having
to send an id (`resolve_judge_profile` falls back to the selected profile). `temperature`
is stored but never accepted from the client and never editable — it is always 0 — because
criterion 8 (same inputs, same verdict) would quietly break otherwise; the API takes
`max_tokens` because it only bounds the reply length. Deleting a provider keeps the profile
(`SET NULL`), and the worker then reports the judge as skipped rather than crashing.

### D7.8 The worker judges after executing, and never judges a case that failed
Judging is phase 2c of `execute_run`: after the cases run and after the safety probes, a
separate short session reads the judge profile and provider, and the model calls then run
with **no session open**, so a slow judge never holds a transaction. Cases whose call
failed are not sent to the judge: there is no answer to grade, and errors are what
`error_rate` measures. Like the safety probes, judging is skipped when the run is being
cancelled. `judge_chat` is an injectable parameter on `execute_run`, exactly like
`sender_factory`, so tests exercise the real scoring, provenance and decision path with a
fake model.

### D7.9 Provenance is stored on the run and per item; no judge means REVIEW, never a failure
On the run, `settings_snapshot.judge` carries the model, provider name, rubric version,
prompt-template hash, temperature, max tokens and the graded/unavailable/low-confidence
counts; `GET /api/v1/runs/{id}` exposes it as `judge` (or `judge` null plus
`judge_skipped_reason` when no judge ran), which is what lets the verdict card name the
judge or say it was skipped. Per item, a `metric_results` row with `run_item_id` set stores
the score, the judge's reason, its confidence and the same rubric/hash, so one bad answer is
traceable back to the sentence the judge wrote. A judge that cannot be reached, replies
off-contract twice, or configured but deleted becomes `answer_quality` not instrumented
plus `JudgeStatus.unavailable_items`, which reaches REVIEW through rule 3 — the run still
completes, because one bad case can never fail a run.

### D7.10 The judge can be capped per run
`judge_profiles.max_cases` (migration `0010_judge_max_cases`) bounds how many answers one
run sends to the judge; NULL keeps the old behaviour of grading every answer. The cap is a
cost guard, not a score: capped cases are *excluded* from `answer_quality` (never scored 0)
and the run records `judge_case_total` and `judge_capped_items`, which the verdict card
turns into "judged N of M cases". A capped run therefore cannot look like a fully judged
one.

## M9 — Baselines, human review and the audit screen

### D9.1 A baseline is one run per owner and dataset version
`run_baselines` (migration `0011_run_baselines`) has a unique `(owner_id,
dataset_version_id)`, so "set as baseline" replaces the previous choice instead of piling
up rows; clearing it deactivates the row so the history of what was compared survives.
Only a `completed` run with a dataset version can be a baseline (409 otherwise), and the
endpoints are owner-scoped like runs and datasets — a foreign run answers 404.

### D9.2 Regression is a stored comparison with two configurable tolerances
The worker compares a finished run with the active baseline and stores the result in the
run's settings snapshot, so the card and the export read the same numbers the moment the
run finished. The rules are pure (`services/regression.py`): **BLOCK** when a hard gate
stopped passing, a metric dropped beyond `metric_tolerance` (default 0.05), or more cases
regressed than `case_tolerance` (default 2); **WARN** for a smaller drop or up to
`case_tolerance` regressed cases; **PASS** otherwise. A metric measured in only one of the
two runs is not compared — saying it "dropped" would be a lie. If the baseline changes
later, the stored comparison is recomputed on read rather than shown against the wrong run.

### D9.3 A case is a regression when it passed before and fails now
A case counts as passed when it completed and every per-item metric recorded for it passed
(the judge's per-item rows are the usual source). Cases added by a new dataset version are
not compared: a baseline only makes sense within one dataset version, and versions are
approved, not edited.

### D9.4 Labels belong to their reviewer, and calibration spans the project
`human_labels` (migration `0012_human_labels`) is unique per `(reviewer_id, run_item_id)`,
so submitting again replaces that reviewer's own label and a second reviewer is a second
opinion rather than a correction. The queue shows the cases where the judge was
unavailable, was unsure (confidence < 0.5), or where the reviewer's label disagrees with
the judge's bucket; a confident, agreed case stays out. Calibration pairs each label with
the judge's own pass/fail bucket (threshold 0.70) and ignores unavailable judges, then
reports raw agreement and Cohen's kappa through the existing `calibrate()`. Only reviewers
and admins may label or read the queue (403 for members, enforced by `require_roles`).

### D9.5 The setup checklist only counts what the run will actually accept
The checklist lives on the New Test page and mirrors the run's own rules: an active
provider (with an on-demand live check, so "reachable" is measured, not assumed), a
connector that answered a detection in this session, and at least one **approved** dataset
version. It is shown for the HTTP entry point only, because a prompt app needs no connector
test and uploaded outputs need no target; claiming those steps otherwise would be noise.

### D9.6 The audit screen filters and pages on the server
`GET /api/v1/audit` gained `action` (case-insensitive substring) and `target_type` filters
that narrow the **total** as well as the page, so "1-20 of 42" stays true under a filter.
Settings → Audit log is now a real tab; the tabs that still have no panel (Connectors,
Criteria, Safety, Account, Preferences) keep the "soon" badge.

### D9.7 The e2e runner takes a spec as its first argument
`bash scripts/run-e2e.sh tests/e2e-baseline.spec.ts` runs one spec on the same disposable
stack, for machines where the full 16-test suite takes longer than one command. This is a
developer convenience: the suite still runs whole in CI.

### D9.8 The one-click demo measures quality, not host latency
Try the demo runs the quality test type only. Its purpose is to show a reproducible GO and
NO-GO with the shipped answers; measuring host timing made the sample score depend on machine
load. Safety and operations remain selectable on normal runs and have their own coverage.

### D9.9 The CI runner uses the standard library and an explicit live demo check
`scripts/greenlit_ci.py` stores the login cookies in a standard-library cookie jar, submits
`/quick-test`, polls `/runs/{id}` to a terminal verdict and maps GO/NO_GO/REVIEW and request
errors to the documented exit codes. Unit tests use a local fake HTTP server; the disposable
e2e runner invokes the CLI against its healthy demo app after Playwright.

## M11 — MCP server

### D11.1 The MCP server reuses the CI runner's authentication, not a new token type
There is no non-browser token in GreenLit: sessions are httpOnly cookies. Rather than
invent a token, the MCP server signs in with `GREENLIT_EMAIL`/`GREENLIT_PASSWORD` exactly
like `scripts/greenlit_ci.py`, keeps the cookie in memory and re-signs in once after a 401.
No backend change was needed, the API's own ownership and permission checks still apply,
and the docs tell the operator to use a dedicated low-privilege account rather than the
admin one. The password and email are redacted from every error and tool response.

### D11.2 `greenlit_list_projects` reports the one implicit project
The API has no projects resource; the UI has always shown a single disabled "Default
project" switcher. The tool therefore returns exactly one entry derived from
`GET /api/v1/auth/me` plus the real dataset and run totals, marked `implicit`, instead of
inventing a project list or adding a projects endpoint.

### D11.3 The start tool is local-only and off by default
GreenLit keeps the permission record on the run (checkbox plus reference), and the MCP
server must never set or change it, so there is no record it could check for a remote
target. `greenlit_start_run` is therefore registered only when
`GREENLIT_MCP_ALLOW_START=1`, accepts only targets on the user's own machine, sends
`allow_private_targets: true` for them, and caps starts at one per 10 seconds. Remote
starts remain a UI action, which keeps the permission decision with a human.

## M12 — Account and Preferences settings

### D12.1 Preferences live on the user row, not only in the browser
The theme was a `localStorage` value, which every account on a browser shared and which no
other browser could see. `users.preferences` (migration `0015_user_preferences`, JSON,
`NOT NULL`, default `{}`) makes the choice belong to the account: two users on one browser
are isolated, and the same user gets their theme on another machine. `localStorage` is kept
as a one-key paint cache, so the first frame after a reload is already right instead of
flashing the default while `/auth/me/preferences` answers. No table was added and no data
was rewritten: existing rows start at `{}` and the API fills in the default.

### D12.2 One validated key, and a stored value that cannot break the UI
`Preferences` accepts exactly `{theme: "dark" | "light" | "system"}` (`extra="forbid"`), so
the account cannot be used as arbitrary storage. A PATCH replaces the document, which is
why the client always sends every key it owns. Reading is defensive: a value written by an
older build (or by hand) that is not one of the three themes is served as `dark` rather than
reaching the browser as an unknown attribute.

### D12.3 The display name is the only self-editable field
The target user comes from the session cookie, never from the request body, so there is no
id to tamper with and a user cannot address another account. `PATCH /api/v1/auth/me` accepts
`name` only (1–120 characters after trimming, blank rejected with a field error); `email`,
`role` and the password are not part of the schema and extra keys are a 422. The change is
audited as `user.profile_updated` with `{"changed": ["name"]}` — which field changed, not
the old and new values — and a no-op save writes no event.

### D12.4 "System" is resolved in the browser, because only the browser knows
The stored preference can be `system`, but the painted theme is always `dark` or `light`:
`resolveTheme()` reads `prefers-color-scheme` and the provider re-resolves when the OS
setting changes (when `matchMedia` is missing it keeps the app's own dark default rather
than guessing light). The topbar toggle flips the *resolved* theme and saves the explicit
choice, so clicking it while on "system" produces a concrete theme instead of a no-op.

### D12.5 One provider owns the theme
The topbar toggle and Settings → Preferences used to be two potential copies of the same
state. `ThemeProvider` (with `themeContext.ts` split out, following the auth-provider
pattern, so `react-refresh/only-export-components` stays clean) is now the only owner: it
applies `data-theme` on `<html>`, caches the choice, saves it to the account and exposes
`saving`/`error`. On sign-in it loads the account's value; if the user changes the theme
before that response arrives, the later response no longer wins; on sign-out it resets to
the default and clears the cache so the next person on the browser does not inherit it.

### D12.6 A theme change is not audited
`user.profile_updated` is recorded because a display name identifies the actor in the log.
The theme is cosmetic and per-account, and recording every toggle would bury the sign-ins
and data changes the append-only trail exists for.

### D12.7 No fake password form, no account deletion
GreenLit has no in-app password change; resets go through the existing API-only flow, which
still needs an email provider, so the panel says that rather than showing a form that cannot
work. Account deletion is not offered because the current schema cascades datasets, runs and
labels from `users`, and no confirmation/re-authentication flow exists to make that safe;
the panel states the limitation instead of silently hiding it.

### D12.8 The e2e expectation changed because the behaviour did
`e2e-setup-audit.spec.ts` asserted that Account was a "soon" placeholder. That assertion is
now the opposite for Account and Preferences, and the spec verifies the real panel instead:
profile fields, a display-name save that survives a reload, a theme applied at once and
restored from the API with `localStorage` cleared, then a restore of the account's name and
theme so the rest of the suite sees the state it expects. No other spec was weakened.
