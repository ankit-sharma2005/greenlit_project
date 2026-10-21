# GreenLit Project Handover

## Scope and verification snapshot

This document describes the repository as inspected, not the aspirational
specification alone. The root `.env` values and database contents were not
read or copied into this report. The existing Git worktree already contained
uncommitted Project Connector changes when this review began; those changes
were preserved. This handover document is the only file added for the review.

Verified during this review:

- `docker compose config --quiet` succeeded. PostgreSQL, Redis, API, worker,
  and web containers were running and reported healthy.
- `GET /healthz`, `GET /readyz`, `/docs`, and the web root returned HTTP 200.
  `/readyz` returned `{"status":"ready"}`.
- The running API reported Alembic revision
  `0010_eval_run_judge_snapshot (head)`.
- From the API container, `host.docker.internal` resolved and the host
  Ollama `/api/tags` endpoint returned HTTP 200. This confirms network
  reachability, not successful model inference through GreenLit's provider
  gateway.
- No `ERROR`, `CRITICAL`, or `Traceback` lines were found in the last 24 hours
  of API, worker, and web logs. Only the count was inspected; raw logs were not
  copied because logs can contain user or upstream data.
- Backend: Ruff lint passed and `pytest -q tests` passed with **103 passed**
  using an in-memory SQLite database (2 dependency deprecation warnings).
  Ruff format check and strict mypy did not pass; details are below.
- Frontend: ESLint, TypeScript, Prettier check, Vitest (**17 passed**), and
  Vite production build passed.
- `npm audit` reported **8 vulnerabilities** in the frontend dependency tree:
  5 moderate, 1 high, and 2 critical. Several suggested remediations require
  major-version upgrades.

## 1. Project overview

### What GreenLit is for

GreenLit is an offline, pre-launch evaluation workbench for LLM-powered
applications: chatbots, RAG systems, agents, and extraction workflows. Its
intended value is to run a fixed, reviewed dataset against a saved application
configuration, score the traces against task-specific criteria, and provide a
repeatable launch decision and regression comparison. It is not a general
foundation-model benchmark.

The intended flow is: create a workspace and project; configure a provider
when the app needs one; connect an application or upload its existing outputs;
create/upload and approve a dataset; configure judge profiles and verdict
criteria; run an evaluation; inspect traces and scores; compare against a
baseline; export a report; and iterate on the application using the same
dataset.

### Architecture and technologies

| Layer | Implementation |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, React Router, hand-authored CSS. `App.tsx` provides the landing/auth/workspace shell; `WorkspaceProjects.tsx` hosts workspace pages and `DatasetStudio.tsx` handles dataset workflows. |
| API | FastAPI under `/api/v1`, Pydantic v2 request/response models, SQLAlchemy 2 async sessions, and dependency-based user/role checks. |
| Persistence | PostgreSQL in Compose; Alembic migrations; SQLAlchemy models in `backend/app/models.py`. SQLite is also configured as the backend's local fallback and is used for isolated tests. |
| Background work | Celery worker with Redis broker and result backend. Evaluation runs are persisted and processed by `services/run_engine.py`; event progress is exposed over SSE. |
| LLM access | `services/llm_gateway.py` uses the OpenAI Python SDK against OpenAI-compatible endpoints, with provider records, encrypted credentials, provider fallback chains, timeout handling, and an in-process rate limiter. Ollama URLs are normalized to include `/v1`. |
| Connectors/evaluation | `services/connectors.py` runs supported application entry points and returns output, latency, usage, and trace fields. `services/metrics.py`, `verdicts.py`, and `comparison.py` implement scoring, launch verdicts, and baseline comparison. |
| Deployment | Root `docker-compose.yml` starts `postgres`, `redis`, `api`, `worker`, and `web`; root `Dockerfile` does not exist. Backend and frontend have separate Dockerfiles. The Compose web service runs the Vite development server, not a production web server. |

Provider/API keys are configured through the UI and encrypted before persistence.
In development, `services/secrets.py` derives its Fernet key from `SECRET_KEY`
when `ENCRYPTION_KEY` is absent; outside development it requires
`ENCRYPTION_KEY`. The actual `.env` is git-ignored and was not inspected.

### Repository map

