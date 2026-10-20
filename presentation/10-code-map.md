# Code map

## How to read this map

This map covers the tracked repository files from `git ls-files`, excluding only `frontend/package-lock.json` because it is a lockfile. No tracked binary/image files were found in the inventory. Every file is listed at least once below; paths are repository-relative. The summaries are based on source/module contents, declarations, route definitions, and project documentation, not filenames alone. `backend/app/services/connectors.py`, `backend/app/services/run_engine.py`, `backend/app/services/metrics.py`, `backend/app/services/datasets.py`, `backend/app/models.py`, `backend/app/routers/phase3.py`, and the frontend page files are large; the source reading used their module headers, top-level classes/functions, and relevant route/function sections rather than reproducing entire files.

## Repository tree (two to three levels)

```text
.
├── backend/                         Python API, persistence, workers, and tests
│   ├── app/                          Application modules, routers, schemas, services
│   │   ├── routers/                  HTTP endpoints grouped by auth and phase
│   │   └── services/                 Domain and integration services
│   ├── alembic/                      Database migration environment and revisions
│   │   └── versions/                 Versioned schema changes
│   ├── tests/                        API and service acceptance tests
│   └── typings/                      Local third-party type stub
├── frontend/                         React + TypeScript web application
│   └── src/                          Routes, workspace flows, API client, styles
├── scripts/                          Seed-summary, report-export, and research scripts
├── docs/                             Specification, progress record, and audit
├── presentation/                     This evidence-based presentation pack
└── docker-compose.yml                Local API, web, worker, Redis, PostgreSQL
```

The `presentation/` files are deliverables for this request and are not part of the `git ls-files` inventory used to count the pre-existing tracked project. No tracked `.github/` directory exists.

## Backend API

