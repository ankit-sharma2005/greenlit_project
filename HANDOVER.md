# GreenLit — Handover notes

> Living document. It reflects the repository as of the account-and-preferences milestone
> (M6 runs, M7 judge and calibration, M8 safety, spec 8.5 reports and regression, and the
> Settings → Account / Preferences panels). Everything below is exercised by a command in
> this file; nothing in it is a plan.

## What GreenLit is

Pre-launch testing for LLM-powered applications. You point it at an app (an HTTP endpoint,
a system prompt plus a provider, or a file of outputs the app already produced), give it a
golden dataset, and it answers one question: **is this app good enough to ship?** — as
**GO / REVIEW / NO-GO**, with the rule that produced the verdict, the metric table, the
failed cases, the safety probes and the judge that scored it. Any finished run can be
exported as HTML, JSON or CSV, and compared with the dataset version's baseline
(PASS / WARN / BLOCK) once one is set. Reviewers label the cases the judge could not
settle, and the Calibration page reports how well the judge agrees with them.

## How to run

```bash
cp .env.example .env      # optional; defaults work
docker compose up --build
```

| Service  | URL                        | Container port | Host port (default)  |
| -------- | -------------------------- | -------------- | -------------------- |
| Web UI   | http://localhost:5177      | 5173           | `WEB_PORT=5177`      |
| API      | http://localhost:8003      | 8000           | `API_PORT=8003`      |
| API docs | http://localhost:8003/docs | 8000           | `API_PORT=8003`      |
| Postgres | `localhost:5436`           | 5432           | `POSTGRES_PORT=5436` |
| Redis    | `localhost:6382`           | 6379           | `REDIS_PORT=6382`    |

Ports are read from `.env`; changing `WEB_PORT`/`API_PORT` also means changing `WEB_ORIGIN`
and `VITE_API_BASE_URL`, because those are browser-facing. Internal compose traffic keeps
using the container ports.

The demo helpdesk is a Compose profile, not a service that is always on:

```bash
docker compose --profile demo up -d     # demo-app (good) on 9301, demo-app-broken on 9302
```

Then press **Try the demo** on the New Test page: GO for the healthy app, NO-GO for the
broken one.

## Architecture

**Backend (`backend/app`)** — FastAPI, sync SQLAlchemy 2 with psycopg 3, Alembic
migrations, one error envelope `{"error": {"code", "message", "fields"}}`.

- `api/` — one router per area: `auth`, `users`, `audit` (paged and filtered), `providers`,
  `connectors` (connector tests and cURL parsing), `saved_targets` (the Settings → Connectors
  shelf), `datasets`, `evaluations`, `runs` (including baseline and report),
  `judge_profiles`, `labels` (review queue and calibration), `demo`, `health`. Thin: parse,
  authorise, delegate, audit.
- `services/` — the logic, no HTTP in it and mostly no I/O outside the session:
  - `run_service.py` validates a request, builds the **settings snapshot**, resolves the
    criteria profile and the judge, then queues the run.
  - `run_executor.py` runs it in the worker: it loads cases from the approved dataset
    version (or the uploaded outputs), sends each one through the run's saved connector,
    scores metrics, applies the decision rules, then runs the safety probes.
  - `metrics.py` / `decision.py` — pure scoring and the GO/REVIEW/NO-GO rules.
  - `safety/` (data + sets + runner + metrics) — the versioned attack and safe-prompt
    sets, the canary/refusal rules and the hard gate.
  - `judge.py` / `judge_profiles.py` / `calibration.py` — structured grading at
    temperature 0 with one retry, the saved profiles, and raw agreement / Cohen's kappa.
  - `saved_targets.py` — validation and owner-scoped queries for the Settings → Connectors
    shelf: name and URL rules, header *names* only, and no permission record.
  - `regression.py` — the baseline of a dataset version and the pure PASS / WARN / BLOCK
    comparison (metric deltas plus case-level regressions) the worker stores.
  - `labels.py` — the review queue (judge unavailable, unsure, or a label that disagrees),
    one label per reviewer per case, and the project calibration.
  - `generation.py` — draft case generation through the shared LLM gateway, with text and
    PDF/TXT/MD extraction, passage limits, untrusted-source prompting and reference passages.
  - `operations.py` — pure operations metrics: p50/p95 latency, error and timeout rates
    and token totals, with a cost estimate only when token prices are configured. A value
    nobody reported stays null rather than becoming a 0.
  - `report.py` — one report document with three renderers; redacts headers and the
    encrypted cURL blob, escapes HTML, prefixes formula-leading CSV cells, and carries the
    recorded permission (who allowed testing the target) in all three formats.
  - `utils/request_client.py` — the one SSRF-safe request path (JSON and streamed), with
    the retry rules: 429/502/503/504, exponential backoff plus jitter, and the target's
    `Retry-After` (seconds or HTTP date) capped at 60 s.
  - `services/connectors.py` — the shared request function both the test call and every run
    case use: polite pacing (`max_concurrency`, `min_delay_ms`, `max_retries`), one JSON
    body or a joined `sse`/`ndjson`/`text` stream (100 KB cap, TTFT and total latency), a
    150 s per-case budget, and interruptible retry waits (Cancel sets a threading.Event).
    A recovered case records the final attempt's latency plus `retry_count`/`waited_ms`;
    `operations.py` reports `retried_cases` and never counts those as errors.
  - `utils/curl.py` — parses a pasted cURL (headers, cookies, `-u`, body), drops `Host`,
    and encrypts the values; the API returns names only.
  - `llm_gateway.py` — the only place that talks to a model provider: timeout, retries
    with backoff, rate limit, key decryption.
- `tasks.py` + `celery_app.py` — the worker task `run_test`. Progress lives in Redis
  (`run_progress.py`) and falls back to the database, so the UI polls cheaply.
- `models.py` — users (with `preferences`), refresh tokens, password resets, audit events,
  providers, datasets/versions/items, runs/items, metric results, judge profiles,
  saved targets.
- `demo_server.py` + `services/demo.py` — the built-in helpdesk app (good/broken modes)
  and the shipped golden dataset, used by "Try the demo" and by the tests.

**Frontend (`frontend/src`)** — React 19 + TypeScript + Vite, React Router, CSS custom
properties with a dark default and a light theme.

- `pages/` — `NewTestPage` (the three entry points and the live run), `ResultsPage`
  (run history, compare, ad-hoc scoring), `CalibrationPage` (review queue and kappa),
  `SettingsPage` (Datasets, Providers, Connectors, Criteria, Judge, Safety, Account,
  Preferences, Audit log), auth pages, `TestChatPage` (not built).
- `components/` — the pieces the pages compose: `PromptAppPanel`, `UploadOutputsPanel`,
  `DemoPanel`, `RunProgressPanel` (progress → verdict card → exports), `BaselinePanel`
  (baseline control and the regression table), `SafetySection`, `SafetyPanel`,
  `CriteriaPanel`, `ReportExport`,
  `RunHistory`, `JudgePanel`, `ProvidersPanel`, `DatasetsPanel`, `ReviewQueue`,
  `CalibrationSummary`, `SetupChecklist`, `AuditPanel`, `AccountPanel`,
  `PreferencesPanel`, `ConnectorsPanel` (the saved-target shelf).