| Path | Role |
| --- | --- |
| `backend/app/` | Application settings, DB/session setup, models, schemas, auth/security, routers, domain services, and Celery worker. |
| `backend/alembic/versions/` | Ten migrations, through `0010_eval_run_judge_snapshot`. |
| `backend/tests/` | Auth, connectors/providers, datasets/runs, metrics, verdicts, regression, safety/review helpers, CI, demo, and tracing tests. |
| `frontend/src/` | App shell, API client, workspace/project UI, connector payload builder/parser, Dataset Studio, chat, CSS, and Vitest tests. |
| `docs/` | `PROJECT_SPEC.md` (aspirational product requirements), `PROGRESS.md` (phase evidence), `AUDIT.md` (older audit), and manual test notes. |
| `greenlit_demo/` | Small golden dataset and good/broken output CSVs plus a demo guide. |
| `scripts/` | Demo seeding, report export, and research-analysis scripts. |
| `presentation/` | Project overview, architecture, phase, results, and demo material. |
| `outputs_good.csv` | Root-level one-row example for the uploaded-output connector. |
| `docker-compose.yml`, `.env.example`, `pyproject.toml`, `Makefile` | Compose stack, safe environment template, Python lint/type configuration, and developer shortcuts. |

Generated/developer-specific material such as `.venv`, `node_modules`, caches,
`.tmp`, `.deepeval`, and `.env` is not source documentation. Avoid copying
database files or environment values into reports or commits.

### API surface

The live OpenAPI document is at `http://localhost:8000/docs` and
`/openapi.json`. The registered API groups include:

- Auth: signup, login, refresh, logout, `/auth/me`, password-reset request and
  confirmation.
- Workspace: listing, preferences, audit, and role-oriented overview helpers.
- Providers: list/create/test/rename/delete, including saved-provider
  connection tests.
- Projects/connectors: project CRUD, app versions, connector list/test/save/
  rename/delete, and entry-point registry.
- Datasets/evaluation: dataset list/upload/generate/version/review; run
  create/list/detail/items, pause/resume/cancel, and SSE events.
- Metrics/verdicts/results: metric catalog, verdict criteria, run reports
  (JSON, HTML, PDF, CSV), baseline promotion, run comparisons, and regression
  reports.
- Chat: workspace preferences and conversations, project Test Chat, draft
  dataset items, retention/deletion.
- Human-review helpers: review queue/calibration/blind comparison/override/
  final-report endpoints (stateless; see status below).
- CI: API-token CRUD and `/ci/regression-check`.
- Health: `/healthz` (liveness) and `/readyz` (database readiness).

There is no separately mounted router for the safety helper module. The API
does not expose a Prometheus `/metrics` endpoint.

## 2. Current project status

“Working” means behavior is supported by relevant tests and, where noted, live
checks. A test against a mock provider is not evidence of a successful
production provider call.

| Feature | Status | Evidence and limits |
| --- | --- | --- |
| Compose startup, API/web connectivity, PostgreSQL migrations | **Working (local development)** | Compose configuration validates; all five containers healthy; HTTP smoke checks passed; current migration is `0010`. |
| Authentication and workspace RBAC | **Working in tested flows** | Backend auth tests cover signup/login/refresh/logout/reset and workspace access restrictions. No live browser signup was performed in this review. |
| Provider management and OpenAI-compatible gateway | **Partially working** | Provider CRUD, test gates, normalization, fallback, and errors are covered by mocked tests. The host Ollama endpoint is reachable from the API container, but the gateway's model inference was not tested. GitHub Models/custom-provider live calls require user credentials and were not tested. |
| HTTP endpoint connector | **Partially working** | Pydantic validation, test calls, credential redaction, and SSRF checks have backend tests. A real target app call was not made. Private targets need the connector's explicit owner/admin setting. |
| Prompt App, built-in RAG, built-in Agent | **Working as tested; live provider unverified** | Prompt/RAG/agent paths and tool argument validation have backend tests using mocked provider responses. They need a saved provider for real inference. |
| UPLOAD_OUTPUTS connector | **Working as tested** | CSV/JSON/JSONL/XLSX parsing and mapping have backend/frontend tests; `outputs_good.csv` supplies one example output row. No provider is needed for this connector. |
| Dataset upload, generation, review/versioning | **Partially working** | Upload, validation, generation contract, and versioning are implemented and tested. Generation requires a live provider; no production-scale/large-upload test was performed. |
| Evaluation run execution and SSE | **Partially working** | Celery run engine supports persisted items, pause/resume/cancel, and event streaming; suite passes. A real provider-backed evaluation was not run in this review. Redis broker state is not persisted by Compose. |
| Metrics, judge profiles, verdicts, reports | **Working as tested; judge integration unverified** | Deterministic metrics/verdict logic and report formats are covered by tests. LLM judge tests are mocked; report content depends on populated run data. |
| Baseline comparisons/regression calculations | **Working as tested** | Baseline, paired comparison, statistical helper, and regression tests exist. The CI endpoint is not an actual database-backed evaluation/regression execution (see bug below). |
| Safety/red-team | **Partially working** | `services/safety.py` contains attack-pack and calculation helpers, but there is no integrated persisted red-team run, review UI, or safety launch gate. |
| Human review/calibration | **Partially working** | Phase 8 routes invoke calculation helpers, but the queue and override are not persisted as a review workflow and there is no human-review UI/audit trail. |
| Website URL and MCP | **Not available end to end** | Models/handlers and contract tests exist, but entry-point registry metadata marks them unavailable and API validation rejects them pending real browser/MCP verification. |
| Python function/SDK traced, Docker image, Git repo, CLI, Proxy | **Not available through the supported connector API** | Registry metadata says `implemented: false`; `validate_connector_settings` rejects these before normal test calls. Some helper branches exist in `connectors.py`, but must not be treated as supported or safely isolated execution. |
| CI token check | **Partially working / unsafe pass semantics** | Token validation and response tests exist, but the route summarizes caller-supplied checks and defaults missing checks to PASS; it does not run the stored evaluation/baseline itself. |
| Frontend pages | **Partially working** | Overview, providers, projects, connector, Dataset Studio, evaluation, results, Test Chat, and settings routes exist. Automated frontend checks pass. A complete authenticated browser E2E workflow has not been verified. |
| Production deployment | **Not ready** | Compose is development-oriented: API reload, Vite dev server, static DB credentials, all-interface published ports, weak default secret behavior, and unresolved dependency/mypy/format findings. |

