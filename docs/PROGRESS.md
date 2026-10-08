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

## Phase 2 - Providers, projects, entry points: IN PROGRESS, approval-gated

Implementation and known gaps are documented in `docs/PROJECT_SPEC.md`. No
additional Phase 2 work is authorized until the user approves after Phase 1
closeout.