- `theme/` — `ThemeProvider` (the only owner of the theme: applies `data-theme`, follows
  `prefers-color-scheme` for "system", saves to the account, clears on sign-out) and
  `themeContext.ts` with `useTheme()`. `lib/theme.ts` holds the pure helpers and the
  one-key paint cache; `lib/preferences.ts` is the API client for
  `/auth/me/preferences`.
- `lib/` — typed API clients, one module per area, all going through `lib/api.ts` so the
  session cookie and the error envelope are handled in one place. `lib/session.ts`
  implements single-flight silent token refresh on 401 with Web Locks (skipping auth
  endpoints); on a failed refresh the app emits `greenlit:session-expired`, sets the auth
  state to anonymous, and `RequireAuth`/`LoginPage` show "Your session expired. Please
  sign in again." Tests: `lib/api.test.ts` (retry-once, one refresh for ten parallel 401s,
  no loop on a second 401, auth endpoints exempt, no sign-out on a refresh 5xx/network
  error, unreadable bodies not replayed), `lib/session.test.ts` (one expiry signal per
  refused refresh, Web Locks inside `navigator.locks.request("greenlit-refresh")`, and the
  fallbacks when the API is missing or the lock throws), and `auth/AuthProvider.test.tsx`
  (mount-time `/me` 401 → refresh → `/me`, anonymous when the refresh is refused). Not
  proven: browsers without Web Locks beyond the stubbed fallback, idle sessions longer than
  14 days, and the backend's refresh-token reuse detection (unchanged).

**MCP server (`mcp_server/`)** — a separate stdio process for MCP clients (Claude,
Freebuff, Copilot). It is a thin client over the same REST API: `client.py` signs in with
`GREENLIT_EMAIL`/`GREENLIT_PASSWORD` like `scripts/greenlit_ci.py`, keeps the httpOnly
session cookie in memory and re-signs in once after a 401; `server.py` exposes five
read-only tools (`greenlit_list_projects`, `greenlit_get_run_status`,
`greenlit_get_verdict`, `greenlit_get_report`, `greenlit_get_criteria`) and the opt-in
`greenlit_start_run` (only when `GREENLIT_MCP_ALLOW_START=1`, local targets only, one
start per 10 s). It imports no app module, reads no database and changes no decision
rule. Every response is size-capped with a `truncated` flag, and credentials are
redacted from every error. Setup and the security rules are in [docs/MCP.md](docs/MCP.md).

**Data flow of one run:** `POST /api/v1/quick-test` (or `/runs`) snapshots settings and
queues → Celery executes case by case, writing items and metric rows → the decision rules
produce the verdict and reason → the worker compares the run with its dataset version's
baseline and stores the result, and stores the operations block → the browser polls
`/runs/{id}/progress` and then reads `/runs/{id}` for metrics, failures, safety, judge
provenance, regression and operations → `/runs/{id}/report` renders the same document out
of the box.

## How to test

```bash
# backend: lint, format, types, unit + API tests (in-memory SQLite, no Docker, no Redis)
cd backend && ruff check . && ruff format --check . && mypy && pytest

# frontend: lint, format, types, component tests, production build
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build

# end to end: a disposable stack (needs Docker Desktop)
bash scripts/run-e2e.sh
```

- Backend tests live in `backend/tests`, one module per area. They never touch a real
  provider: `ChatFn` is injected, and so are the queue and the progress reader. Dataset
  source-generation tests build a small PDF fixture at test time and fake the model call.
  `python -m pytest --collect-only -q` reports 649 tests when its per-file counts are summed.
  The single `python -m pytest -q` run on 2026-11-04 had two Redis-dependent failures:
  `test_the_api_check_then_accept_unlocks_a_remote_run` and
  `test_a_local_run_needs_no_check` could not connect to localhost:6382. The captured
  output had no final passed/skipped/time summary, so those figures are not claimed.
  `tests/test_quirk_failures.py` runs the real connector against
  `tests/support/quirk_server.py` (and a generated TLS server) for the failure classes
  listed under "Real-world failure classes" below. `tests/test_operations.py` covers the
  percentile edge cases (one case, even and odd counts, all failures), and
  `tests/test_error_kind_timeout.py` proves a real timeout against a local slow server
  (plus connection-refused and the old-run text fallback). `tests/test_http_rate_control.py`
  and `tests/test_http_streaming.py` run real local servers for the retry/`Retry-After` and
  SSE/NDJSON/text/stall/oversize behaviour, and `tests/test_curl_credentials.py` uses a
  server that refuses anything without the imported cookie and bearer token.
- Frontend component tests are Vitest + Testing Library next to the components; the
  measured `npx vitest run` result is 208 tests in 34 files (including
  `NewTestPage.test.tsx`, which proves
  the permission box is required and that the attack-probe box starts off, and
  `lib/api.test.ts` + `lib/session.test.ts` + `auth/AuthProvider.test.tsx`, which prove the
  silent refresh).
- `frontend/tests` is the Playwright suite (21 tests in 13 specs, measured by
  `npx playwright test --list`; the one website wizard spec passed against the local
  demo in this step: `website chatbot wizard checks the local demo and keeps HTTP
  endpoint flow working`. It includes
  `e2e-session-refresh.spec.ts`): admin/accounts and the
  results page, Try the demo, baseline regression, calibration (label → kappa), judge
  provenance, the prompt app (prices typed into the provider's row in Settings, then
  the priced cost estimate on the verdict),
  report download, safety both ways, the setup checklist, the audit screen, the Account
  panel (profile fields, a display-name save that survives a reload) and Preferences
  (immediate apply, save, restore from the API with the local cache cleared, then a
  restore), uploaded
  outputs, PDF dataset generation through preview and approval, and the website chatbot
  wizard against the local demo. It runs against local or fake apps; no real third-party
  site is used.
- `scripts/run-e2e.sh` uses a uniquely named Compose project per invocation (Postgres 5536,
  Redis 6482, fresh volume), the API on 8103, a solo Celery worker, Vite on 5277 and the two
  demo helpdesks on 9501/9502. It stops only that invocation's containers, preserves its
  volume, and never touches the stack you use in the browser. After Playwright it runs the
  CI runner against the healthy demo app.
- MCP server: `python -m pytest mcp_server/tests -q` (16 tests, no network: the SDK's
  in-memory client drives a local fake GreenLit server), `mypy --strict` on
  `mcp_server/client.py`, `server.py`, `__main__.py` and `__init__.py`, and
  `ruff check --config backend/pyproject.toml mcp_server` plus `ruff format --check` on
  the same path. The server needs only `mcp>=1,<2` (`mcp_server/requirements.txt`); it is
  not a dependency of the backend image or of `backend/`'s test suite.
