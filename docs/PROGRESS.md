# GreenLit phase progress

Updated: 2026-10-11

## Phase 1 - Foundation: DONE

### Acceptance checklist

- **PASS** - `docker compose up --build -d` starts the API, web, worker, Redis,
  and PostgreSQL. Evidence: `docker compose ps` showed all five containers
  healthy after the final rebuild.
- **PASS** - Health, readiness, and OpenAPI docs work. Evidence:
  `GET /healthz` returned `{"status":"ok"}`, `GET /readyz` returned
  `{"status":"ready"}`, and `/docs` returned HTTP 200.
- **PASS** - Signup, login, refresh rotation, logout, and password reset work.
  Evidence: backend tests `test_signup_creates_workspace_and_access_token`,
  `test_login_refresh_and_logout_flow`, and
  `test_password_reset_uses_one_time_token_and_revokes_sessions`.
- **PASS** - A Viewer cannot use write-only Engineer/Admin endpoints. Evidence:
  `test_viewer_and_cross_workspace_access_are_forbidden`.
- **PASS** - Cross-workspace access is denied. Evidence:
  `test_viewer_and_cross_workspace_access_are_forbidden`.
- **PASS** - Signup, login, and workspace actions are audit logged. Evidence:
  `test_signup_creates_workspace_and_access_token` checks signup and workspace
  audit records; `test_login_refresh_and_logout_flow` checks the login event.
- **PASS (manual smoke check)** - Landing and auth pages render in dark and
  light themes and keyboard navigation reaches the interactive controls.
  Evidence: browser screenshots of landing in both themes and auth screens in
  both themes; Tab navigation reached the theme toggle, navigation links, form
  fields, submit button, and password-reset link on `http://localhost:5173`.
  This is not a full WCAG accessibility audit.
- **PASS** - Lint, type-check, and tests pass. Evidence: backend and frontend
  summaries below.

### Validation

- `backend\.venv\Scripts\python.exe -m ruff check backend` - passed.
- `backend\.venv\Scripts\python.exe -m ruff format --check backend` - passed.
- `backend\.venv\Scripts\python.exe -m mypy --strict backend\app backend\alembic backend\tests`
  - passed; no issues in 26 source files.
- `cd backend; .venv\Scripts\python.exe -m pytest -q tests` - 14 passed,
  2 dependency deprecation warnings.
- `npm run lint --prefix frontend` - passed.
- `npm run typecheck --prefix frontend` - passed.
- `npm run format:check --prefix frontend` - passed.
- `npm run build --prefix frontend` - passed.
- `pre-commit run --all-files` - all configured hooks passed after correcting
  the backend test hook to run from the backend project directory.
- Compose and HTTP smoke checks passed as listed above; Alembic current revision:
  `0002_phase2 (head)`.

### Assumptions and limitations

- Theme and keyboard checks cover visible page rendering and sequential
  keyboard focus only; they do not certify accessibility conformance.
- Phase 2 features had already been started under earlier authorization and
  remain documented as in progress. No additional Phase 2 implementation is
  undertaken under this Phase 1 closeout; further work waits for explicit
  approval.
- Local generated SQLite databases, test output, environment secrets, caches,
  dependency directories, and build output are excluded from the commit.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