## 3. Important bugs, risks, and configuration issues

Priorities reflect impact on correctness/security, not whether a failure is
currently visible in local smoke tests.

| Priority | Finding and evidence | Reproduction | Recommended fix |
| --- | --- | --- | --- |
| **High** | **CI can return a false PASS.** `routers/phase9.py::ci_regression_check` fabricates three passing checks when `checks` is missing. `services/ci.py::normalize_ci_status` treats unknown/empty values as PASS and `summarize_ci_status` returns PASS for an empty list. The endpoint does not load an evaluation run or approved baseline. | Create a valid CI API token, call `POST /api/v1/workspaces/{workspace_id}/ci/regression-check` with the token and omit `checks`; it returns passing checks/status without running tests or comparing an evaluation. | Reject absent/empty/unknown check states; require explicit results. For true regression gating, resolve a run/baseline and calculate status server-side. Add tests proving missing data cannot pass. |
| **High** | **Production secrets can remain on development defaults.** `config.py::Settings.secret_key` defaults to a known development placeholder and there is no validation rejecting that value when `APP_ENV=production`. Compose requires a non-empty `SECRET_KEY`, but `.env.example` is development-oriented and Compose can still start with its placeholder. `ENCRYPTION_KEY` is only rejected when secret operations are attempted outside development. | Set `APP_ENV=production` while leaving `SECRET_KEY` at the template value; startup does not fail closed. | Validate a strong, non-default signing secret at startup for non-development environments; require valid `ENCRYPTION_KEY` during startup; document secure generation/rotation and test both rejected defaults. |
| **High (deployment exposure)** | **Compose publishes PostgreSQL and Redis on all host interfaces and uses a static database credential.** `docker-compose.yml` maps ports `5432:5432` and `6379:6379` without loopback binding and embeds a fixed DB password. This is acceptable only for a controlled local demo, not a shared/untrusted network. | Inspect the Compose port mappings and run the stack on a machine reachable from another host. | Bind development-only DB/Redis ports to `127.0.0.1`, load the DB credential from a required secret, and do not expose data services in production. Add a separate production Compose/deployment profile. |
| **High (toolchain risk)** | **Frontend dependency audit reports 8 advisories:** 5 moderate, 1 high, 2 critical. Direct affected packages include Vite, Vitest, and `react-router-dom`; the audit's recommended versions require major upgrades. | From repository root, run `npm audit --prefix frontend`. | Review advisory reachability, update and pin compatible maintained major versions with a migration plan, then rerun tests/build and audit. Do not apply a blind `npm audit fix --force`. |
| **Medium** | **Strict backend mypy fails.** `mypy --strict app alembic tests` from `backend` reports 7 errors: an untyped Celery import in `app/worker.py` and six test typing errors in `tests/test_phase2.py` (module-private `connectors.socket`/`HttpEndpointSettings` references and a `str` where Pydantic expects `Url`). | Run the strict command from the execution guide. | Add/declare an appropriate Celery typing strategy and adjust test imports/types to use public symbols and validated URL values; restore strict mypy as a required passing gate. |
| **Medium** | **Ruff formatting check fails on two files.** `ruff format --check app alembic tests` reported `app/services/connectors.py` and `tests/test_phase2.py` would be reformatted. Ruff lint itself passed. | Run the formatter check from `backend`. | Review and format those files in a separate change, then check the diff and rerun tests. This handover review did not format or modify application files. |
| **Medium** | **Provider SSRF validation fails open on DNS lookup errors.** `services/llm_gateway.py::_validate_provider_target` returns from `except socket.gaierror`, so an unresolved hostname is not rejected at validation time. The HTTP request will commonly fail later, but the policy should not rely on a second DNS lookup behaving identically. | Configure a provider URL whose hostname fails resolution during validation; observe validation returns instead of raising the private-host error. | Fail closed on resolver errors and bind validation to the actual connected address; ensure redirects and DNS rebinding cannot bypass public-address checks. |
| **Medium (suspected)** | **DNS rebinding window in HTTP connector validation.** `_check_target_is_public` resolves and checks the host, then `httpx` resolves it again for the request. The request is not pinned to the checked address. No exploit was demonstrated; this is a code-level SSRF risk. | A controlled test host would need to return a public address during validation and a private address for the subsequent connection. Do not test against third parties. | Pin the validated address or use a transport that enforces the allow/deny decision at connect time; keep redirects disabled and cover IPv4/IPv6 cases in tests. |
| **Medium** | **Local Ollama requires explicit allow-list configuration.** `ALLOWED_PRIVATE_HOSTS` is empty in `.env.example`; provider target validation blocks private IPs unless the exact hostname is allow-listed. `host.docker.internal` and host Ollama were reachable from this API container, but a provider test through the gateway was not made. | Configure an Ollama provider at `http://host.docker.internal:11434` while `ALLOWED_PRIVATE_HOSTS` is empty; the private-target guard can reject it before model inference. | Document `ALLOWED_PRIVATE_HOSTS=host.docker.internal` for trusted local Ollama only, recreate API/worker after changing env, and keep connector private-target approval separate and explicit. |
| **Medium** | **Rate limiting is process-local.** `services/rate_limit.py::ProviderRateLimiter` stores locks, queues, and daily counters in memory. API/worker processes do not share limits and a restart resets the counters. | Run concurrent requests through separate processes or restart the process and compare counts. | Move counters/leases to Redis or another shared atomic store; define how a daily quota pause is resumed after process restart. |
| **Medium** | **CI token scopes are recorded but not enforced by the token validator.** `services/ci.py::validate_api_token` checks hash, active status, and expiry; it does not check the stored `scopes`. The token-create endpoint also does not visibly check the caller's workspace membership/role before storing the requested workspace ID. | Create a token with a deliberately narrow scope and call the CI route; compare with a token having a CI scope. Exercise creation against a workspace the user does not belong to in an isolated test. | Enforce scope and workspace membership at creation and use; restrict token creation to authorized roles and test cross-workspace denial. |
| **Low/Medium** | **Readiness only verifies PostgreSQL.** `/readyz` in `main.py` executes `SELECT 1`; it does not check Redis/Celery. Compose has separate health checks, but the API readiness endpoint can remain ready while background evaluation enqueueing is unavailable. | Stop Redis while keeping API/Postgres up and query `/readyz`. | Decide whether readiness should include Redis for run-creation paths; expose clear component health without making liveness depend on optional providers. |
| **Low** | **Docs are stale and inconsistent.** `README.md`, `docs/PROGRESS.md`, and `docs/AUDIT.md` report older test counts/status dates (the phase progress tail says 92 backend and 9 frontend tests; current verified counts are 103 and 17). Phase and entry-point descriptions have evolved. | Compare the dated progress/audit text with the live OpenAPI registry and current test run. | Update phase status, test evidence, and deferred entry points as part of documentation maintenance; keep one canonical verification snapshot. |