| File path | Key classes/functions/endpoints | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/routers/auth.py` | `signup`, `login`, `refresh`, `logout`, password-reset request/confirm, `/auth/me` | Registration, access/refresh tokens, one-time reset, audit records | 1 | `backend/tests/test_auth.py` |
| `backend/app/routers/workspaces.py` | Workspace member/role endpoints | Workspace membership and role administration | 1 | `backend/tests/test_auth.py` |
| `backend/app/routers/core.py` | workspace listing, audit listing, health/readiness, viewer/engineer summaries | Common workspace, audit, health/readiness endpoints | 1 | `backend/tests/test_auth.py` |
| `backend/app/routers/phase2.py` | `/entry-point-types`; providers; projects; app versions; connector test/save; judge profiles | Provider/project/connector API and gate checks | 2 | `backend/tests/test_phase2.py`, `test_phase10.py` |
| `backend/app/routers/phase3.py` | dataset list/upload/generate/review, create and inspect runs, progress, pause/resume/cancel | Dataset Studio and evaluation run endpoints | 3 | `backend/tests/test_phase3.py` |
| `backend/app/routers/phase4.py` | metric catalog endpoint | Exposes metric definitions and required fields | 4 | `backend/tests/test_phase4.py` |
| `backend/app/routers/phase5.py` | verdict criteria read/write; run report | Criteria, hard gates, report/readiness response | 5 | `backend/tests/test_phase5.py` |
| `backend/app/routers/phase6.py` | baseline get/promote, run comparison, regression check | Baseline management and regression reports | 6 | `backend/tests/test_phase6.py` |
| `backend/app/routers/phase8.py` | review queue, calibration, blind compare, override, final-report rescore | Human-review/calibration service/API contracts | 8 | `backend/tests/test_phase8.py` |
| `backend/app/routers/phase9.py` | CI regression status, create/list API tokens | Token-authenticated CI status response and tokens; not a GitHub Actions workflow or a full run trigger | 9 | `backend/tests/test_phase9.py` |

There is no tracked `phase7.py` router. Safety calculations are in a service and have tests, but a safety API/UI should not be inferred from that alone. Phase 9's CI endpoint builds a response from submitted checks; do not describe it as executing a complete evaluation suite.

## Backend core

| File path | What code it contains | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/__init__.py` | Package marker | Python package initialization | 1 | Imported by test suite |
| `backend/app/config.py` | Pydantic settings | Reads application settings and environment variables | 1 | `test_auth.py`; config used by API |
| `backend/app/db.py` | Declarative `Base`, engine/session factory, `get_db` | Async SQLAlchemy database session dependency | 1 | Integration tests |
| `backend/app/deps.py` | `get_current_user`, `require_roles`, `require_workspace_access` | Bearer authentication and workspace/role checks | 1 | `test_auth.py`, phase API tests |
| `backend/app/mailer.py` | Reset-mail delivery configuration and sender | Console/dev or configured SMTP password-reset delivery | 1 | `test_auth.py` |
| `backend/app/main.py` | FastAPI app, router registration, CORS, `/healthz`, `/readyz` | API entry point and health/readiness endpoints | 1 | Full API test suite |
| `backend/app/models.py` | SQLAlchemy ORM models | Persistent application entities (table list below) | 1–9 | All phase integration tests |
| `backend/app/schemas.py` | Auth/workspace/audit Pydantic I/O types | Shared API schema validation and response models | 1 | `test_auth.py` |
| `backend/app/phase2_schemas.py` | Provider/project/judge and 13 connector settings models; model registry | Validated provider/connector payloads and JSON Schema | 2 | `test_phase2.py`, `test_phase10.py` |
| `backend/app/phase3_schemas.py` | Dataset and run request/response models | Typed dataset/run API contracts | 3 | `test_phase3.py` |
| `backend/app/phase4_schemas.py` | Metric catalog and score models | Typed metric output | 4 | `test_phase4.py` |
| `backend/app/phase5_schemas.py` | Criteria, verdict, readiness, report models | Typed decision and report shape | 5 | `test_phase5.py` |
| `backend/app/phase6_schemas.py` | Baseline/comparison/regression models | Typed paired comparison output | 6 | `test_phase6.py` |
| `backend/app/phase7_schemas.py` | Attack pack and safety summary schemas | Typed safety calculation output | 7 | `test_phase7.py` |
| `backend/app/phase8_schemas.py` | Review queue, calibration, blind compare, override, final report schemas | Typed review/calibration contracts | 8 | `test_phase8.py` |
| `backend/app/security.py` | Password hash/verify, token hash, JWT creation and decode | Password and JWT helpers | 1, 9 | `test_auth.py`, `test_phase9.py` |
| `backend/app/tracing.py` | `TraceRecorder`, `trace_context`, `emit_trace_step`, `current_trace` | Async-context trace recording helpers | 2 | `backend/tests/test_tracing.py` |
| `backend/app/worker.py` | Celery setup/configuration, `execute_eval_run`, enqueue helper | Runs async evaluation jobs outside API requests | 3 | `test_phase3.py` |

### Database models and migration history

The actual ORM declares the following table models in `backend/app/models.py`.

| Table | What it stores |
|---|---|
| `users` | Email, password hash, active state, and timestamps |
| `workspaces` | Workspace name/slug and owner |
| `workspace_memberships` | User-to-workspace membership and workspace role |
| `refresh_tokens` | Hashed refresh token, expiry/revocation, user/workspace association |
| `password_reset_tokens` | Hashed, expiring, one-time reset token state |
| `api_tokens` | Hashed API token, name, workspace, scopes, expiry, and activity |
| `audit_logs` | Actor, workspace, action, details, timestamp |
| `provider_configs` | Provider type/URL, encrypted key, quotas, token limits, fallback IDs |
| `projects` | Workspace-owned project metadata |
| `connector_profiles` | Entry-point type, settings, encrypted credentials, hash/access level |
| `app_versions` | Connector/config snapshot and version lineage metadata |
| `judge_profiles` | Project role, provider/model, rubric prompt and version |
| `project_verdict_criteria` | Project's configured criteria |
| `connector_tests` | Connector test identity/hash/expiry |
| `datasets` | Project dataset and task type |
| `dataset_versions` | Dataset version, content hash, split strategy, locked timestamp |
| `dataset_items` | Inputs, references, category, provenance, review status, split and flags |
| `eval_runs` | Run configuration snapshots, lifecycle state, item counts and task metadata |
| `project_baselines` | Approved baseline run, approver, reason, timestamp |
| `eval_run_items` | Per-item execution state, output/trace/scores/errors |
| `judge_metric_cache` | Cached judge scores keyed to evaluation identity |