- `scripts/greenlit_ci.py` uses only the Python standard library: it logs in with
  `GREENLIT_EMAIL`/`GREENLIT_PASSWORD`, creates a quick test, polls to completion, prints the
  verdict, weighted score and failed instrumented metrics, and returns documented CI exit
  codes. Fake-server tests cover GO, NO_GO, REVIEW, timeout and authentication failure.

## M12 — Task: Account and Preferences settings

**Status: implemented and tested.** Both tabs that used to carry a "soon" badge are now
real panels; every control in them calls an endpoint that exists.

### Completed

- **Account** (`Settings → Account`): display name, email, role, account status, creation
  date and account id, all read from `GET /api/v1/auth/me`. The display name is editable
  (`PATCH /api/v1/auth/me`), trimmed, limited to 120 characters and refused when blank; the
  save updates the shared user so the topbar follows. Sign-out uses the existing
  `/auth/logout` and goes to `/login`. The panel says plainly that there is no in-app
  password form and no account deletion, and why.
- **Preferences** (`Settings → Preferences`): dark, light or system default. Choosing one
  paints immediately, is saved to the account (`PATCH /api/v1/auth/me/preferences`), is
  restored from the API on any browser, and is cached locally so a reload does not flash.
  Failure to save keeps the local choice and offers a retry; "Reset to defaults" returns to
  dark and persists it. A signed-out user is never shown the previous account's theme.
- **Isolation and safety:** both endpoints take the target from the session cookie; there
  is no user id in either request, so a caller can only change their own record. Passwords,
  tokens and keys are never rendered, and the endpoints reject unknown keys with a 422.

### Files

Created:

- `backend/alembic/versions/0015_user_preferences.py`
- `backend/app/schemas/preferences.py`
- `backend/tests/test_account_preferences.py`
- `frontend/src/lib/preferences.ts`, `frontend/src/lib/theme.ts` (+ `theme.test.ts`)
- `frontend/src/theme/ThemeProvider.tsx`, `frontend/src/theme/themeContext.ts`
- `frontend/src/components/AccountPanel.tsx` (+ `.test.tsx`)
- `frontend/src/components/PreferencesPanel.tsx` (+ `.test.tsx`)
- `frontend/src/styles/settings.css`

Modified:

- `backend/app/models.py` (`User.preferences`), `backend/app/schemas/auth.py`
  (`ProfileUpdateRequest`), `backend/app/api/auth.py` (the two profile/preferences routes)
- `frontend/src/lib/authApi.ts`, `frontend/src/auth/authContext.ts`,
  `frontend/src/auth/AuthProvider.tsx` (`updateProfile`)
- `frontend/src/components/Layout.tsx` (uses the shared theme instead of local state)
- `frontend/src/pages/SettingsPage.tsx` (both tabs registered, "soon" removed)
- `frontend/src/main.tsx` (`ThemeProvider`), `frontend/tests/e2e-setup-audit.spec.ts`

### Backend / API / database

- `GET /api/v1/auth/me/preferences` → `{"theme": "dark" | "light" | "system"}` (default
  `dark`; an unrecognised stored value is served as `dark`).
- `PATCH /api/v1/auth/me/preferences` replaces that document; `extra="forbid"`.
- `PATCH /api/v1/auth/me` accepts `name` only and appends `user.profile_updated`
  (`{"changed": ["name"]}`) to the audit trail when the value actually changes.
- Migration `0015_user_preferences` adds `users.preferences` (JSON, `NOT NULL`,
  `server_default '{}'`). No new table, no backfill; existing accounts read as `dark`.

### Tests actually run

- `cd backend && python -m pytest tests/test_account_preferences.py -q` — **7 passed**.
- `cd backend && ruff check .` (clean), `ruff format --check .` (**151 files already
  formatted**), `mypy` (**no issues in 82 source files**).
- `cd frontend && npx vitest run` — **188 passed in 31 files** (169/28 before; the new
  files are `AccountPanel.test.tsx`, `PreferencesPanel.test.tsx`, `lib/theme.test.ts`).
- `cd frontend && npm run lint`, `npm run typecheck`, `npm run build` — all pass.
- `bash scripts/run-e2e.sh tests/e2e-setup-audit.spec.ts` on the disposable stack —
  **1 passed (11.4s)**, exit 0. It now checks the real Account panel, a display-name save
  that survives a reload, and a theme applied at once and restored from the API with
  `localStorage` cleared, then restores the name and theme for the rest of the suite.
- Manual check against the running dev stack (`http://localhost:5177`, migration applied):
  the account panel showed `demo@example.com` / `member` / "November 2, 2026"; a name edit
  updated the topbar and the database; light → saved; cache cleared + reload → light came
  back from the API; "System default" resolved to the OS theme; reset returned to dark.

### Known limitations

- **No email change, password change or account deletion.** Email is the sign-in identity;
  passwords use the API-only reset flow, which still needs an email provider; deletion has
  no safe re-authentication/cascade flow. The panel says so.
- **Login page theme follows the cache.** Before sign-in the browser uses the last cached
  theme; after sign-in the account's own choice replaces it. A shared machine therefore
  shows the previous user's colours on the sign-in screen (no account data is exposed).
- **`prettier --check` still reports 9 pre-existing files** (`lib/api.ts`,
  `pages/NewTestPage.tsx`, `WebsiteWizard.tsx`, …) that this change did not touch and did
  not reformat; every file added or edited here is formatted.
- **The full backend suite is slow on this machine** (about 20 minutes). The complete run
  finished with exit code 0 and no failures (`s` = 1 skipped, no `F`); this environment
  suppresses pytest's final summary line, so the count comes from collection:
  `python -m pytest --collect-only -q` lists **661** tests (649 before, 7 of them the new
  `test_account_preferences.py`, plus five picked up from tests added since that count was
  written).

### Remaining tasks

- None for this task. Related, deliberately not done here: password change UI, account
  deletion, and the Connectors tab (still "soon").

### Latest commit

- `dc4490a` — `feat(settings): account and preferences tabs with per-account theme`
  (documentation for it, including this hash, is the follow-up commit on top).

## M13 — Task: Saved targets (Settings → Connectors)

**Status: implemented and tested.** The last Settings placeholder is a real panel.

### Completed

- **The shelf:** Settings → Connectors lists the saved targets of the signed-in account with
  their method, URL, response format and answer path, and saves (`POST`), edits (`PATCH`) and
  deletes them. Names are unique per account; a duplicate answers 409 in plain words. The
  form asks for name, URL, method, response format, answer and context paths, request body
  and timeout.
- **No secrets, no consent on the shelf:** only header *names* are stored (a cURL's header
  values stay encrypted inside the run that sent them), and there is no permission field —
  the first-contact check still asks per run. The schema rejects `headers`,
  `headers_secret`, `permission_confirmed` and `owner_id` as extra keys.
- **Owner-scoped:** the owner comes from the session; a foreign or missing id is a 404, so a
  target of another account never leaks. Two accounts on one browser see separate shelves
  (checked in the dev database: the demo account saw only its own row).

### Files