(Invoke-WebRequest -UseBasicParsing http://localhost:5173).StatusCode
```

Open `http://localhost:5173`, then check the theme toggle and keyboard Tab order
on landing, login, and signup pages.

## Phase 2 - Providers, projects, entry points: DONE WITH DOCUMENTED GAPS

### Acceptance checklist

- **PASS** - GitHub Models and Ollama connection behavior is covered using
  mocked endpoints by `test_provider_connection_works_for_github_and_ollama_without_exposing_secrets`.
- **PASS** - RPM queueing and RPD pause behavior is covered by
  `test_provider_rate_limiter_queues_rpm_and_pauses_at_rpd`.
- **PASS** - The API exposes all 13 entry-point types and disables unsupported
  Python execution and later-phase types; evidence:
  `test_registry_lists_all_thirteen_types_and_validates_type_settings`.
- **PASS (partial browser coverage)** - The RAG form renders dynamic fields,
  JSON documents are formatted, and invalid RAG settings return HTTP 422.
  Manual browser verification did not cover every entry-point form.
- **PASS** - Prompt App and RAG calls return parsed output, trace, usage, and
  detected/missing trace fields in
  `test_prompt_and_rag_test_calls_gate_saves_and_create_app_versions`.
- **PASS** - Save is denied until the exact settings pass Test call, and changed
  settings are rejected; verified in the same integration test. Browser
  verified Save disabled before a successful test.
- **PASS** - Provider and connector secrets are encrypted and redacted from API
  output/logging in `test_provider_connection_works_for_github_and_ollama_without_exposing_secrets`
  and `test_http_test_call_redacts_and_encrypts_secret_headers`.
- **PASS (mocked provider)** - Built-in RAG retrieves document context and
  answers a sample question in
  `test_prompt_and_rag_test_calls_gate_saves_and_create_app_versions`.
- **PASS** - Changing entry-point configuration increments AppVersion in that
  same integration test.
- **PASS** - Built-in Agent tool calls enforce JSON schema and reject invalid
  arguments in `test_builtin_agent_executes_schema_validated_mock_tool_calls`
  and `test_builtin_agent_rejects_tool_arguments_outside_schema`.
- **PASS** - Trace-context nesting and asynchronous task isolation pass in
  `test_trace_context_captures_steps_and_restores_parent_context` and
  `test_trace_context_isolated_between_async_tasks`.
- **KNOWN GAP** - Python Function and Python SDK Traced are unavailable until a
  resource-limited isolated execution runner is provided. User code is not run
  unsandboxed.
- **KNOWN GAP** - Full browser coverage of every dynamic form and end-to-end
  execution/instrumentation for Python SDK Traced remains deferred with the
  isolated-runner work.
- **UPDATED 2026-10-10** - Connector provider selection is sent as a top-level
  `provider_id`; only entry points that require a provider receive it inside
  their validated settings. UPLOAD_OUTPUTS ignores the optional provider rather
  than persisting it in settings. Settings validation errors are returned as
  readable messages while strict extra-field rejection remains enabled.
- **UPDATED 2026-10-10** - The entry-point chooser displays all 13 types with
  descriptions, selected/unavailable states, keyboard navigation, and large
  responsive click targets. Connector dropdowns use larger controls and the
  optional provider choice is labeled `None (not required)`.
- **UPDATED 2026-10-10** - Added the root-level `outputs_good.csv` sample for
  the documented UPLOAD_OUTPUTS retest flow.

### Validation

- **UPDATED 2026-10-10** - `tests/test_phase2.py` in a fresh temporary SQLite
  database: 17 passed; one Ollama-dependent test was deselected because no live
  Ollama service was available. The temporary database was removed afterwards.
- **PASS 2026-10-10** - Frontend tests (8), strict TypeScript check, ESLint,
  Prettier check, and Vite production build.
- **PASS 2026-10-10** - `docker compose up --build -d api web worker`; API and
  web containers healthy, `/healthz` and `/readyz` successful, web returned
  HTTP 200.
- `docker compose ps` - API, web, worker, Redis, and PostgreSQL healthy.
- `GET /healthz` - `{"status":"ok"}`; `GET /readyz` - `{"status":"ready"}`;
  `/docs` and `http://localhost:5173` returned HTTP 200.
- `docker compose exec -T api alembic current` - `0002_phase2 (head)`.
- Backend: `cd backend; .venv\Scripts\python.exe -m pytest -q tests` - 19
  passed, 2 dependency deprecation warnings.
- Ruff check, Ruff format check, strict mypy, and all configured pre-commit
  hooks passed. Frontend ESLint, Prettier, typecheck, and production build passed.
- Browser checked the RAG dynamic form, formatted JSON document input, required
  provider selection, Test call enabled state, and Save disabled before testing.
- No real provider credentials were used; provider and RAG responses are mocked.

### Assumptions and limitations

- Provider rate limits are process-local and do not persist or coordinate across
  multiple API processes.
- RAG currently uses basic lexical retrieval; this is not a retrieval-quality
  benchmark.
- Dark/light and keyboard smoke checks are recorded under Phase 1; they do not
  constitute a full accessibility audit.
- Generated local databases, test output, environment secrets, caches,
  dependencies, and build output remain excluded from commits.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
(Invoke-WebRequest -UseBasicParsing http://localhost:5173).StatusCode
```

## Phase 3 - Datasets and run engine: DONE WITH DOCUMENTED GAPS

### Acceptance checklist

- **PASS** - CSV/JSON/JSONL upload maps columns, validates invalid rows, removes
  duplicates, and reports validation results. Evidence:
  `test_upload_maps_rows_reports_errors_and_versions_are_hash_stable`; browser
  import displayed one valid row and the mapped reference answer.
- **PASS** - RAG, chatbot, agent, and extraction generation templates produce
  pending synthetic items. Evidence:
  `test_generation_templates_use_provider_and_store_pending_synthetic_items`
  using a mocked provider response for all four templates.
- **PASS** - Only approved items may enter a run and provenance is recorded.
  Evidence: `test_twenty_item_run_resumes_without_duplicate_records_and_controls_work`
  rejects a run before approval and starts with only 20 approved out of 21
  uploaded items; generated items are asserted as `synthetic`.
- **PASS** - Dataset version hashes are stable and a run locks its version.
  Evidence: `test_upload_maps_rows_reports_errors_and_versions_are_hash_stable`
  checks matching hashes across equivalent CSV/JSON imports; the run test
  confirms review is rejected after the version is locked.
- **PASS** - A 20-item run completes with live UI progress. Evidence: browser
  test on the Compose stack imported and approved 20 JSONL items, started a
  Celery run, and displayed `completed 20/20`; all 20 item rows displayed
  `completed` and `attempt 1`. Worker log reported 20 completed and 0 failed.
- **NEEDS MANUAL CHECK** - Killing the worker during an in-flight item and
  restarting it was not performed against a live process. The integration test
  simulates a persisted `running` item and verifies recovery (`attempts == 2`)
  with no duplicate run-item records; Celery is configured for late
  acknowledgements and worker-loss rejection.
- **PASS** - Cancel and pause/resume work; one item failure does not stop the
  rest of the run. Evidence: the run integration test verifies user pause and
  resume, quota pause and resume, cancellation, and 19 completed items plus one
  safely summarized failure.
- **UPDATED 2026-10-10** - Evaluation sends the raw dataset input to the
  UPLOAD_OUTPUTS connector so it can match the uploaded row. The recovery test
  now includes saved upload rows and verifies the expected 19 completed items
  plus one failed item.

### Validation

- `Push-Location backend; $env:DATABASE_URL='sqlite+aiosqlite:///./phase3_full_test.db'; .\.venv\Scripts\python.exe -m pytest -q tests; Pop-Location`
  - **22 passed**, 2 dependency deprecation warnings.
- `backend\.venv\Scripts\python.exe -m ruff check backend` - passed.
- `backend\.venv\Scripts\python.exe -m ruff format --check backend` - passed;
  34 files already formatted.
- `backend\.venv\Scripts\python.exe -m mypy --strict backend\app backend\alembic backend\tests`
  - passed; no issues in 33 source files.
- `$env:PATH=(Resolve-Path backend\.venv\Scripts).Path+';'+(Resolve-Path frontend\node_modules\.bin).Path+';'+$env:PATH; backend\.venv\Scripts\python.exe -m pre_commit run --all-files`
  - all seven configured hooks passed, including the backend suite.
- Frontend `npm run lint`, `typecheck`, `format:check`, and `build` - all passed.
- `docker compose up --build -d` - API, web, worker, Redis, and PostgreSQL
  healthy; `alembic current` reports `0003_phase3 (head)`.
- `/healthz` returned `{"status":"ok"}`, `/readyz` returned
  `{"status":"ready"}`, and `/docs` and the web app returned HTTP 200.
- No external model credentials were used; generation tests use a mock provider.

### Assumptions, known limitations, and deferred items

- Dataset generation currently relies on schema validation, exact duplicate
  removal, and human review. The broader spec's embedding-similarity dedupe,
  generated-item self-verification, quality filtering, and coverage report are
  deferred and must not be treated as implemented.
- Dataset item review uses a regular rendered list; a virtualized table is not
  implemented.
- Worker-loss recovery has integration coverage for replaying a persisted
  running item, but an actual process kill/restart remains a manual check.
- Uploaded XLSX support is included in addition to the Phase 3 CSV/JSON/JSONL
  acceptance scope.
- Local test databases, generated output, environment secrets, caches,
  dependency directories, and build output remain excluded from commits.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
docker compose exec -T api alembic current
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
(Invoke-WebRequest -UseBasicParsing http://localhost:5173).StatusCode
```

Open `http://localhost:5173`, select a project, import and approve a dataset,
then run it against a tested connector version to observe live progress.

## Phase 4 - Metrics: DONE WITH DOCUMENTED LIMITATIONS

### Acceptance checklist

- **PASS** - Every registered deterministic metric has fixed-example tests.
  Evidence: `test_every_rule_metric_returns_fixed_expected_score` covers
  answer presence, normalized exact match, RAG context-term recall, expected
  tool-call matching, latency, token instrumentation, and JSON Schema output.
  Invalid JSON and schema violations are covered separately.
- **PASS** - Metrics with absent requirements are `not_instrumented`, not
  failures. Evidence: `test_missing_required_metric_fields_are_not_instrumented`
  covers missing output/reference, retrieved chunks, tool calls, latency, token
  usage, and expected schema. Run integration verifies persisted statuses.
- **PASS** - Judge output is validated as bounded JSON and malformed output is
  repaired once. Evidence: `test_malformed_judge_json_is_retried_and_validated`
  verifies the retry and structured score.
- **PASS** - A cache hit prevents a second provider call. Evidence:
  `test_judge_cache_avoids_second_provider_call` sees exactly one mocked gateway
  call for two profiles with the same rubric/provider/model/input identity.
- **PASS (mocked provider)** - Hostile answer text is treated as untrusted and
  does not change the score. Evidence:
  `test_judge_prompt_treats_hostile_answer_as_untrusted` asserts the hardening
  instructions in both prompts and the same returned score for benign/hostile
  answers. This does not certify behavior of any live external model.
- **PASS** - Rule and judge score statuses, provider/model provenance,
  confidence, rubric version, cache-hit indicator, and multi-judge aggregate
  persist in run-item output; a project-scoped metric catalog is available.
  Evidence: the Phase 3 run test verifies a saved mocked dev-judge score,
  provider/model details, rule scores, and typed API output;
  `test_metric_catalog_api_is_project_scoped`,
  `test_metric_catalog_and_multi_judge_aggregation`, and
  `test_judge_cache_avoids_second_provider_call`.
- **PASS (manual browser smoke)** - The Dataset Studio page displays all metric
  categories and the versioned Dev/Final/Secondary judge profile editor.
  Evidence: `http://localhost:5173/workspace`, region “Metric library” and
  heading “Configure a versioned judge profile”.

### Validation

- Fresh isolated backend database: `pytest -q tests` - **43 passed**, 2
  dependency deprecation warnings.
- Ruff check and format check passed; strict mypy passed with no issues in 38
  source files.
- All seven configured `pre-commit run --all-files` hooks passed, including the
  backend test suite.
- Frontend ESLint, TypeScript typecheck, Prettier format check, and Vite build
  passed.
- `docker compose up --build -d` - API, web, worker, Redis, and PostgreSQL
  healthy; Alembic reports `0004_metrics (head)`. PostgreSQL confirms
  `eval_run_items.scores` is a JSON column.
- `/healthz` returned `{"status":"ok"}`, `/readyz` returned
  `{"status":"ready"}`, and `/docs` and the web app returned HTTP 200.
- No live provider credentials were used. Judge behavior and prompt-injection
  validation are tested with a mocked gateway.

### Assumptions, known limitations, and deferred items

- Registered deterministic checks are useful baselines, not a replacement for
  a task-specific calibrated rubric. Context recall is lexical term overlap,
  exact match uses normalized whitespace/case, the default latency threshold
  is 5000 ms, and token usage is instrumentation presence only.
- Judge prompt injection was validated at prompt construction with a mocked
  provider response; robustness on real provider models remains an empirical
  limitation.
- The judge cache has no eviction/retention policy yet; local deployments are
  expected to have small data volumes.
- Judge profiles are versioned when their rubric changes. Re-scoring completed
  traces in Final Report mode remains a Phase 8 item.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
docker compose exec -T api alembic current
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
(Invoke-WebRequest -UseBasicParsing http://localhost:5173).StatusCode
```

In Dataset Studio, inspect the metric library, configure a judge profile, run an
approved dataset, and expand run items to inspect persisted metric scores.

## Phase 5 - Verdict and trace viewer: DONE WITH MANUAL UI CHECK OUTSTANDING

### Acceptance checklist

- **PASS** - Any failed hard gate forces `NO_GO` and reports the exact metric,
  item position, observed score, and required threshold. Evidence:
  `test_hard_gate_failure_forces_no_go_with_exact_reason` and
  `test_hard_gate_matches_role_suffixed_judge_metric`.
- **PASS** - Weighted scores and threshold boundaries produce GO, REVIEW, and
  NO_GO. Evidence: `test_weighted_score_threshold_edges` and
  `test_category_weights_control_the_weighted_run_score`.
- **NEEDS MANUAL CHECK** - Results UI implements the verdict banner, category
  cards, radar chart, and per-item drill-down. Evidence: frontend ESLint,
  TypeScript, Prettier, and production build pass; the live web app returns
  HTTP 200. An authenticated visual check of a populated Phase 5 report was
  not completed.
- **NEEDS MANUAL CHECK** - Trace waterfall maps zero scores and configured
  hard-gate failures to the affected steps, and displays retrieved chunks next
  to the answer. Evidence: implementation in `frontend/src/DatasetStudio.tsx`
  passes lint, typecheck, formatting, and production build; populated trace
  rendering still needs browser inspection.
- **PASS** - Readiness reports identify failed execution, unavailable metric
  instrumentation, and missing trace fields. Evidence:
  `test_readiness_report_names_unavailable_metric_and_failed_component`,
  `test_readiness_detects_missing_application_instrumentation_fields`, and
  `test_criteria_api_is_project_scoped_and_reports_saved_run_snapshot`.
- **PASS** - Failed/cancelled runs and runs containing failed items cannot
  receive a misleading GO verdict. Evidence:
  `test_failed_or_cancelled_run_cannot_receive_go` and
  `test_readiness_report_names_unavailable_metric_and_failed_component`.

### Validation

- Focused Phase 5 tests: **12 passed**.
- Full backend suite: **55 passed**, 2 dependency deprecation warnings.
- Ruff check and format check passed; strict mypy passed with no issues in 43
  source files.
- All seven configured pre-commit hooks passed, including the full backend
  suite, ESLint, Prettier, and frontend TypeScript check.
- Frontend production build passed with Vite.
- `docker compose up --build -d` - API, web, worker, Redis, and PostgreSQL
  healthy. Alembic reports `0005_verdicts (head)`.
- `/healthz` returned `{"status":"ok"}`, `/readyz` returned
  `{"status":"ready"}`, and `/docs` and the web app returned HTTP 200.
- No live provider credentials were used. An authenticated populated-results
  browser check remains outstanding.

### Assumptions, limitations, and deferred items

- Category scores average each metric across run items, average metric means
  within each category, then apply the configured category weights.
- Runs snapshot their project's verdict criteria at creation; editing project
  criteria does not change reports for existing runs.
- Missing required trace instrumentation is reported as a readiness issue; it
  does not independently force NO_GO unless the configured scoring criteria
  require it.
- Phase 6 comparison and regression analysis have not started and require
  explicit user approval.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
docker compose exec -T api alembic current
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
(Invoke-WebRequest -UseBasicParsing http://localhost:5173).StatusCode
```

Sign in, open Dataset Studio, configure verdict thresholds and hard gates, run
an approved dataset, inspect the verdict/category results, and expand a run item
to check the answer, waterfall, and retrieved chunks.

## Phase 6 - Compare, failure analysis, regression: DONE

### Acceptance checklist

- **PASS** - Bootstrap confidence intervals and paired permutation/McNemar
  statistics match expected known values. Evidence: `test_paired_bootstrap_interval_is_exact_for_constant_differences`,
  `test_paired_permutation_uses_exact_two_sided_sign_flips`,
  `test_mcnemar_exact_matches_known_discordant_pair_probability`, and
  `test_holm_adjustment_controls_familywise_error` all passed.
- **PASS** - Paired compare logic correctly returns no significant difference
  for equal scores. Evidence: `test_compare_runs_reports_no_significant_difference_for_equal_scores` passed.
- **PASS** - Baseline promotion is Admin-scoped and audit-logged. Evidence:
  `test_baseline_approval_and_regression_api_are_scoped_and_audited` asserts
  `PUT /baseline` is denied for an engineer when it should require admin access,
  accepts the approved baseline, and records the audit log entries.
- **PASS** - Regression report returns PASS/WARN/BLOCK with reasons and a
  new-failure list. Evidence: `test_seeded_regressing_version_returns_block_with_new_failure`
  and `test_new_noncritical_failure_returns_warn` passed.
- **PASS** - A seeded regressing candidate run returns BLOCK and retains the
  regression-critical failure details. Evidence: the regression API test asserts
  the status is `BLOCK` and `new_failures[1].regression_critical` is true.

### Validation

- Backend focused Phase 6 tests: **8 passed**.
- Full backend suite: **63 passed**, 2 dependency deprecation warnings.
- Ruff check and format check passed; strict mypy passed with no issues in 49
  source files.
- All configured pre-commit hooks passed.
- Docker services remained healthy throughout validation; `/healthz` returned
  `{"status":"ok"}`, `/readyz` returned `{"status":"ready"}`, and `/docs`
  responded with HTTP 200.

### Assumptions, limitations, and deferred items

- Statistical significance is computed on paired item scores for the shared
  dataset items only; runs with no paired items return `insufficient_data`.
- The toolbox uses exact bootstrap/permutation tests and exact McNemar tests
  for deterministic, reproducible comparisons; it is not a substitute for a full
  benchmark analysis across thousands of examples.
- Phase 7 safety and red-team work is deferred until explicit approval.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
docker compose exec -T api alembic current
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
```

Sign in, open the project baseline controls, compare a baseline against a
candidate run, and inspect the regression report with its reasons and
new-failure list.

## Phase 7 - Safety and red-team: PARTIAL (helper logic only)

### Acceptance checklist

- **PARTIAL** - Attack-pack definitions cover the requested categories.
  Evidence: `test_attack_pack_contains_required_red_team_scenarios`. They are
  not executed against a selected app version by a red-team workflow.
- **PARTIAL** - Canary and system-prompt detectors work on supplied text.
  Evidence: `test_canary_and_system_prompt_leaks_are_detected` and
  `test_red_team_case_flags_canary_and_prompt_leaks`. No integrated flow plants
  a canary in an app system prompt and tests whether the app leaks it.
- **PARTIAL** - Summary helpers calculate ASR, leak, over-refusal, unsafe-tool,
  and guardrail-uplift values from supplied samples. Evidence:
  `test_phase7_summary_measures_attack_success_by_category_and_guardrail_uplift`.
  Results are not persisted or tied to live evaluation outputs.
- **PARTIAL** - `guardrail_ablation()` computes an ON/OFF comparison from
  supplied samples, covered by `test_guardrail_ablation_reports_category_uplift`;
  there is no workflow that executes both app configurations.
- **FAIL / KNOWN GAP** - Red-team findings cannot be promoted to
  regression-critical dataset items.
- **FAIL / KNOWN GAP** - Safety metrics are not supported as configured launch
  hard gates.
- **FAIL / KNOWN GAP** - There is no integrated red-team console or persisted
  safety assessment API.

### Validation

- Phase 7 helper tests: **6 passed**; this does not verify an integrated
  red-team workflow.
- No real provider credentials or live secrets were used in the safety tests.

### Assumptions, limitations, and deferred items

- The Phase 7 checks validate helper logic, not a live or persisted red-team
  assessment against an authorized app version.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
docker compose exec -T api alembic current
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
```

Use the helper tests as unit-level coverage only. Do not treat Phase 7 as
complete until the missing integrated workflow and gates are implemented.

## Phase 8 - Human review and calibration: PARTIAL (stateless helpers)

### Acceptance checklist

- **PARTIAL** - `queue_review_items()` computes reasons for supplied review
  candidates; `test_review_queue_auto_queues_risky_items` covers the helper.
  Evaluation runs do not persistently enqueue their risky items.
- **PARTIAL** - The review endpoints require a reviewer-capable workspace role,
  but there is no persisted review queue or stored reviewer grading workflow.
- **PARTIAL** - `blind_ab_compare()` computes a comparison from caller-supplied
  scores (`test_blind_ab_compare_hides_labels_and_reports_winner`); it does not
  load two runs or persist blinded assignments.
- **FAIL / KNOWN GAP** - Override audit state is caller-supplied through
  `audit_logged`; the endpoint does not persist an override or create an audit
  record. Justification validation alone is not an audited override workflow.
- **PARTIAL** - Calibration statistics are calculated from supplied values
  (`test_calibration_summary_reports_kappa_alpha_and_confusion_data`); there is
  no persisted calibration page or reviewer dataset.
- **PARTIAL** - Final-report summary calculation is covered by
  `test_final_report_reruns_score_summary_without_live_calls`, but the endpoint
  accepts caller-supplied traces rather than loading and rescoring stored run
  traces and scores.
- **FAIL / KNOWN GAP** - No human-review UI or persisted review/audit schema.

### Validation

- Phase 8 helper tests: **5 passed in 0.38s**; no persisted workflow integration
  tests are present.
- Command: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_phase8.py`
  - Result: **5 passed**.

### Environment and repo-status notes

- `make check` currently fails on this machine because `make` is not installed:
  `make : The term 'make' is not recognized as the name of a cmdlet, function, script file, or operable program.`
- This is an environment issue, not a project-code failure. The project’s
  Python-based validation was run instead via the backend test target above.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_phase8.py
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
```

The Phase 8 helper logic is validated. The persistent review and audit workflow
remains unimplemented.

## Phase 9 - CI regression and demo/export tooling: DONE WITH DOCUMENTED GAPS

### Acceptance checklist

- **PASS** - CI regression checks authenticate with a workspace-scoped API token
  and return a PASS/WARN/BLOCK status. Evidence: `test_phase9_api_tokens_enable_ci_regression_checks`
  passed, and `backend/app/routers/phase9.py` validates bearer or `x-api-token`
  credentials before calling `build_ci_response()`.
- **PASS** - `make seed` produces the demo states `GOOD=GO`, `BROKEN=NO_GO`, and
  `REGRESSING=BLOCK`. Evidence: `python scripts/seed_demo.py --output .tmp/seed-demo.json`
  generated a JSON payload with those three states and
  `backend/tests/test_phase9_seed.py::test_seed_demo_generates_required_states`
  passed.
- **PASS** - Markdown, CSV, and PDF report exports are generated from the seeded
  demo states. Evidence: `python scripts/export_reports.py --format all --output-dir .tmp/reports`
  wrote `demo-report.md`, `demo-report.csv`, and `demo-report.pdf`, and the
  backend export test passed.
- **PASS** - Research summary scripts emit a kappa value and a bootstrap
  confidence interval. Evidence: `python scripts/research_analysis.py --output .tmp/research.json`
  emitted a JSON object containing `cohens_kappa` and `score_ci`, and
  `backend/tests/test_phase9_seed.py::test_exports_and_research_scripts_create_artifacts`
  passed.
- **FAIL / KNOWN GAP** - Docker, Git, CLI, and Proxy entry-point sandbox
  execution remains unimplemented. Evidence: the Phase 9 connector types remain
  in the later-phase registry; no sandbox runner or trace-capture implementation
  is present in the repo.
- **FAIL / KNOWN GAP** - Proxy-mode trace capture and Playwright golden-path E2E
  remain unimplemented. Evidence: there is no proxy capture service or browser
  E2E script in the workspace.

### Validation

- Phase 9 focused backend tests: **3 passed**.
- Command: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_phase9.py tests/test_phase9_seed.py`
  - Result: **3 passed**.
- Full backend suite: **77 passed**, 2 deprecation warnings.
- Docker services remained healthy throughout validation: `docker compose ps`
  showed `api`, `web`, `worker`, `redis`, and `postgres` all healthy.
- `/healthz` returned `{"status":"ok"}`, `/readyz` returned `{"status":"ready"}`,
  and `/docs` returned HTTP 200.

### Assumptions, limitations, and deferred items

- Docker/Git/CLI/Proxy sandbox execution, Website URL discovery, and MCP runtime verification remain unproven without a verified sandbox/browser/MCP environment. The UI disables these entry points with clear reasons, the API rejects them with a "not available yet" error, and no fake trace is returned. Website URL discovery and MCP require manual verification against the seeded demo website and live MCP server before they are considered complete.
- The Phase 9 demo/export tooling is complete and validated, but the actual
  Docker/Git/CLI/Proxy connector runners and the browser automation golden path
  remain deferred.
- The codebase still does not contain a real sandboxed execution service for
  runner-style connector types; it avoids unsafe execution by keeping them as
  later-phase work.
- No Phase 10 completion is claimed. The separately requested UI/chat
  follow-up below remains incomplete and is not a Phase 10 closeout.

### Run and verify

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
python scripts/seed_demo.py --output .tmp/seed-demo.json
python scripts/export_reports.py --format all --output-dir .tmp/reports
python scripts/research_analysis.py --output .tmp/research.json
```

The Phase 9 CI token flow, demo-seeding output, and export/research scripts are
validated. The remaining connector sandbox and browser E2E work remains a
follow-up item, not a hidden blocker for the completed CI and demo tooling.

## Requested UI, chat, and connector follow-up - STILL WORKING

This is an incomplete user-requested follow-up, not a phase completion. The
following status reflects repository tests and code inspection; mocked provider
tests do not establish a live connection to a user's provider or application.

### Entry-point audit

| Entry point | Current status | Requirement or remaining work |
| --- | --- | --- |
| `HTTP_ENDPOINT` | Implemented and tested with mocked HTTP calls and SSRF checks | A live Docker-target smoke call has not been run. Private targets still require the existing Admin authorization path. |
| `PYTHON_FUNCTION` | Not implemented; disabled honestly | Requires an isolated Python worker with no network by default, no host mounts or secret access, resource limits, and hard timeouts. Planned for a separately authorized sandbox phase. |
| `PYTHON_SDK_TRACED` | Not implemented; disabled honestly | Requires the isolated Python worker plus real SDK instrumentation and trace-capture verification. Planned for a separately authorized sandbox phase. |
| `PROMPT_APP` | Implemented and tested with a mocked LLM gateway | No live provider call has been made in this validation. |
| `BUILTIN_RAG_APP` | Implemented and tested with a mocked LLM gateway | Retrieval and trace behavior are covered; no live provider call has been made. |
| `BUILTIN_AGENT_APP` | Implemented and tested with mocked provider/tool calls | Tool schema validation is covered; no live provider call has been made. |
| `DOCKER_IMAGE` | Not implemented; disabled honestly | Requires an isolated Docker runner, no host mounts, network disabled by default, resource quotas, and hard timeouts. Planned for a separately authorized sandbox phase. |
| `GIT_REPO` | Not implemented; disabled honestly | Requires isolated checkout/execution, restricted network access, no host mounts or secrets, quotas, and timeouts. Planned for a separately authorized sandbox phase. |
| `CLI_COMMAND` | Not implemented; disabled honestly | Requires isolated command execution with restricted filesystem/network access, quotas, and timeouts. Planned for a separately authorized sandbox phase. |
| `PROXY_MODE` | Not implemented; disabled honestly | Requires a verified outbound proxy sandbox and persisted trace capture. Planned for a separately authorized sandbox phase. |
| `UPLOAD_OUTPUTS` | Implemented and tested against uploaded sample rows | Lookup matching, mapping, preview, and validation are covered by backend/frontend tests. Live retest with `outputs_good.csv` is still requested. |
| `WEBSITE_URL` | Not implemented; disabled honestly | Requires an SSRF-protected isolated browser plus manual verification against a real target. Planned for a separately authorized browser-verification phase. |
| `MCP_SERVER` | Not implemented; disabled honestly | Requires a verified MCP runtime and manual protocol/auth verification. Planned for a separately authorized MCP phase. |

All 13 choices remain visible in the entry-point chooser; unsupported runners
are disabled with a reason. Their test calls are rejected rather than faked.

### Implemented in this follow-up

- Separate route navigation and page-specific sections, a mobile sidebar,
  breadcrumbs, page-step links, a top-bar active-project selector, and a
  workspace Assistant button.
- Workspace-scoped default provider/project/page/entry-point/mapping
  preferences; guarded drafts exclude uploaded rows and secret fields.
- Connector settings are sent through a per-entry-point allow-list, with
  provider/model at the top level. Backend settings remain strict.
- Owner-scoped Assistant and Test Chat storage, redaction, bounded context and
  summaries, searchable/renameable/deletable conversations, retention default
  of 30 days, and pending-only chat-to-dataset drafts.
- Test Chat stores the exact application context, trace/tool data when
  available, latency, and usage. UPLOAD_OUTPUTS does not claim to support live
  chat.
- Migration revisions use SQLite-compatible batch alterations and the complete
  migration chain was verified on a disposable SQLite database. The configured
  PostgreSQL database was advanced to revision `0009_chat_preferences_connectors`
  by the approved Compose upgrade; no database reset was performed.

### Current verification and limitations

- Backend full suite: **92 passed**, 2 dependency deprecation warnings.
- Backend Ruff check/format and strict mypy passed for the application,
  migrations, and tests.
- Frontend: **9 tests passed**, ESLint, TypeScript, Prettier, and Vite production
  build passed.
- Compose rebuild and service-health checks passed; `api`, `web`, `worker`,
  `redis`, and `postgres` were healthy, and `/healthz`, `/readyz`, and the web
  app returned successful responses.
- No authenticated browser retest of the provider/UPLOAD_OUTPUTS/Assistant/
  Test Chat workflow has been completed. No live provider credentials were
  used. Connector form, Assistant, and Test Chat coverage is not yet complete.
- The Test Chat draft endpoint preserves prior dataset records, labels
  provenance as `chat-session`, prevents sequential repeat additions, and
  leaves new rows `pending`; a concurrent double-submit integration test is
  still outstanding.
- Full feature acceptance is not complete. Do not treat the checklist above as
  completion of a new project phase.

## Current verification and completeness status (2026-10-11)

- **UPDATED** - The UPLOAD_OUTPUTS evaluation regression was fixed by passing
  dataset inputs without a JSON wrapper. The focused Phase 3 suite passed:
  `pytest -q tests\test_phase3.py` (**3 passed**).
- **UPDATED** - Full backend suite: `pytest -q tests` (**92 passed**, 2
  dependency deprecation warnings) using a temporary SQLite database.
- **UPDATED** - Full frontend checks: 9 tests, TypeScript typecheck, ESLint,
  Prettier, and production build.
- **PASS** - Backend Ruff check/format and strict mypy after formatting:
  `ruff check .`, `ruff format --check .`, and `mypy --strict app alembic tests`.
- **CONFIRMED GAP** - Phase 7 and Phase 8 currently have helper calculations
  and unit tests, not the integrated persisted safety and human-review
  workflows described above.
- **CONFIRMED GAP** - Runner-style sandboxing, proxy trace capture, full
  Playwright E2E, website discovery, and live MCP support remain unavailable.
- **VERDICT** - The project is **not complete overall**. The tested connector
  workflow and automated suites pass, but the listed product requirements and
  manual runtime checks remain incomplete.