The migration files are incremental schema changes. Their exact filenames are listed in Infrastructure below. There are no ORM tables for persisted HumanReview, ReviewQueueItem, AttackPack, or DiscoverySession in the tracked model file; do not imply those entities are already durable database workflows.

## LLM provider layer

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/services/llm_gateway.py` | `LLMGateway`, `ChatResult`, `ProviderRequestError`, connection and completion methods | Calls OpenAI-compatible provider APIs, checks configured limits, carries model/provider usage | 2 | `test_phase2.py` |
| `backend/app/services/rate_limit.py` | `ProviderRateLimiter`, `DailyQuotaPaused` | In-process RPM queue and RPD pause tracking | 2 | `test_provider_rate_limiter_queues_rpm_and_pauses_at_rpd` |
| `backend/app/services/secrets.py` | `_fernet`, `encrypt_secret`, `decrypt_secret` | Encrypts/decrypts stored provider and connector secrets | 2 | `test_phase2.py` secret tests |
| `backend/app/routers/phase2.py` | provider creation/test, workspace provider lists, fallback IDs | Configures and tests providers and checks workspace ownership | 2 | `test_phase2.py` |

The repo code supports GitHub Models defaults, Ollama defaults, and custom OpenAI-compatible endpoints. The latest project tests do not establish a live provider call; provider tests are mocked. Rate-limit state is process-local.

## Connectors and entry points

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/services/__init__.py` | Service package marker | Defines the backend services package | 1 | Imported by service modules |
| `backend/app/services/connectors.py` | `entry_point_types`, `validate_connector_settings`, `execute_test_call`, `redact_secrets`, `_trace_response`, per-type test-call helpers | Registry, validation, supported test calls, SSRF target checks, trace normalization | 2, 9, 10 | `test_phase2.py`, `test_phase10.py` |
| `backend/app/phase2_schemas.py` | `CONNECTOR_SETTINGS_MODELS`; HTTP, Python, Prompt, RAG, Agent, upload, Docker, Git, CLI, Proxy, Website URL, MCP settings | Per-type validated settings and generated JSON Schema | 2, 10 | `test_phase2.py`, `test_phase10.py` |
| `backend/app/tracing.py` | Context-local trace recorder | Captures nested/async trace steps for white-box use | 2 | `test_tracing.py` |
| `frontend/src/WorkspaceProjects.tsx` | Registry type, fallback choices, `disabledReason`, `SettingsEditor`, project/provider/connector UI | Workspace project and connector configuration surface | 2 | No separate frontend test file tracked |

The registry lists all 13 types, but current metadata gates Python Function, Python SDK Traced, Docker, Git, CLI, Proxy, Website URL, and MCP. Some helper implementations are present, yet the API rejects gated types. Website URL and MCP calls are not proven against a real browser/server.