Created: `backend/alembic/versions/0016_saved_targets.py`,
`backend/app/schemas/saved_targets.py`, `backend/app/services/saved_targets.py`,
`backend/app/api/saved_targets.py`, `backend/tests/test_saved_targets.py`,
`frontend/src/lib/savedTargets.ts`, `frontend/src/components/ConnectorsPanel.tsx`,
`frontend/src/components/ConnectorsPanel.test.tsx`.

Modified: `backend/app/models.py` (`SavedTarget`), `backend/app/main.py` (router),
`frontend/src/pages/SettingsPage.tsx` (tab registered, "soon" removed),
`frontend/tests/e2e-setup-audit.spec.ts` (real panel instead of the "soon" assertion).

### Backend / API / database

- `GET /api/v1/saved-targets` → `{items, total}` (oldest first).
- `POST /api/v1/saved-targets` (201), `PATCH /api/v1/saved-targets/{id}` (partial;
  `exclude_unset`, an explicit null clears a path), `DELETE /api/v1/saved-targets/{id}` (204).
- Audit: `saved_target.create`, `saved_target.update` (with `changed`), `saved_target.delete`;
  metadata carries the connector type, method, format and header names, never the URL.
- Migration `0016_saved_targets`: one table, `UniqueConstraint(owner_id, name)`, cascade from
  `users`. No backfill, no change to `runs` (a run keeps its own snapshot).

### Tests actually run

- `cd backend && python -m pytest tests/test_saved_targets.py` — **9 passed** (defaults and
  upper-cased method, extra-key rejection, header-name de-duplication, 409 on a repeated
  name, bad URL and blank name, partial edit with a cleared field, foreign-account 404s,
  delete plus audit trail without the URL, 401 without a session).
- `ruff check`, `ruff format --check`, `mypy` — clean (85 source files; 154 formatted after
  the new files were formatted).
- `cd frontend && npx vitest run` — **195 passed in 32 files** (188/31 before; the new file is
  `ConnectorsPanel.test.tsx` with 7 tests). Superseded in M14: **208 in 34 files**. `npm run typecheck`, `npm run lint`,
  `npm run build` all pass.
- `bash scripts/run-e2e.sh tests/e2e-setup-audit.spec.ts` — **passed** (`test-results/
  .last-run.json` reports `passed`, no failed tests); the spec now saves a target, reloads,
  checks the row came back from the API, and deletes it.
- Full backend suite (`python -m pytest -q`, ~20 minutes here) — **exit 0, no failures or
  errors**. This environment suppresses pytest's final summary line, so the count comes from
  collection: **670** tests (661 before + 9 new). Superseded in M14: see the summary line
  measured there.
- Manual run on the dev stack (`http://localhost:5177`, migration applied, log shows
  `0015_user_preferences -> 0016_saved_targets`): the tab renders with no error, the empty
  state reads "Nothing saved yet", saving "Demo helpdesk" produced the notice, the row and a
  Postgres row, edit loaded the saved values and renamed it, delete emptied the shelf again.

### Known limitations

- **The shelf is not yet offered on the New Test page.** A saved target keeps the format, but
  starting a run still means typing the connector settings there; wiring a picker needs the
  page's form state lifted into one place.
- **No header values are stored**, so an authenticated target still needs a cURL per run.
- **No "test this target" button**, because it would have to assert the remote-permission
  consent the first-contact check collects per run.
- **The two demo helpdesk apps were not running** when the dev stack was restarted, so the
  manual check used a saved URL without sending a request (saving sends nothing by design).

### Remaining tasks

- Offer saved targets on the New Test page (pick → prefill the connector fields).
- Password change UI, account deletion and a production deploy path remain open from before.

### Latest commit

- `2ef8207` — `feat(settings): saved targets in the Connectors tab` (this hash is recorded by
  the follow-up documentation commit on top).

## Real-world failure classes

`backend/tests/support/quirk_server.py` is one loopback server that mimics the ways a
real app (or a company website chatbot) misbehaves; each row below is proven by a named
test in `backend/tests/test_quirk_failures.py` unless the row says otherwise. Status is
honest: PARTLY means the truth is narrower than the row reads.

| Quirk | Status | Proof |
| --- | --- | --- |
| Basic / bearer / API-key / cookie auth | HANDLED | `test_each_auth_style_is_sent_and_accepted` |
| Token expiring mid-run | PARTLY | `test_a_token_that_expires_mid_run_stops_with_a_clear_error` — a clear `auth_error`, exactly one further request, no retry storm. The run-level "answered cases are kept" comes from the normal per-case failure path, not a dedicated test. |
| CSRF / anti-bot 403 challenge page | HANDLED | `test_an_anti_bot_challenge_is_a_blocked_site_not_a_wrong_answer` (and `test_a_secret_in_a_challenge_page_is_redacted`); the 401/403 taxonomy is in M15 below (`tests/test_site_diagnosis.py`) |
| A 403 that is *not* a challenge (nginx page, permission, expired login) | HANDLED | M15: `test_a_plain_nginx_403_is_not_called_an_anti_bot_challenge`, `test_an_expired_session_login_page_says_the_session_is_missing`, `test_a_403_with_credentials_names_permission_not_the_anti_bot_story` |
| Browser-copied headers (`:authority`, stale `content-length`) | HANDLED | M15: `tests/test_curl_browser_headers.py` |
| Redirects | HANDLED | `test_a_same_host_redirect_is_followed`, `test_a_cross_host_redirect_is_refused_and_names_the_target` (the other host is never contacted), `test_a_redirect_loop_stops_after_three_hops` |
| TLS, DNS, reset | PARTLY | `test_a_self_signed_certificate_is_named_as_such`, `test_an_expired_certificate_says_expired`, `test_a_dns_failure_is_not_a_timeout`, `test_a_connection_reset_is_reported`. Connect has its own shorter clock but no test trips a hanging host. |
| Response shapes | HANDLED | `test_a_known_response_shape_is_mapped` (OpenAI, nested JSON path, messages array, gzip), `test_an_unreadable_answer_names_what_was_tried` (HTML 200, empty, invalid UTF-8, plain text, null answer), `test_a_huge_json_body_is_capped_not_parsed` |
| Streams | HANDLED | existing SSE/NDJSON/keepalive tests plus `test_a_stream_without_a_final_event_is_flagged_incomplete`, `test_a_stream_that_stalls_keeps_its_partial_answer`, and `test_an_incomplete_streamed_answer_is_a_failed_case_not_a_correct_one` |
| Conversations / sessions | MISSING | No session or conversation id, no multi-turn history, no per-case cookie isolation. Only the request template's escaping is proven: `test_a_template_with_quotes_newlines_backslashes_emoji_and_hindi_stays_json`. |
| Refusals and guardrails | PARTLY | Safety already counts a refusal as resisted; there is no REFUSED badge or reason for an ordinary case. |
| Rate limits and quotas | HANDLED | `tests/test_http_rate_control.py` (429 with and without `Retry-After`, 503 bursts) and `tests/test_run_executor.py::test_circuit_breaker_marks_the_rest_not_run_and_says_target_failing`; there is no quota-body-specific wording. |
| Slow apps | PARTLY | Per-run timeout 1–300 s (`RunCreateRequest.timeout_seconds`) and a 150 s per-case budget; no cold-start handling and no per-project setting (there is no project record). |
| Sensitive data in exports | MISSING | Only request headers are redacted (`tests/test_report.py`); emails, phones, card-like numbers and keys inside answers are exported as written. |
| Judge problems | HANDLED | `tests/test_judge.py`, `tests/test_run_executor_judge.py`: unavailable or off-contract judge → not measured + REVIEW, never a 0. |
| Worker crash / duplicate start | PARTLY | A run with no heartbeat for `INTERRUPTED_AFTER_MINUTES` (default 10) is marked `interrupted` by the worker-start / before-task sweep: answered cases are kept, the rest become "not run", and nothing is resumed (`tests/test_run_sweep.py`). A repeated start with the same `Idempotency-Key`, or the same target+dataset within a minute, returns the existing run (`test_a_retried_start_with_the_same_idempotency_key_returns_the_same_run`). Cancel stops a run at the next case boundary (`test_cancel_mid_run_keeps_partial_results`). Not proven: a hard kill mid-case is only swept when a worker starts or the next task arrives, and there is still no resume. |
| Cost and time caps | MISSING | No max-cases, max-duration or max-token run caps and no "stopped by limit" status. |

