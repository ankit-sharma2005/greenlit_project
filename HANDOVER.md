# GreenLit — Handover notes

> Living document. It reflects the repository as of the baselines, human-review and audit
> milestone (M6 runs, M7 judge and calibration, M8 safety, spec 8.5 reports and
> regression). Everything below is exercised by a command in this file; nothing in it is a
> plan.

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
  `connectors`, `datasets`, `evaluations`, `runs` (including baseline and report), 
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
- `models.py` — users, refresh tokens, password resets, audit events, providers,
  datasets/versions/items, runs/items, metric results, judge profiles.
- `demo_server.py` + `services/demo.py` — the built-in helpdesk app (good/broken modes)
  and the shipped golden dataset, used by "Try the demo" and by the tests.

**Frontend (`frontend/src`)** — React 19 + TypeScript + Vite, React Router, CSS custom
properties with a dark default and a light theme.

- `pages/` — `NewTestPage` (the three entry points and the live run), `ResultsPage`
  (run history, compare, ad-hoc scoring), `CalibrationPage` (review queue and kappa),
  `SettingsPage` (Datasets, Providers, Criteria, Judge, Safety, Audit log), auth pages,
  `TestChatPage` (not built).
- `components/` — the pieces the pages compose: `PromptAppPanel`, `UploadOutputsPanel`,
  `DemoPanel`, `RunProgressPanel` (progress → verdict card → exports), `BaselinePanel`
  (baseline control and the regression table), `SafetySection`, `SafetyPanel`,
  `CriteriaPanel`, `ReportExport`,
  `RunHistory`, `JudgePanel`, `ProvidersPanel`, `DatasetsPanel`, `ReviewQueue`,
  `CalibrationSummary`, `SetupChecklist`, `AuditPanel`.
- `lib/` — typed API clients, one module per area, all going through `lib/api.ts` so the
  session cookie and the error envelope are handled in one place.

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
  The suite currently collects 542 tests (1 skipped), and a full run on 2026-11-01 exited
  0; `tests/test_operations.py` covers the
  percentile edge cases (one case, even and odd counts, all failures), and
  `tests/test_error_kind_timeout.py` proves a real timeout against a local slow server
  (plus connection-refused and the old-run text fallback). `tests/test_http_rate_control.py`
  and `tests/test_http_streaming.py` run real local servers for the retry/`Retry-After` and
  SSE/NDJSON/text/stall/oversize behaviour, and `tests/test_curl_credentials.py` uses a
  server that refuses anything without the imported cookie and bearer token.
- Frontend component tests are Vitest + Testing Library next to the components; the
  suite is currently 128 tests in 25 files (including `NewTestPage.test.tsx`, which proves
  the permission box is required and that the attack-probe box starts off).
- `frontend/tests` is the Playwright suite (18 tests in 11 specs): admin/accounts and the
  results page, Try the demo, baseline regression, calibration (label → kappa), judge
  provenance, the prompt app (prices typed into the provider's row in Settings, then
  the priced cost estimate on the verdict),
  report download, safety both ways, the setup checklist and audit screen, uploaded
  outputs, and PDF dataset generation through preview and approval.
  It runs against fake apps started inside the test process (`tests/helpers.ts`), so no
  real model is needed. The last full run from a clean stack passed all of them:
  `17 passed (7.1m)`, exit code 0. `e2e-report.spec.ts` then gained a second test (a
  streamed SSE target reaches a GO, and the permission box is required first); running
  that spec alone on a clean stack passed: `2 passed (1.5m)`, exit code 0.
- `scripts/run-e2e.sh` uses a uniquely named Compose project per invocation (Postgres 5536,
  Redis 6482, fresh volume), the API on 8103, a solo Celery worker, Vite on 5277 and the two
  demo helpdesks on 9501/9502. It stops only that invocation's containers, preserves its
  volume, and never touches the stack you use in the browser. After Playwright it runs the
  CI runner against the healthy demo app.
- `scripts/greenlit_ci.py` uses only the Python standard library: it logs in with
  `GREENLIT_EMAIL`/`GREENLIT_PASSWORD`, creates a quick test, polls to completion, prints the
  verdict, weighted score and failed instrumented metrics, and returns documented CI exit
  codes. Fake-server tests cover GO, NO_GO, REVIEW, timeout and authentication failure.

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

## Still marked "Coming soon"

- **Settings sections:** Connectors (saved targets), Account, Preferences. (Criteria and
  Safety are no longer placeholders: each tab renders its catalogue read-only, from
  `GET /api/v1/criteria` and `GET /api/v1/safety/sets`. Editing criteria weights or the
  safety set is not built, and the Safety set picker has no UI — only the backend/API
  support exists: `safety_sets` on a run request, validated when the run is created.)
- **Entry points on New Test:** Python function (traced), Built-in RAG app, Python SDK
  (traced), Docker image, Git repository, CLI command, and the disabled optgroup options
  beside them.
- **Test Chat:** manual chat with the app under test.
- **Tests still to be run when Docker is available:** none of the current suite is
  skipped — all 17 Playwright tests are exercised against the disposable stack — but any
  browser-level coverage of the features in the two lists above will have to be added with
  them.