## Dataset Studio and run engine

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/services/datasets.py` | `DatasetItemDraft`, upload parsers, mapping/validation, template drafts, `dataset_content_hash` | CSV/JSON/JSONL/XLSX parsing, validation, dedupe, generation record shaping, hashing | 3 | `test_phase3.py` |
| `backend/app/routers/phase3.py` | dataset upload/generation/review/version endpoints; run creation, stream/progress and controls | API for Dataset Studio and asynchronous runs | 3 | `test_phase3.py` |
| `backend/app/phase3_schemas.py` | Dataset mapping, generation, review, versions and run I/O | Validates Phase 3 request/response shapes | 3 | `test_phase3.py` |
| `backend/app/services/run_engine.py` | `execute_eval_run_async`, `_execute_one_item`, status/count helpers | Per-item run processing, pause/cancel and failure containment | 3 | `test_phase3.py` |
| `backend/app/worker.py` | Celery task wrapper, `execute_eval_run`, enqueue path | Worker entry for run jobs | 3 | `test_phase3.py` |
| `frontend/src/DatasetStudio.tsx` | Dataset Studio component, API path helper and record checks | Upload/generate/review/run user interface | 3–5 | No separate frontend test file tracked |

## Metric library

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/services/metrics.py` | `MetricDefinition`, `MetricCase`, `JudgeOutput`, `METRIC_REGISTRY`, `evaluate_rule_metrics`, `score_run_item`, `score_with_judge`, cache helpers | Rule metrics, judge scoring, missing-instrumentation status, aggregation and cache | 4 | `test_phase4.py` |
| `backend/app/phase4_schemas.py` | `MetricCatalogOut`, `MetricScoreOut` | Typed score and catalog output | 4 | `test_phase4.py` |
| `backend/app/models.py` | `JudgeProfile`, `JudgeMetricCache` | Persisted judge configuration and cache | 4 | `test_phase4.py` |
| `backend/app/routers/phase4.py` | Metric catalog route | Project-scoped metric catalog API | 4 | `test_phase4.py` |

Metrics in code are not all advanced evaluations. For example, context recall uses lexical term overlap; exact match normalizes text; token usage checks for instrumentation. The docs explicitly describe these as baselines.

## Decision engine and statistics

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/services/verdicts.py` | `evaluate_verdict`, `readiness_issues_for_trace`, `criteria_snapshot` | Applies hard gates and thresholds; generates readiness issues | 5 | `test_phase5.py` |
| `backend/app/phase5_schemas.py` | Default criteria, result, verdict and readiness models | Typed decision contract | 5 | `test_phase5.py` |
| `backend/app/routers/phase5.py` | Criteria read/write and run report routes | Stores criteria and returns item/report/verdict data | 5 | `test_phase5.py` |
| `backend/app/services/statistics.py` | Paired bootstrap, permutation, McNemar, Holm adjustment | Statistical support for comparisons | 6 | `test_phase6.py` |
| `backend/app/services/comparison.py` | `compare_runs`, `regression_report` | Item/metric comparison and regression status | 6 | `test_phase6.py` |
| `backend/app/phase6_schemas.py` | Baseline, comparison, failure, report schemas | Typed regression output | 6 | `test_phase6.py` |
| `backend/app/routers/phase6.py` | Baseline, compare and regression routes | Workspace/project-scoped baseline endpoints | 6 | `test_phase6.py` |

## Safety module

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/services/safety.py` | `attack_pack`, canary and system-prompt leak detectors, `summarize_safety`, guardrail uplift | Builds attack examples and computes safety summaries from supplied samples | 7 | `test_phase7.py` |
| `backend/app/phase7_schemas.py` | Attack-pack, safety metric and summary output types | Typed safety results | 7 | `test_phase7.py` |

This is service logic and contract tests, not a complete live red-team console. No Phase 7 router or safety page is present in the tracked frontend.