Not built in this milestone: the "Check before full run" step (one harmless case, an
accepted extraction, then a 5-case smoke run) and any frontend change that would go
with it.

## Known limitations

- **The shipped defaults are not a deployment.** Change `APP_SECRET_KEY` and
  `POSTGRES_PASSWORD` in `.env` before any real deployment; see README →
  "Before you deploy or share this repo", which also covers the old `cookies.txt` that commit
  `d953cff` once tracked.
- **No email provider.** Password reset works through `POST /auth/password-reset/request`,
  which returns a `debug_token` only in development; production needs an email integration.
- **No UI for some endpoints that exist:** password reset and user administration are
  API-only.
- **A baseline is per owner and dataset version.** GreenLit has one project, but the
  baseline is stored against the signed-in user, so two accounts testing the same dataset
  version keep separate baselines, and not every dataset version has one.
- **Regression is metric-and-case based, not statistical.** A drop smaller than the
  baseline's tolerance is a WARN even if it is real, and a case whose answer changed but
  still passed is not reported.
- **The safety probe burst is large** (44 attacks plus 26 safe prompts). A provider with a
  low per-minute limit reports many probes as _unprobed_ rather than failed; that is
  deliberate (see D8.5) but it means a heavily throttled provider needs a higher limit to
  fully exercise the set.
- **PDF dataset generation requires selectable text.** Scanned PDFs are rejected with an
  actionable error; OCR is not implemented. Source uploads are limited to 5 MB and only the
  first 20 passages are sent to the model.
- **Token prices are set per provider, and nothing sets them yet from the UI.**
  `operations.py` reads `price_per_1k_tokens_in` / `price_per_1k_tokens_out` out of a
  provider's `metadata`, so until those keys exist every run reports cost as "not
  configured". An HTTP-endpoint run has no provider at all and always says so.
- **Operations describes the cases it saw.** Percentiles cover only the cases that
  reported a latency; a run where the connector never timed the call shows "not measured"
  rather than an estimate.
- **The permission rule keys on "runs on my computer".** Any target tested with that box
  unticked needs the confirmation (the built-in demo and host.docker.internal targets are
  local, so one click still works); a LAN address typed without the box is treated as
  remote and refused until confirmed. There is no allowlist of company domains.
- **The safety set picker still has no UI.** `safety_sets` is API-only, and for a remote
  target the whole Safety type is dropped unless the second permission checkbox is ticked.
- **Test Chat is a placeholder.** The page exists and is honest about it.
- **The topbar project switcher is disabled** ("Default project") and the provider health
  badge there is static; provider health is real on Settings → Providers.
- **No production deploy path.** Only the dev servers (Vite + uvicorn) and the Compose
  stack exist; there is no image build for production or a hosting story.

## MCP server limitations

- **One project, and it is implicit.** There is no projects endpoint, so
  `greenlit_list_projects` returns the single "Default project" entry built from
  `GET /api/v1/auth/me` plus the datasets and runs totals; it invents no second project.
- **Starts are local-only.** GreenLit stores the permission record on the run, and the MCP
  server never sets that record, so `greenlit_start_run` refuses anything that is not
  `localhost`/`127.0.0.1`/`::1`/`host.docker.internal`. Starting a run against a remote app
  stays a UI action.
- **No separate reasons list yet.** `greenlit_get_verdict` returns the API's single
  `verdict_reason` as the headline, sets `reasons` to null and says so instead of
  fabricating a breakdown.
- **Reports are truncated.** `greenlit_get_report` returns at most 100,000 characters with
  `truncated: true`; the small tools cap at 20,000. Fetch the full file from the API or the
  UI when the flag is set.
- **The live check is manual.** The MCP tests never touch a real GreenLit: they use a local
  fake API. Pointing the server at the dev stack needs real `GREENLIT_EMAIL`/
  `GREENLIT_PASSWORD` from the environment.

## Still marked "Coming soon"

### New Test entry points

| Entry point | Status |
| --- | --- |
| HTTP endpoint | Built |
| Website chatbot | Built as a cURL wizard over the HTTP endpoint |
| Prompt app | Built |
| Upload outputs | Built |
| MCP server | Built in M14: Streamable HTTP, one tool per target, URL only (no stdio) |

- **Settings sections:** none — every tab now renders a real panel (Connectors joined in M13;
  Account and Preferences in M12; Criteria and Safety render their catalogues read-only from
  `GET /api/v1/criteria` and `GET /api/v1/safety/sets`). What is still missing inside those
  panels: editing criteria weights, and any UI for the safety set picker — only the
  backend/API support exists (`safety_sets` on a run request, validated when the run is
  created).
- **Entry points on New Test:** Python function (traced), Built-in RAG app, Python SDK
  (traced), Docker image, Git repository, CLI command, and the disabled optgroup options
  beside them.
- **Test Chat:** manual chat with the app under test.
- The Playwright inventory currently contains 21 tests in 13 specs. The website chatbot
  spec was run against the disposable stack; the complete Playwright suite has not been
  rerun since it was added.

## M14 — An MCP server as the app under test

GreenLit can now test **one tool of an MCP server** (Streamable HTTP) instead of a chat
endpoint. This is the target side; the standalone `mcp_server/` in this repository is a
different thing (an MCP server *for* GreenLit) and was not touched.

### What exists