No current 502 or 404 was observed in the live health/docs checks. The 502
responses in the API are intentional translations of upstream provider/target
errors in some routes; they do not establish that the GreenLit API itself is
unavailable. See the next section for past issue checks.

## 4. Previously encountered issues

| Reported issue | Current assessment |
| --- | --- |
| HTTP 502 Bad Gateway | **Not currently observed; still possible for upstream failures.** Health/docs endpoints returned 200. Provider/generation and connector routes translate some upstream provider failures into 502. Real provider inference was not tested, so provider credentials/model compatibility remain unverified. |
| HTTP 404 Endpoint Not Found | **Not currently observed on the app/API smoke routes.** OpenAPI is served and frontend requests use `/api/v1`. A target application's wrong path can still yield `Endpoint returned HTTP 404`; verify the target URL/method rather than changing GreenLit routes. |
| GreenLit blocking private/local URLs | **Intentional protection, not universally a defect.** HTTP connectors deny private destinations by default. An owner/admin must enable `allow_private_targets` for an approved connector. Provider URLs use a different exact-host allow-list, `ALLOWED_PRIVATE_HOSTS`. |
| Docker containers cannot reach host applications | **Base networking is working in this environment.** From the API container, `host.docker.internal` resolved and the host Ollama tags endpoint returned HTTP 200. A particular host application may still bind only to loopback, use the wrong port/path, or be blocked by the connector/provider SSRF guard. |
| Ollama connectivity | **Host endpoint reachable; GreenLit model request not verified.** URL normalization and mocked-provider behavior are tested. To test through GreenLit, configure a reachable model and allow-list `host.docker.internal` for provider access; then use the provider's Test connection in the UI. |
| Provider configuration/API key errors | **No live provider error reproduced.** Provider tests are predominantly mocked. Saved secrets are encrypted and omitted from provider output per tests. A 401/403 or 404 from the provider is an upstream credential, permission, model, or URL issue; check its raw status without sharing the key. |