## Human review and calibration

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/services/human_review.py` | `queue_review_items`, `blind_ab_compare`, `validate_override`, `calibration_summary`, `final_report_rescore` | Review decision and calibration calculations | 8 | `test_phase8.py` |
| `backend/app/phase8_schemas.py` | Review/calibration/comparison/override/report outputs | Contract types | 8 | `test_phase8.py` |
| `backend/app/routers/phase8.py` | Review queue, calibration, blind comparison, override and rescore routes | Exposes service/API contracts | 8 | `test_phase8.py` |

The repository has no ORM tables for persistent review records in `models.py` and the frontend has no separate review/calibration page. Phrase this as validated service/API behavior, as `docs/PROGRESS.md` does.

## CI status, reports, and research scripts

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `backend/app/services/ci.py` | API token generation/validation and CI status normalization | Produces PASS/WARN/BLOCK responses from check data | 9 | `test_phase9.py` |
| `backend/app/routers/phase9.py` | CI regression-check and API-token endpoints | Authenticates and returns a CI status; does not itself run GitHub Actions | 9 | `test_phase9.py` |
| `scripts/__init__.py` | Script package marker | Allows script imports | 9 | Indirect |
| `scripts/seed_demo.py` | `build_demo_states`, CLI `main` | Writes static GOOD/BROKEN/REGRESSING scenario JSON | 9 | `test_phase9_seed.py` |
| `scripts/export_reports.py` | Markdown/CSV/PDF writers and CLI | Exports the static scenario mapping, not stored evaluation runs | 9 | `test_phase9_seed.py` |
| `scripts/research_analysis.py` | Cohen's kappa and bootstrap CI helpers; CLI | Calculates example research summary from small built-in arrays | 9 | `test_phase9_seed.py` |

## Frontend

| File path | Key code | Use in GreenLit | Phase | Related tests |
|---|---|---|---|---|
| `frontend/src/main.tsx` | React root and `BrowserRouter` | Starts the SPA and routes | 1 | Build/typecheck |
| `frontend/src/App.tsx` | Landing, theme toggle, auth/reset pages, workspace route | Top-level navigation and session UI | 1–3 | Build/typecheck; no frontend unit test files tracked |
| `frontend/src/WorkspaceProjects.tsx` | Workspace project/provider/connector controls and disabled reasons | Project and entry-point configuration UI | 2 | Build/lint/typecheck |
| `frontend/src/DatasetStudio.tsx` | Dataset upload/generation/review and run display | Dataset workflow UI | 3–5 | Build/lint/typecheck |
| `frontend/src/api.ts` | `apiRequest` and frontend API types | HTTP client and shared frontend data types | 1 | Build/typecheck |
| `frontend/src/styles.css` | Theme variables, layout, forms, component styles | Design system and page presentation | 1 | Prettier/build |
| `frontend/src/vite-env.d.ts` | Vite client type declarations | TypeScript environment types | 1 | Typecheck |

The tracked frontend has four route paths in `App.tsx`: `/`, `/login`, `/signup`, `/reset-password`, plus `/workspace` and a fallback redirect. It should not be presented as 15 separately implemented pages from the spec.

## Infrastructure and configuration

| File path | What it configures | Use in GreenLit |
|---|---|---|
| `.env.example` | Names of local API/database/Redis/security/mail settings | Documents environment variable names only; this map does not include any values |
| `.gitignore` | Ignored local artifacts | Excludes local settings, Python caches/virtualenv and frontend dependencies/build output |
| `.pre-commit-config.yaml` | Seven local system hooks | Ruff, Ruff format, strict mypy, backend tests, frontend ESLint, Prettier, frontend typecheck |
| `Makefile` | `up`, `down`, `migrate`, test/build, seed/export/research targets | Developer commands; Make is not available in the recorded Windows PowerShell session |
| `docker-compose.yml` | PostgreSQL, Redis, API, worker, web services | Local service wiring and health checks; no `beat` service |
| `backend/Dockerfile` | `python:3.11-slim` API/worker image | Installs backend requirements and copies app/migrations |
| `backend/.dockerignore` | Backend build exclusions | Keeps local/unneeded files out of Docker build context |
| `backend/alembic.ini` | Alembic configuration | Migration tool setup |
| `backend/alembic/env.py` | Migration environment | Applies model metadata/revisions |
| `backend/alembic/versions/0001_initial_schema.py` | Initial schema | Foundation tables |
| `backend/alembic/versions/0002_providers_projects_connectors.py` | Provider/project/connector changes | Phase 2 persistence |
| `backend/alembic/versions/0003_datasets_runs.py` | Dataset and run changes | Phase 3 persistence |
| `backend/alembic/versions/0004_metrics.py` | Metric/judge storage changes | Phase 4 persistence |
| `backend/alembic/versions/0005_verdicts.py` | Verdict-related schema changes | Phase 5 persistence |
| `backend/alembic/versions/0006_comparison_regression.py` | Baseline/comparison schema changes | Phase 6 persistence |
| `backend/pytest.ini` | pytest configuration | Backend test discovery/settings |
| `backend/requirements.txt` | Runtime and test package pins/ranges | Backend dependencies |
| `backend/requirements-dev.txt` | Ruff, mypy, types, pre-commit | Backend development tools |
| `backend/typings/celery/__init__.pyi` | Local Celery type stub | Type-checker compatibility |
| `frontend/Dockerfile` | `node:20-alpine`, npm ci, Vite dev server | Frontend container |
| `frontend/.dockerignore` | Frontend build exclusions | Keeps local/unneeded files out of Docker build context |
| `frontend/.prettierrc.json` | Prettier preferences | Consistent frontend formatting |
| `frontend/eslint.config.js` | ESLint config | Frontend lint rules |
| `frontend/index.html` | SPA HTML shell | Vite entry document |
| `frontend/package.json` | Dependencies and scripts | Frontend build, lint, typecheck, format commands |
| `frontend/tsconfig.json` | TypeScript compiler options | Frontend typechecking |
| `frontend/vite.config.ts` | Vite config | Frontend bundling/dev server |
| `pyproject.toml` | Ruff and mypy configuration | Python lint/format and strict type configuration |

`frontend/package-lock.json` is intentionally omitted from the map because the requested counting rules exclude lockfiles. It remains tracked in the repository.

## Tests

| File path | What it covers (from names and phase evidence) | Phase / evidence |
|---|---|---|
| `backend/tests/test_auth.py` | Signup, login, refresh/logout, password reset, roles, workspace isolation and audit behaviors | 1; Progress Phase 1 |
| `backend/tests/test_tracing.py` | Nested trace context and asynchronous task isolation | 2; `docs/PROGRESS.md` Phase 2 |
| `backend/tests/test_phase2.py` | Provider config/mocks, quota limits, connector registry and execution/gating, secret handling, Prompt/RAG/Agent | 2; latest run contains two failures |
| `backend/tests/test_phase3.py` | Upload, dataset versions/review, runs and run controls | 3 |
| `backend/tests/test_phase4.py` | Metric values, not-instrumented statuses, judge schema/retry/cache/injection prompt behavior | 4 |
| `backend/tests/test_phase5.py` | Hard/soft verdict criteria, readiness, run report | 5 |
| `backend/tests/test_phase6.py` | Baselines, paired statistics, comparison and regression | 6 |
| `backend/tests/test_phase7.py` | Attack pack, canary/leak detection, safety summary and uplift | 7 |
| `backend/tests/test_phase8.py` | Queue, blind A/B, override contract and calibration/rescore | 8 |
| `backend/tests/test_phase9.py` | API-token CI status flow | 9 |
| `backend/tests/test_phase9_seed.py` | Static scenario mapping, report exports, research summary | 9 |
| `backend/tests/test_phase10.py` | Mocked Website URL/MCP contract expectations and registry exposure | 10; latest run contains two failures |

No frontend or Playwright E2E test file is included in `git ls-files`. The spec requires a golden-path E2E, while Progress/Audit record that work as a gap.

## Docs

| File path | Purpose |
|---|---|
| `README.md` | Setup, product overview, phase summaries, known limitations, local checks |
| `docs/PROJECT_SPEC.md` | Target architecture, feature requirements, phases, checklists, completion protocol |
| `docs/PROGRESS.md` | Phase-by-phase recorded acceptance evidence, checks, and known gaps |
| `docs/AUDIT.md` | Independent implementation status summary and known limitations |

## Request walkthroughs

### 1) Login and token refresh

| Step | File | Function/endpoint | What happens |
|---:|---|---|---|
| 1 | `frontend/src/App.tsx` | `AuthPage`, `handleSubmit` | Sends login/signup form data to the API. |
| 2 | `frontend/src/api.ts` | `apiRequest` | Sends the HTTP request and attaches the returned access token to later calls. |
| 3 | `backend/app/routers/auth.py` | `POST /api/v1/auth/login` | Verifies the password and creates access and refresh tokens. |
| 4 | `backend/app/security.py` | `verify_password`, `create_access_token`, `create_refresh_token`, `hash_token` | Hashes/verifies password and signs tokens; token hash is stored. |
| 5 | `backend/app/models.py` | `User`, `RefreshToken`, `WorkspaceMembership`, `AuditLog` | Stores identity/session/membership/audit rows. |
| 6 | `backend/app/routers/auth.py` | `POST /api/v1/auth/refresh` | Reads the httpOnly cookie, replaces the stored token hash, sets a new cookie, returns a new access token. |

### 2) Connecting an app with the entry-point dropdown and Test call

| Step | File | Function/endpoint | What happens |
|---:|---|---|---|
| 1 | `frontend/src/WorkspaceProjects.tsx` | `WorkspaceProjects`, `SettingsEditor`, `disabledReason` | Loads/shows the registry, displays settings, and explains disabled types. |
| 2 | `frontend/src/api.ts` | `apiRequest` | Sends registry and connector requests. |
| 3 | `backend/app/routers/phase2.py` | `GET /api/v1/entry-point-types` | Returns registry labels, flags, and settings schemas. |
| 4 | `backend/app/services/connectors.py` | `entry_point_types`, `validate_connector_settings` | Supplies the registry and rejects unavailable types before execution. |
| 5 | `backend/app/routers/phase2.py` | `POST /api/v1/workspaces/{workspace_id}/connectors/test-call` | Validates input, invokes the connector service, records the test boundary, and returns result/trace metadata. |
| 6 | `backend/app/services/connectors.py` | `execute_test_call`, `_trace_response` | Executes supported connector behavior and normalizes the trace; gated connectors return a clear unavailable error. |
| 7 | `backend/app/models.py` | `ConnectorProfile`, `ConnectorTest`, `AppVersion` | Stores successful saved connector/config version information. |

### 3) Running an evaluation: dataset to verdict

| Step | File | Function/endpoint | What happens |
|---:|---|---|---|
| 1 | `frontend/src/DatasetStudio.tsx` | Dataset Studio component | Uploads/generates examples and requests dataset/run operations. |
| 2 | `backend/app/routers/phase3.py` | dataset upload/generate/review endpoints | Validates and persists dataset versions/items; approval controls eligibility. |
| 3 | `backend/app/services/datasets.py` | `parse_upload_records`, `map_upload_records`, `dataset_content_hash` | Parses supported files, validates/matches columns, detects duplicates and hashes version content. |
| 4 | `backend/app/models.py` | `Dataset`, `DatasetVersion`, `DatasetItem`, `EvalRun`, `EvalRunItem` | Stores dataset/run snapshots and per-item status. |
| 5 | `backend/app/routers/phase3.py` | run creation route | Snapshots app/dataset/criteria identifiers and enqueues the run. |
| 6 | `backend/app/worker.py` | `enqueue_eval_run`, `execute_eval_run` | Sends work to Celery. |
| 7 | `backend/app/services/run_engine.py` | `execute_eval_run_async`, `_execute_one_item` | Runs each item, stores trace/output/status, tolerates an item failure, and pauses on quota. |
| 8 | `backend/app/services/metrics.py` | `score_run_item`, `evaluate_rule_metrics`, `score_with_judge` | Calculates rule/judge scores and stores score metadata. |
| 9 | `backend/app/routers/phase5.py` | `GET .../runs/{run_id}/report` | Returns items, readiness issues, criteria snapshot, and verdict. |
| 10 | `backend/app/services/verdicts.py` | `evaluate_verdict` | Applies hard-gate and weighted threshold logic. |

## “Where do I change X?” cheat sheet

| Change | Start here |
|---|---|
| Add a deterministic metric | `backend/app/services/metrics.py` and `backend/tests/test_phase4.py` |
| Change a judge prompt or retry | `backend/app/services/metrics.py` |
| Change provider limits | `backend/app/models.py` provider fields, `backend/app/services/rate_limit.py`, provider schemas |
| Change provider connection behavior | `backend/app/services/llm_gateway.py` |
| Add an entry-point schema | `backend/app/phase2_schemas.py` |
| Add an entry-point label/status | `_ENTRY_POINT_TYPES` in `backend/app/services/connectors.py` |
| Implement a connector test call | `backend/app/services/connectors.py`; keep API/UI gating consistent |
| Change connector dropdown or disabled message | `frontend/src/WorkspaceProjects.tsx` |
| Change dataset upload parsing | `backend/app/services/datasets.py` |
| Change a generated dataset template | `backend/app/services/datasets.py` and `backend/app/routers/phase3.py` |
| Change item approval or dataset versioning | `backend/app/routers/phase3.py`, `backend/app/services/datasets.py` |
| Change run progress/pause/cancel behavior | `backend/app/services/run_engine.py`, `backend/app/worker.py`, `backend/app/routers/phase3.py` |
| Change GO/REVIEW/NO_GO rules | `backend/app/services/verdicts.py`, `backend/app/phase5_schemas.py` |
| Change baseline/regression logic | `backend/app/services/comparison.py`, `statistics.py`, `backend/app/routers/phase6.py` |
| Add/change a safety detector | `backend/app/services/safety.py`, `backend/app/phase7_schemas.py` |
| Change review/calibration calculations | `backend/app/services/human_review.py` |
| Add a database table | `backend/app/models.py` and a new Alembic revision under `backend/alembic/versions/` |
| Change authentication/password behavior | `backend/app/security.py`, `backend/app/routers/auth.py`, `backend/tests/test_auth.py` |
| Change workspace role rules | `backend/app/deps.py` and relevant router dependencies |
| Change secret encryption | `backend/app/services/secrets.py` |
| Add or change a frontend route | `frontend/src/App.tsx` |
| Change dataset UI | `frontend/src/DatasetStudio.tsx` |
| Change theme/design tokens | `frontend/src/styles.css`, `frontend/src/App.tsx` |
| Change local service wiring | `docker-compose.yml` and relevant Dockerfile |
| Change lint/type/pre-commit commands | `pyproject.toml`, frontend configs/package scripts, `.pre-commit-config.yaml` |
| Change example CI scenario labels | `scripts/seed_demo.py`; it is static output, not a live seed |
| Add a GitHub Actions workflow | No tracked `.github/` workflow currently exists; create and validate one as separate approved work |

## Stubbed, disabled, mocked, and partial areas

- **Disabled:** `PYTHON_FUNCTION`, `PYTHON_SDK_TRACED`, `DOCKER_IMAGE`, `GIT_REPO`, `CLI_COMMAND`, `PROXY_MODE`, `WEBSITE_URL`, and `MCP_SERVER` are marked unimplemented in the connector registry and rejected. See `docs/AUDIT.md` Known limitations and `backend/app/services/connectors.py`.
- **Mocked in tests:** provider connections/RAG/judge flows use mocked endpoints or gateway responses, as noted in `docs/PROGRESS.md` Phases 2 and 4.
- **Partial:** Phase 10 Website URL/MCP runtime is partial in `docs/AUDIT.md`; its successful-call tests disagree with current gating and fail in the latest run.
- **Partial:** Phase 9 report and research scripts operate on small static examples, not stored production evaluation records (`scripts/seed_demo.py`, `export_reports.py`, `research_analysis.py`).
- **Not present:** `.github/` workflows, frontend component test files, Playwright E2E tests, `phase7` router, and a persistent review queue model are not in the tracked file inventory.

## Inventory counts

- Tracked files returned by `git ls-files`: **98**.
- Files mapped above: **97**.
- Skipped by the requested exclusions: **1** lockfile, `frontend/package-lock.json`.
- Tracked binary/image files skipped: **0** found.
- Git-ignored and untracked files are not part of the tracked-file map.