| Part | Where |
| --- | --- |
| Client | `app/services/mcp_client.py`: `McpSession` (initialize, tools/list, tools/call, DELETE), `McpToolSender` (one case), `normalize_tools` (bounded picker data) |
| Discovery | `POST /api/v1/targets/mcp/tools` — URL + encrypted header blob + the same permission and SSRF rules as an HTTP target |
| Header storage | `POST /api/v1/connectors/headers/encrypt` — a typed `Authorization` becomes the same encrypted blob a pasted cURL produces |
| Run request | `entry_point: "mcp_server"` with `mcp_tool`, `mcp_question_arg`, `mcp_extra_args` (size-validated, `extra="forbid"`) |
| Check | the existing target check, now accepting `entry_point` and the three MCP fields, so a remote server is checked once and accepted before a run |
| Executor | the worker builds one session per run, sends one `tools/call` per case, re-initialises once on a dead session and `DELETE`s at the end |
| Errors | `mcp_tool_error`, `mcp_protocol_error`, `mcp_transport_unsupported`, `mcp_session_expired` in `error_kinds` |
| UI | `frontend/src/components/McpPanel.tsx` + `frontend/src/lib/mcp.ts`, wired into `NewTestPage.tsx` (entry point, check, smoke and full run) |
| Docs | `docs/MCP.md` → "GreenLit testing an MCP server"; decisions D14.1–D14.6 |

### Tests actually run (measured in this step)

- `cd backend && python -m pytest` — **`699 passed, 1 skipped, 2 warnings in 528.58s
  (0:08:48)`**, exit 0. (669 before this step; the 30 new tests are 14 in
  `tests/test_mcp_client.py`, 13 in `tests/test_mcp_target.py`, one executor integration
  test in `tests/test_run_executor.py` and two encrypt-endpoint tests in
  `tests/test_curl_credentials.py`.)
- `cd frontend && npx vitest run` — **208 passed in 34 files** (195/32 before;
  `McpPanel.test.tsx` 7 tests, `lib/mcp.test.ts` 6).
- `npx playwright test --list` — **21 tests in 13 files** (unchanged).
- `ruff check .`, `ruff format --check .`, `mypy app` — clean (161 files formatted, 86
  source files); `npx tsc --noEmit` and `npm run lint` clean.
- Interop, against the official SDK's server (`mcp` 1.30.0, FastMCP, one
  `echo(text: str) -> str` tool), `backend/tests/support/mcp_interop_check.py`:
  `2025-06-18` negotiated, one tool listed with `suggested_question_arg: "text"`, two calls
  echoed exactly, `initializations` 1, `DELETE` 200 → **AGREEMENT, exit 0**.

### Known limitations

- **The browser path is NOT PROVEN.** No Playwright spec covers MCP: the e2e harness
  drives real local servers and a mock MCP server (JSON-RPC, session header, JSON-or-SSE
  negotiation, `DELETE`) was well past the size this step allowed. The backend, the check
  and the panel are each proven by their own tests; the click path is not.
- No stdio, no OAuth-protected servers, no legacy HTTP+SSE transport, one question
  argument plus static extras, text results only (non-text blocks are counted, not scored).
- Prettier still reports 9 pre-existing files (`src/lib/api.ts`, `src/lib/session.test.ts`,
  `src/components/WebsiteWizard.tsx`, `src/pages/NewTestPage.tsx` and their tests) — none of
  the files added in this step.

## M15 — What a refusal is called (the recurring 403)

### The finding, measured

The Website Chatbot's "anti-bot or CSRF challenge" message was produced by
`connectors._is_challenge_page`, which treated **any** 401/403 whose body looked like HTML
as an anti-bot challenge, and missed the opposite case: a CDN that blocks automation but
answers JSON fell through to "your session expired". Both errors were reproduced against
a local server serving the real response shapes (status, headers, body), running the real
`HttpConnector`:

| Response the site sent | Reported before | Reported now |
| --- | --- | --- |
| 403, `Server: cloudflare`, `cf-mitigated: challenge`, "Just a moment…" | `blocked_by_site` "anti-bot or CSRF" | `blocked_by_site`, names Cloudflare, evidence `cf-mitigated` + page text |
| 403, `Server: nginx/1.25.3`, plain "403 Forbidden" page | **`blocked_by_site`** (wrong) | `auth_error` "no session was sent" (correct) |
| 403, JSON `{"detail":"CSRF token missing."}` | `blocked_by_site` "anti-bot or CSRF" | `csrf_rejected`, says to paste a fresh cURL with the token |
| 403, `Server: AkamaiGHost`, JSON "Access Denied / Reference #18…" | **`auth_error` "session expired"** (wrong) | `blocked_by_site`, names Akamai |
| 401, site's login page (session gone) | **`blocked_by_site`** (wrong) | `auth_error`, "needs a signed-in session" |
| 401, JSON `invalid_token`, `WWW-Authenticate: Bearer` | `auth_error` | `auth_error`, "the cookie or token … has expired" |
| 403, JSON `{"error":"forbidden"}`, cookie sent | `auth_error` "session expired" | `auth_error`, "the account may not have access … or the firewall refused the shape" |
| 429, `Retry-After: 0` | `http_error` "target returned HTTP 429" | `http_error`, "the site is rate-limiting this runner … lower the request rate" |

Two header defects were found on the same path, both fatal to a request before the app
sees it: a Chrome "Copy as cURL" carries HTTP/2 pseudo-headers, and importing
`:authority` failed with `connector_error: Illegal header name b':authority'`; importing
the copied `content-length` failed with `Too little data for declared Content-Length`
(and a strict server would answer 400/403 instead). `Host`, the pseudo-headers,
`content-length` and `accept-encoding` are now dropped at import and again at send time,
so a target saved before the rule heals too. Cookies, `Origin`, `Referer`, `User-Agent`
and CSRF headers are kept.

### What exists now

| Part | Where |
| --- | --- |
| Classification | `app/services/site_diagnosis.py` — headers (`cf-mitigated`, DataDome, PerimeterX, Imperva, Sucuri, AWS WAF) and challenge-page text first, CSRF words second, status last |
| Codes | `blocked_by_site` (unchanged), `csrf_rejected` (new, `http_error` in the shared vocabulary), `auth_error` for 401/403 without evidence, `http_error` for 429 |
| Evidence | every refusal keeps `status_code`, the diagnostic response headers (allowlist, redacted, no `Set-Cookie`), the redacted snippet and an `evidence` list, in the check result and in the stored case detail |
| Header import | `app/utils/curl.py::clean_request_headers`, applied at import and in `HttpConnector.render_and_send` |
| Docs | README ("A refusal is named from its evidence"), `docs/REAL_WORLD_CHECKLIST.md` table, DECISIONS D15.1–D15.7 |

### Tests actually run

- `tests/test_site_diagnosis.py` — **19 passed**: one mock local server, eight real
  refusal shapes (Cloudflare challenge, nginx 403, CSRF JSON, Akamai JSON, expired login
  page, bearer 401, permission 403, 429), each asserting the code, the message, the
  evidence, the kept headers, that a challenge is called once and never retried, that no
  cookie reaches the detail, and that a 200 is never diagnosed; plus the run-level detail.
- `tests/test_curl_browser_headers.py` — **3 passed**: a Chrome copy keeps its session
  headers and drops client-owned ones, the pasted cookie and CSRF header reach the target
  with a correct `content-length`, and a target saved with `:authority` heals at send.