## 5. Improvements to the existing implementation

| Area | Why it matters | Concrete next step |
| --- | --- | --- |
| Security/configuration | Signing keys, connector credentials, provider URLs, and host ports determine whether a local-only application is safe outside a developer machine. | Fail closed on production defaults, harden outbound IP enforcement, bind local data ports to loopback, and enforce API-token scopes/workspace access. |
| CI correctness | A false PASS can turn an incomplete or failed check into a misleading launch signal. | Replace default-PASS behavior with required validated checks and add server-side evaluation/baseline computation. |
| Provider reliability | Process-local rate limits and the absence of a live inference check leave quota and restart behavior uncertain. | Shared quota state, bounded retry/backoff policy, request IDs, safe structured logs, and a documented live-provider smoke test. |
| Evaluation workflow | The worker/run model is implemented, but real external-provider and worker-recovery acceptance is not established by mocked tests. | Add a repeatable Docker-backed integration test with a local mock OpenAI-compatible server and a worker restart/recovery test. |
| API consistency | The API uses typed schemas in many core routes, but phase 8/9 routes accept generic dictionaries and sometimes silently choose permissive defaults. | Use strict Pydantic request/response models, consistent error envelopes, and explicit validation for token scopes, check names, and statuses. |
| Frontend UX | The main workspace is a single large component and live E2E coverage is incomplete. | Split page-level components/hooks incrementally; add browser tests for signup-to-report and connector failure paths. |
| Performance/reliability | The app targets a small local team, but exports, run-item lists, and trace JSON can grow with data. Redis broker state is ephemeral. | Add pagination/limits and payload-size tests; document backup/recovery and use Redis persistence or recoverable enqueue scheduling. |
| Observability | Readiness checks the DB only, and run failure details are stored/logged with limited context. | Add correlated request/run IDs, sanitized structured logs, worker/Redis readiness, and a minimal metrics endpoint. Never log credentials or full sensitive prompts by default. |
| Test quality | All current backend tests pass, but mypy/format checks fail and live external integrations are unverified. | Make Ruff format, strict mypy, npm audit review, full tests, and one local provider-backed integration test required CI gates. |
| Documentation/deployment | Existing docs describe older test counts and Compose is a development stack. | Refresh the current-state docs and publish a separate deployment guide/profile rather than calling the dev Compose stack production-ready. |

## 6. Missing features to add (without duplicating existing functionality)

| Feature | Existing status | Priority / effort / dependency |
| --- | --- | --- |
| Multiple provider types and custom OpenAI-compatible URLs | **Implemented** in provider records and `LLMGateway`; live behavior is not verified for every vendor. Improve model discovery and compatibility tests rather than adding a duplicate provider layer. | P1 reliability; medium effort; build on gateway tests. |
| Configurable target application endpoints | **Partially implemented** via HTTP endpoint settings, method/body template, headers, response mapping, and explicit private-target approval. Add structured authentication options, tested error guidance, and address-pinning SSRF defense. | P0 security; medium effort; before enabling more outbound connector modes. |
| Automated test-case generation | **Partially implemented** by provider-backed template generation. Quality filtering, semantic deduplication, self-verification, and coverage reports are absent. | P1; medium effort; depends on safe provider calls and dataset review. |
| Prompt injection/jailbreak testing | **Partially implemented** as a helper attack pack and mocked judge-related tests; no persisted execution workflow. | P1; high effort; depends on a red-team runner, result model, and safety gates. |
| Harmful output/policy detection | **Partially implemented** helper calculations only; no integrated policy classifier/run or hard gate. | P1; high effort; define versioned policies and validation before scoring. |
| Hallucination/response-quality evaluation | **Partially implemented** using answer-match heuristics, trace/context metrics, and optional LLM judges. No robust grounding/claim verification guarantee. | P1; high effort; improve dataset references, judge validation, and rubric/versioning. |
| Configurable suites | **Partially implemented** through dataset versions, categories/splits, metrics, criteria, and judge profiles; no full named reusable suite abstraction across projects/versions. | P1; medium effort; build on existing immutable dataset and criteria snapshots. |
| Test history and progress | **Partially implemented**: runs, per-item status, SSE, pause/resume/cancel, and reports exist. Add retained history UI, recovery/retention policies, and worker restart evidence. | P1; medium effort; depends on durable queue/worker acceptance. |
| Risk scoring/severity classification | **Partially implemented** through GO/REVIEW/NO_GO, hard gates, readiness issues, and regression-critical items. A unified finding severity model is missing. | P2; medium effort; requires persisted safety findings and policy agreement. |
| Dashboard/statistics | **Partially implemented**: workspace overview and reports exist; broad trend, quality, cost, and safety dashboards are limited. | P2; medium effort; depends on stable persisted evaluation data. |
| Exportable reports | **Implemented** for JSON, HTML, PDF, and CSV. Improve provenance and safety findings as those features become persisted. | P2 maintenance; low/medium effort. |
| Authentication/access control | **Partially implemented**: email/password, access/refresh tokens, workspace roles, and API tokens exist. Email verification, login throttling, session management UI, strict token scopes, and full token lifecycle are missing/incomplete. | P0 security; medium effort; strengthen existing auth rather than replacing it. |
| Execution status/progress | **Partially implemented** via run status endpoints/SSE and Celery. More reliable across Redis/worker restart is not proven. | P1; medium effort; depends on queue durability and integration tests. |
| Safe sandbox entry points | **Not implemented as supported workflows** despite some helper code: Python, Docker, Git, CLI, Proxy, Website discovery, and MCP remain blocked by registry validation. | P2; very high effort; only proceed with isolated runners, resource/network/filesystem boundaries, and security review. |
| Embeddings, cost tracking, scheduled evaluations | **Not implemented or materially incomplete**: no embeddings layer or reliable price/cost accounting; no scheduled re-evaluation. | P2; high effort; depends on provider abstraction and persisted run history. |

