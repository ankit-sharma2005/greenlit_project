# GreenLit phase progress

Updated: 2026-10-08

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

### Validation

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

Phase 3 has not been started and requires explicit approval.