- Existing suites that own this code, unchanged: `test_quirk_failures`, `test_connectors_fake_app`,
  `test_target_errors`, `test_target_check`, `test_http_rate_control`, `test_curl_credentials`,
  `test_error_kind_timeout` — **121 passed**; `test_run_executor` — **32 passed**.
- Full backend suite, twice: the first run `1 failed, 719 passed, 1 skipped`
  (`test_http_rate_control.py::test_a_retried_case_records_the_final_attempt_and_the_wait_separately`,
  the known load-sensitive timing case — it passed 3/3 on its own and in the final run),
  the final run with every change in place `721 passed, 1 skipped, 2 warnings in 559.25s`, exit 0.
- `ruff check .` — All checks passed; `ruff format --check .` — 165 files already formatted;
  `mypy app` — Success: no issues found in 87 source files.

### Known limitations (unchanged by this work)

- A site that refuses automation stays refused: GreenLit names the product and stops. It
  does not solve a challenge, rotate a fingerprint or retry a block.
- The only authentication remains a pasted cURL's own headers, after the permission tick.
- No real third-party site was contacted for this investigation (by instruction); every
  row above is a local server serving that site's response shape.
- The Website Chatbot UI itself was not changed in M15, so its click path was covered by
  the same specs as before. The new messages were *claimed* for the UI by reading the code;
  M16 proves them in the browser.

## M16 — Proving the refusal in the browser, and a one-request diagnostic

### What M15 did not prove

The browser path. The check panel rendered only the shared `kind`, so every 401/403 read
"The site answered with an error (http_error)", and the Website Chatbot wizard rendered
nothing at all for `check.error`. The first run of the new spec failed on exactly this:
`Expected substring: "blocked_by_site" / Received string: "The site answered with an error
(http_error, HTTP 403)"` — the claim in the M15 report was wrong until the code was fixed.

### What changed

| Part | Where |
| --- | --- |
| The refusal's own name travels | `target_error.error_detail(code=...)`, filled from `ConnectorError.code` in `target_check.run_check`; `kind` stays one value per family |
| One block, both panels | `frontend/src/components/CheckRefusal.tsx` — the summary, a plain-words label with the code and status, the evidence list, the diagnostic headers |
| The wizard stops dropping it | `WebsiteWizard.tsx` renders `check.error`; `TargetCheckPanel.tsx` uses the same block |
| A real server for the browser | `tests/support/refusal_server.py`: `serve()` / `__main__` answers every mode by path, `GET /_calls` counts what was asked for, `GET /_health` is the probe |
| Harness | `scripts/run-e2e.sh` starts it on `E2E_REFUSAL_PORT` (9503), refuses a taken port, waits for health, logs to `e2e-refusal.log`, stops it with the rest |
| The proof | `frontend/tests/e2e-refusals.spec.ts` |
| Own-target diagnosis | `scripts/diagnose_target.py`, `backend/tests/test_diagnose_target.py` |

### Measured

- `bash scripts/run-e2e.sh tests/e2e-refusals.spec.ts`: first run **3 failed, 1 passed**
  (the `http_error` bug above, caught by the spec); after the fix **4 passed (28.0s)**, exit 0.
  Each case asserts the plain-words message, the code, the evidence, the headers, that a
  sentinel cookie and CSRF token never reach the page, and that the server saw **exactly
  one** request (counted on the server, not in the browser).
- `tests/test_diagnose_target.py` — **7 passed**: four refusal modes end-to-end through the
  script, a 200 that is not called a refusal, a remote host refused before any DNS or
  network call, and a file that is not a cURL.
- The flaky rate-control test: **10/10** alone, **3/3** while `vitest run` loaded the
  machine, and in the full suite — its fixed 400 ms margin is now a share of the measured
  exchange (`total - latency - waited` vs `max(10, total/50)`), so it still fails if the
  waits are counted as latency, and no longer fails when the machine is slow.
- Full backend suite with every change in place: `729 passed, 1 skipped, 2 warnings in
  602.96s (0:10:02)`, exit 0.
- `vitest run` — 208 passed (34 files); `npx tsc --noEmit`, `npm run lint` — clean.

## M17 — The check panel, in a browser

M16 proved the wizard. The check panel (`TargetCheckPanel`) was still covered by unit
tests only, and reaching it took two findings:

- The panel is offered only for a target that is **not** "on my computer", so a loopback
  refusal server is refused there by the SSRF rule (`allow_private_targets` is false on
  that path). The spec reaches the harness's server through `host.docker.internal` — the
  host's own name, already the documented e2e target host — and `scripts/run-e2e.sh` binds
  the refusal server to `0.0.0.0` for it, exactly as the demo servers are bound.
- The panel renders only once `detectResult` exists, and a refused auto-detect raises 400,
  so a refusing target never showed the panel at all. `refusal_server.py` now serves
  `POST /first-ok/<mode>`: a readable 200 for the first request, the real refusal after it.

| Proof | Result |
| --- | --- |
| `frontend/tests/e2e-check-panel-refusals.spec.ts` — nginx 403, CSRF JSON, Cloudflare challenge, 429 | **4 passed (37.0s)**, exit 0 |
| what each case asserts | plain-words message, refusal code, evidence, diagnostic headers, `run-full` disabled, `run-full-blocked` shown, sentinel cookie and CSRF token absent from the page, server counter `+1` |
| `npx playwright test --list` | **29 tests in 15 files** (was 25/14) |
| `npx vitest run --reporter=verbose`, five consecutive runs | 34/34 files and 208/208 tests passed, exit 0 each (`local-prompts/vitest-run-1..5.txt`) |

The single unexplained Vitest failure from M16 did **not** reproduce in five more full
verbose runs; cause unknown, and nothing was changed for it.

Known limitation: the four refusals reach the panel through the harness's own server and
the first request is answered 200 on purpose, because the panel only appears after a
successful first contact. A real third-party site was still never contacted.

## Gate-run rule (standing, from the M17 review)

A full gate run never pipes Vitest's output through `grep`, `tail` or `head`. It captures the
whole run to a file first, prints the last lines only afterwards, and reports the shell status:

```
npx vitest run --reporter=verbose > local-prompts/gate-vitest-last.txt 2>&1; echo EXIT=$?
```

Run from the repo root that path is correct; from `frontend/` it is `../local-prompts/…`.
If the run fails, that file is copied to `local-prompts/flake/FAIL-<timestamp>.txt` **before
anything else** — no rerun first — and the failing test's file, name and message are reported
from the copy.

## M18 — A shell that fills the window, and controls that look designed

### What was wrong

`frontend/src/styles/global.css` capped the content column at `--content-max-width: 1440px`
with no `margin-inline: auto`, so at 1920 the column stopped ~230px short of the right edge
while the *document*, not the main region, did the scrolling (`.app-shell` was
`min-height: 100%`, the sidebar a sticky `100vh` box). At 375 the top bar overflowed the
window. Separately, the pages used `form__label`, `form__hint`, `form__textarea`,
`form__advanced`, `form__curl-button` and `form__row`, and **none of those classes existed in
any stylesheet** — that is why New Test showed a raw browser select, a raw text input and a
plain grey wizard button.

### What changed