## 7. Execution guide

### Docker development (recommended)

Prerequisites: Docker Desktop running with Compose v2, Git, and a PowerShell
terminal. The app has already been started successfully in this environment.

1. From the repository root, create `.env` only if it does not already exist:

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   ```

   Keep `.env` private. Set a non-placeholder `SECRET_KEY` for local use, and
   configure a valid Fernet `ENCRYPTION_KEY` before using any non-development
   environment. Keep `DATABASE_URL` pointed at the Compose PostgreSQL service
   (`postgres:5432`) when running the API in Docker. Compose sets the internal
   Redis URL to `redis:6379`; do not replace it with `localhost` in the
   container configuration.

2. Start/build the services:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

3. Verify API, UI, and migration:

   ```powershell
   Invoke-RestMethod http://localhost:8000/healthz
   Invoke-RestMethod http://localhost:8000/readyz
   (Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
   (Invoke-WebRequest -UseBasicParsing http://localhost:5173).StatusCode
   docker compose exec -T api alembic current
   ```

   The API container runs `alembic upgrade head` before Uvicorn. Current
   verified head: `0010_eval_run_judge_snapshot`.

4. Open `http://localhost:5173`, create an account/workspace, and choose a
   workflow:

   - **No provider required:** create a project; open **Project Connector**;
     use **UPLOAD_OUTPUTS** and select the root `outputs_good.csv`; map its
     `input` and `output` columns; send a matching sample input; save.
   - In **Dataset Studio**, upload
     `greenlit_demo\golden_dataset.csv` and map `input`,
     `reference_answer`, and (optionally) `reference_context`; review/approve
     the item and lock/create a version.
   - Open **Evaluation Runs**, select the connected app version and dataset,
     start a run, and monitor it. Open **Results/Reports** for scores/verdict
     and export formats.
   - **Prompt App/RAG/Agent:** first create and successfully test a saved
     provider in **LLM Providers**; then select that provider in the project
     connector. Provider API keys belong in the UI, not in source files or
     this report.

5. For local Ollama, run Ollama on the host and ensure it accepts connections
   from Docker Desktop. Use `http://host.docker.internal:11434` as its base URL
   in the provider UI. Add `host.docker.internal` to `ALLOWED_PRIVATE_HOSTS`
   in `.env`, then recreate the API and worker so they receive the setting:

   ```powershell
   docker compose up -d --force-recreate api worker
   ```

   Provider private-host access and HTTP connector private-target approval
   are separate controls. Do not broadly allow private networks.

### Local frontend/backend commands

Python 3.11 is the configured minimum in `pyproject.toml` and the backend
Dockerfile. The following installs the locked frontend packages and the
backend development/test dependencies:

```powershell
py -3.11 -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
npm ci --prefix frontend
```

Run backend checks from the backend directory. Set an isolated in-memory DB
explicitly; otherwise backend settings can use a local SQLite fallback or
`.env` depending on working directory:

```powershell
Push-Location backend
$env:DATABASE_URL = 'sqlite+aiosqlite:///:memory:'
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q tests
.\.venv\Scripts\python.exe -m mypy --strict app alembic tests
.\.venv\Scripts\python.exe -m ruff format --check app alembic tests
Pop-Location
```

The last two commands currently fail for the reasons in Section 3. Do not
format or alter files as part of an ordinary test run.

Run frontend validation from the repository root:

```powershell
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run format:check
npm --prefix frontend test
npm --prefix frontend run build
```

### Troubleshooting and shutdown

- **API 502:** check whether the failing route is reporting an upstream
  provider/target error. Retest the saved provider, base URL, model name,
  provider permissions, and key. Do not paste API keys or full sensitive
  upstream responses into issues.
- **Target 404:** confirm the target app's actual route and HTTP method. The
  connector sends `GET` with an input query parameter or `POST` with the
  configured JSON body template; it does not invent the target route.
- **Private/localhost URL blocked:** use only an approved target. For a
  connector, an owner/admin must explicitly enable its private-target option.
  For an LLM provider, allow-list the exact trusted hostname in
  `ALLOWED_PRIVATE_HOSTS`.
- **Ollama unreachable from container:** confirm it is running on the host,
  listens on the expected port, and is accessible via
  `host.docker.internal`; avoid using container `localhost` for a host service.
- **API not ready:** inspect `docker compose ps`, then review API/Postgres
  logs locally. Migrations are run by the API startup command. `/readyz`
  currently checks PostgreSQL only.
- **Restart/stop:** `docker compose restart` restarts services without
  removing data; `docker compose down` stops services and retains named
  volumes. Do not use `docker compose down -v` unless intentionally deleting
  the database.

## 8. Recommended development roadmap

| Phase/task | Priority | Expected outcome | Likely files/modules | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- | --- |
| **1. Harden runtime defaults and network exposure** | P0 | No production startup with placeholder signing/encryption keys; local data ports are private; outbound URL checks fail closed. | `backend/app/config.py`, `services/secrets.py`, `services/llm_gateway.py`, `services/connectors.py`, `docker-compose.yml`, tests | None | Tests reject insecure production config, resolver failures, private IPs, and DNS changes; Compose local ports bind loopback; no credentials committed. |
| **1. Repair quality gates and dependency advisories** | P0 | Backend formatting/mypy and dependency audit are reviewable passing gates. | `backend/app/worker.py`, `backend/tests/test_phase2.py`, `backend/requirements-dev.txt`, `frontend/package.json`/lock | None | Ruff format check, strict mypy, frontend tests/build pass; npm audit findings are resolved or explicitly risk-accepted with evidence. |
| **1. Remove false-green CI behavior** | P0 | Missing or malformed checks cannot report PASS; token scope/workspace authorization is enforced. | `backend/app/routers/phase9.py`, `services/ci.py`, `models.py`, `tests/test_phase9.py` | Security/config fixes | Empty checks return 4xx/BLOCK; unknown status is rejected; unauthorized workspace/scope is denied; true regression invokes the evaluation/baseline calculation. |
| **2. Prove provider and connector integration** | P1 | Repeatable local integration covers OpenAI-compatible inference, error mapping, and HTTP target execution. | `services/llm_gateway.py`, `services/connectors.py`, `phase2_schemas.py`, tests, connector UI | Network guard fixes | Mock-server tests cover valid completion, timeout, 401/403/404/429/5xx, non-JSON and JSON path errors; local Ollama smoke path documented and tested without credential leakage. |
| **2. Make worker recovery durable** | P1 | Evaluation tasks resume safely after Redis/API/worker restart and rate/quota state is shared. | `docker-compose.yml`, `worker.py`, `run_engine.py`, `rate_limit.py`, phase3 tests | Integration test harness | Restart test proves persisted run items reach terminal state without duplicate completion or silent loss; readiness reports required dependencies. |
| **3. Complete safety and human-review workflows** | P1 | Red-team findings, policy results, reviewer decisions, overrides, and calibration are persisted and auditable. | `phase7_schemas.py`, `phase8_schemas.py`, `services/safety.py`, `human_review.py`, new models/migrations/routers/UI | Durable runs; policy definitions | Authenticated UI/API end-to-end tests cover creation, review, audit, thresholds, and export; hard gates affect verdict only under explicit criteria. |
| **3. Expand browser/integration test coverage** | P1 | The primary create-project-to-report workflow is verified in a real browser against Compose. | frontend tests, `docs/manual-tests/`, backend integration tests | Stable local mock provider and worker | CI or documented repeatable run covers signup, provider, connector, dataset approval, run SSE, verdict, and report download. |
| **4. Add severity and richer evaluation methods** | P2 | Persisted findings have severity/confidence; grounding, policy, and hallucination evaluations are measurable and versioned. | metrics, verdicts, safety services/schemas/UI | Safety persistence and validated judge workflow | Benchmark dataset and human-reviewed acceptance set demonstrate calibrated results; reports include source/version and thresholds. |
| **4. Add reusable suites/history/dashboard** | P2 | Named suites combine immutable datasets, criteria, metrics, and judge profiles; trend views support repeated runs. | models/migrations, phase3/5/6 routers/services, frontend results | Reliable worker and persisted run history | Re-running a suite preserves the exact config snapshot; dashboard metrics reconcile with exported reports. |
| **5. Refresh docs and deployment profile** | P2 | Handover/setup docs match current paths, status, and test evidence; production topology is distinct from dev Compose. | `README.md`, `docs/PROGRESS.md`, `docs/AUDIT.md`, Compose/deployment docs | Phases 1-4 decisions | New developer can start, test a sample, diagnose known issues, and identify unverified features without relying on stale counts. |

## 9. Developer handover checklist

- [ ] Start Docker Desktop and verify all five Compose services with
  `docker compose ps`.
- [ ] Keep `.env` private; replace development key values before any shared
  environment. Do not commit `.env` or database files.
- [ ] Remember that API and worker use Docker service names (`postgres`,
  `redis`); browser-side `VITE_API_URL` is `http://localhost:8000` by default.
- [ ] Migrations are applied by the API startup command; current inspected
  revision is `0010_eval_run_judge_snapshot`.
- [ ] Run backend tests with `DATABASE_URL=sqlite+aiosqlite:///:memory:` to
  avoid stale/local SQLite state.
- [ ] Review the pre-existing connector worktree changes before branching or
  committing; they were not made by this handover task and must not be
  discarded.
- [ ] Treat provider tests using mocked transports as contract evidence, not
  proof of a vendor's live availability or credentials.
- [ ] Remember the supported connectors are HTTP endpoint, Prompt App, built-in
  RAG, built-in Agent, and uploaded outputs. The other registry entries remain
  disabled until a verified sandbox/browser/MCP implementation exists.
- [ ] Keep the distinction between helper calculations and actual integrated
  persisted workflows clear for Phase 7 safety and Phase 8 human review.
- [ ] Fix the CI false-PASS path, production secrets/network defaults, and SSRF
  validation before production or shared-network deployment.
- [ ] Re-run backend lint, format, strict mypy, pytest, frontend lint,
  typecheck, format, Vitest, build, and dependency audit after relevant
  changes.
- [ ] Update stale phase/test counts in README/progress/audit documentation
  when their respective evidence is revalidated.

## 10. Final assessment

### What works now

- The local five-service Compose stack starts, is healthy, serves the frontend
  and API, and has applied migrations through revision 0010.
- Core authentication/RBAC, provider and connector contracts, dataset/run
  persistence, metrics, verdicts, reports, comparisons, chat, and helper
  functions have substantial automated backend coverage.
- Uploaded outputs can be tested without a provider; frontend connector
  payload construction and the simplified connector chooser have passing
  tests.
- Host Ollama network reachability from the API container is confirmed.

### What prevents production readiness

- A CI request can produce a PASS without real checks or a GreenLit regression
  comparison.
- Production startup can use development secrets, Compose exposes data
  services broadly with static credentials, and outbound URL validation has
  gaps.
- npm audit has critical/high findings; strict mypy and Ruff format checks
  currently fail.
- Real provider inference, the full authenticated browser workflow, and
  worker/Redis recovery have not been proven here.
- Safety and human review are not complete persisted product workflows, and
  several connector entry points are correctly disabled.

### Three most urgent fixes

1. Fail closed on production secrets and close SSRF/DNS validation gaps; harden
   Compose network bindings and credentials.
2. Remove the CI false-PASS behavior and enforce token scopes/workspace
   authorization; connect CI checks to actual run/baseline results.
3. Restore all quality gates and address frontend dependency advisories, then
   add a repeatable provider/worker integration test.

### Five most valuable additions

1. Persisted red-team/policy assessments with explicit severity and launch
   gates.
2. A durable, restart-tested evaluation queue and progress/history workflow.
3. Reusable versioned evaluation suites spanning datasets, metrics, judges,
   and criteria.
4. Better calibrated grounding/hallucination and response-quality evaluation
   with human-reviewed evidence.
5. Trend dashboards and exportable reports built on the existing report and
   comparison foundation.

### Completion estimate and readiness

Estimate: **about 65% of the intended product scope**, assuming
`docs/PROJECT_SPEC.md` is the target and weighting security, reliability, and
integrated workflows—not lines of code or the number of phase folders. Core
phases are substantial, but safety/review integration, sandboxed entry points,
live integration evidence, and production hardening are material gaps.

**Ready for handover:** yes, with the known issues and existing uncommitted
connector changes explicitly called out. **Ready for controlled local
testing:** yes, especially with uploaded outputs or a deliberately configured
local provider. **Ready for production:** no.