- `.app-shell` is `height: 100dvh` (with a `100vh` line above it) and `overflow: hidden`;
  the sidebar is `height: 100%` with its own `overflow-y: auto`; `main.page` is
  `flex: 1; min-height: 0; overflow-y: auto` and has **no max-width**; the top bar is a fixed
  flex row. `body` no longer scrolls; `.auth-page` scrolls itself, so the login card stays
  reachable in a short window.
- Below 800px the grid is `auto minmax(0, 1fr)`, and the account name (800px) and the
  provider pill (560px) drop out so the top bar stays one row with no horizontal scroll.
- The missing `form__*` classes are defined, plus one height/radius/border/focus rule for
  every `input`, `select` and `textarea` inside `.page`.
- Tokens: added `--measure: 72ch`, `--line-height-heading: 1.25`, `--line-height-snug: 1.4`,
  `--color-no-go-hover`, `--color-on-danger` (both themes); light `--color-go` is now
  `#0b7a22`. Removed `--content-max-width`, which nothing should cap the shell with.
- `.btn--danger` and a 1px `:active` nudge for every button variant.

### Measured

| Proof | Result |
| --- | --- |
| `frontend/tests/e2e-ui-shell.spec.ts` (new, 4 tests) | **4 passed (56.2s)** |
| shell box = viewport within 1px at 1920x1080/1440x900/1280x800/375x800, no horizontal scroll, document never scrolls, sidebar = window height above 800px | asserted per size |
| 375x800: `main.scrollTop` changes by 240 while `document`/`body` stay at 0 | asserted |
| short windows 1280x500 and 375x500: login container `overflow-y: auto`, submit button inside the window after scrollIntoView | asserted |
| 640x400 (1280x800 at 200% zoom): main scrolls, nav still navigates to Settings | asserted |
| light theme GO on Results | `rgb(11, 122, 34)`, measured 5.50:1 on the page and 4.82:1 on the badge fill (was 2.13:1) |
| `e2e-session-refresh`, `e2e-website-wizard`, `e2e-check-panel-refusals`, `e2e-refusals` (one at a time) | 2/1/4/4 passed |
| `npx vitest run` | 34/34 files, 208/208 tests, exit 0 |
| `npx tsc --noEmit`, `npm run lint` | exit 0, exit 0 |
| `npx playwright test --list` | 33 tests in 16 files (was 29 in 15) |

### Not proven

- Test Chat has no composer yet (it is a "coming soon" empty state), so "the composer stays
  pinned" is **not** implemented or claimed; the spec only proves its heading sits inside
  the window unscrolled.
- No modal, dialog, dropdown or toast exists in the app, so "nothing is clipped" was checked
  by grep (none) rather than by opening one; the `<select>` dropdowns are drawn by the browser.
- Tables wider than the window on a phone: Results shows no runs in the screenshot pass, so
  the "table scrolls inside its own container" case was not exercised.
- Screenshots are Chromium at the listed sizes; other browsers were not looked at.

## M19 — A sidebar that folds away, and nothing else changed

### What was added

One toggle in the sidebar's brand row (`data-testid="sidebar-toggle"`, `aria-label` "Collapse
sidebar" / "Expand sidebar", `aria-expanded`, `title`), which folds the 248px sidebar into a
56px rail (`--sidebar-width-collapsed`) of letter badges. Each badge is `aria-hidden` and the
real label stays in the link as a clipped-but-readable span, so the link's accessible name and
`getByRole("link", { name })` are unchanged; the label is also the `title` tooltip. State is
stored under **`greenlit-sidebar-collapsed`** (`"true"` / `"false"`), read in the `useState`
initialiser so there is no open-then-shut flash, and every `localStorage` call is wrapped in
`try/catch` — a blocked storage means "expanded" and a working toggle, not a crash.

The rail exists only above the existing 800px strip breakpoint: `.app-shell--collapsed` and the
`sidebar__link-mark` rules live inside `@media (min-width: 801px)`, and `.sidebar__toggle` is
`display: none` at or below 800px.

### The mobile drawer: skipped, with evidence

STEP 0 asked whether the existing strip is usable at 375px before building a drawer. Measured on
the real stack: **5 links, 173px tall (two rows), every entry inside the window, no horizontal
scroll** (`local-prompts/e2e-sidebar-before.log`, `before-sidebar-375x800-dark.png`). So the
strip is fully usable and no drawer, hamburger or overlay was built. No existing nav, route,
label, active-link style, class name or testid was touched — the only markup change is the new
buttons/spans described above.

There are no "soon" badges in the sidebar (they live in Settings), so the "soon badge becomes a
dot" case has nothing to act on.

### Measured

| Proof | Result |
| --- | --- |
| `src/components/Layout.test.tsx` (new, 5 tests) | **5 passed**: same labels/order/hrefs/titles, toggle flips `aria-expanded` + rail class + testid and persists, Enter and Space work, stored `"true"` restored on first render, throwing `getItem`/`setItem` still renders expanded and toggles |
| `tests/e2e-ui-shell.spec.ts` (now 5 tests) | **5 passed (56.0s)** — new test: collapse → rail ≤64px, shell still equals the 1280x800 viewport within 1px, no horizontal scroll, stored value `"true"`, reload keeps it shut, a link still navigates with the rail folded and keeps `sidebar__link sidebar__link--active`, light theme captured expanded and collapsed |
| `npx vitest run` | 35/35 files, 213/213 tests, exit 0 (was 208; no existing test edited) |
| `npx tsc --noEmit`, `npm run lint` | exit 0, exit 0 |
| screenshots | `after-sidebar-default-1280x800-dark.png`, `after-sidebar-collapsed-1280x800-dark.png`, `after-sidebar-collapsed-1280x800-light.png`, `after-sidebar-expanded-1280x800-light.png` |

Default desktop is unchanged apart from the new toggle now sitting at the right of the brand row
(same 248px width, same nav offsets, same active styling); the after-default screenshot is
`after-sidebar-default-1280x800-dark.png` against `before-sidebar-1280x800-dark.png`.

### Not proven / limitations

- Letters, not icons: the app ships no icon set, so the rail shows N/R/C/T/S inside a badge.
- The version line (`GreenLit v0.1.0`) is hidden in the rail — 40px of content cannot hold it.
- A nav item whose first letter collides with another's would be ambiguous in the rail; the five
  current labels are distinct, and nothing enforces that.
- No test presses Escape or asserts the focus ring on the toggle; the ring is the global
  `:focus-visible` rule, and Escape has nothing to close in this implementation.
- Collapsing then resizing below 800px leaves the stored preference intact and the strip normal;
  that transition is not asserted by a test.

- Vitest flake in `PreferencesPanel.test.tsx` ("restores the account's stored preference on load"): the test read `documentElement.dataset.theme` in the same breath as a `waitFor` on the theme radio, while the attribute is written one commit later by `ThemeProvider`'s effect; it now waits for the attribute itself, and the cause was identified from the saved failure log `local-prompts/flake/FAIL-20261108-091024.txt` (earlier unexplained Vitest failures may or may not be this same race).
