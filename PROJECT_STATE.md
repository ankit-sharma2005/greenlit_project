# GreenLit — Project State Audit

**Audit Date:** 2026-10-24  
**Auditor:** Senior Full-Stack Engineer (Clean take-over from Freebuff)  
**Verification Method:** Direct execution of test suites, linters, typecheckers, build tools, and code inspection.

---

## 1. Executive Summary

The project is approximately **60% complete** against the full specification (`FREEBUFF_PROMPT_GreenLit.md`). Milestones **M0 through M5** are fully implemented, verified, and backed by comprehensive unit and integration tests. Milestone **M6** is partially built (persistence layer M6a is committed; execution engine, Celery task pipeline, cancellation, and API endpoints M6b are pending). Milestones **M7 through M10** have not been started yet.

The codebase is clean, well-architected, and adheres strictly to the decisions recorded in `DECISIONS.md`.

---

## 2. Test & Verification Metrics

All verification commands were executed directly on the machine:

| Suite / Tool | Command | Scope | Result | Notes |
|---|---|---|---|---|
| **Backend Unit & Integration Tests** | `pytest -q` | `backend/tests/` | **209 passed** (100%) | Covers auth, providers, connectors, datasets, decision engine, rule metrics, run repository |
| **Backend Lint** | `ruff check .` | `backend/` | **All checks passed** | Zero lint errors |
| **Backend Format** | `ruff format --check .` | `backend/` | **All checks passed** | Formatted properly |
| **Backend Typecheck** | `mypy` | `backend/` | **Success: 0 issues in 46 source files** | Strict typing enforced |
| **Frontend Unit & Component Tests** | `npm test` | `frontend/src/` | **32 passed in 10 test files** | Vitest + Testing Library |
| **Frontend Lint** | `npm run lint` | `frontend/` | **Zero issues** | ESLint flat config |
| **Frontend Typecheck** | `npm run typecheck` | `frontend/` | **Zero issues** | `tsc --noEmit` passes cleanly |
| **Frontend Production Build** | `npm run build` | `frontend/` | **Successful build** | Vite production bundle created in 3.54s |
| **Frontend Prettier** | `npm run format:check` | `frontend/` | 5 files have formatting warnings | Prettier style differences in `src/components/ProvidersPanel.tsx`, `src/pages/NewTestPage.tsx`, `src/pages/ResultsPage.test.tsx`, `tests/e2e-admin.spec.ts` |

---

## 3. Detailed Milestone Status

### M0 — Foundation: COMPLETE
- **Docker Compose Stack:** Multi-service composition (`postgres`, `redis`, `api`, `worker`, `web`) with non-clashing default host ports: Web 5177, API 8003, Postgres 5436, Redis 6382.
- **Backend Infrastructure:** FastAPI with sync SQLAlchemy 2.0 (`postgresql+psycopg://`), Alembic baseline migration `0001_initial` (`pgcrypto`), unified error envelope `{"error": {"code", "message", "fields"}}`, `/healthz` and `/readyz` endpoints.
- **Frontend Foundation:** Vite + React 19 + TypeScript, React Router, CSS custom properties with light/dark theme toggle (dark default).
- **Design System Components:** `<Spinner />` (sizes sm/md/lg/xl), `<Button loading />` with 10s slow-action state switch, `<ProgressBar />`, responsive sidebar navigation, top bar with brand mark and text.

### M1 — Accounts & Auth: COMPLETE
- **Authentication:** Argon2id password hashing, short-lived access JWT cookie (15m), rotating opaque refresh token (14d) stored as SHA-256 hash with reuse family revocation.
- **Rate Limiting:** Redis fixed-window rate limiter for sign-in (5 attempts / 15 min), failing open if Redis is down.
- **RBAC:** Roles `admin`, `member`, `reviewer`. First registered user automatically promoted to `admin`. Protection against demoting the last admin.
- **Audit Logging:** Append-only `audit_events` table for authentication, role changes, and data lifecycle.
- **Password Reset:** Token generation and reset endpoints with single-use hashed tokens. (Uses `debug_token` in development).
- **Frontend Auth UX:** `RequireAuth` route guard, `AuthProvider`, login, and registration forms.

### M2 — Providers & LLMGateway: COMPLETE
- **Provider Management:** Provider CRUD API, support for Ollama and OpenAI-compatible endpoints.
- **Secret Protection:** Provider API keys encrypted at rest with AES-GCM app key; never exposed in API responses or logs.
- **Health Verification:** Test connection endpoint `/api/v1/providers/test` and provider health badge.
- **LLMGateway:** Central gateway for all model calls with exponential backoff retries, rate limiting, and timeout enforcement.
- **Setup Checklist:** Top-bar setup checklist showing provider status.

### M3 — Connectors & One-Box New Test: COMPLETE
- **Supported Connectors:**
  1. `HTTP_ENDPOINT` (with auto-detect and cURL import)
  2. `PROMPT_APP` (system prompt + model)
  3. `UPLOAD_OUTPUTS` (precomputed answers CSV/JSON)
- **Coming Soon Connectors:** 9 additional connector types registered in schema and returning HTTP 501.
- **SSRF Defense:** SSRF-safe HTTP client blocking RFC1918 / loopback IPs unless the "This app runs on my computer" toggle is enabled.
- **Format Auto-Detection:** Endpoint probing with common body shapes (`question`, `input`, `messages`, etc.) and extraction paths (`answer`, `choices.0.message.content`, `context`, etc.).
- **New Test UI:** Dynamic target input based on entry-point, cURL parser modal, test type selector checkboxes.

### M4 — Datasets & Test Generation: COMPLETE
- **M4a Upload & Column Detection:** Multi-format parser (CSV, JSON, JSONL, XLSX via `openpyxl`), two-pass column role detector, SHA-256 version content hashing.
- **M4b Approval & Generation:** Dataset version approval workflow (`dataset.approved` audit event), LLM test generation endpoint (`/generate`) with preview and approval.

### M5 — Metrics & Decision Engine: COMPLETE
- **Rule-based Metrics:** `answer_match`, `exact_match`, `latency_p50`, `latency_p95`, `error_rate`, `timeout_rate`.
- **Decision Engine:** Hard gate evaluation, weighted average score calculation, priority rules (NO-GO, REVIEW, GO) with plain-language explanations and actionable fix suggestions.
- **Evaluation Preview API:** `/api/v1/evaluations/preview`.
- **Results Page UI:** Metric scorecard, failed cases breakdown, verdict card.

### M6 — Runs & Orchestration: IN PROGRESS (M6a Done, M6b Pending)
- **M6a (Committed - `f87511a`):**
  - Database schema: `runs`, `run_items`, `metric_results` (migration `0008_runs`).
  - Six run states: `queued`, `running`, `cancelling`, `cancelled`, `failed`, `completed`.
  - Repository layer: `app/services/run_repository.py` with 14 unit tests.
- **M6b (Missing):**
  - Celery background worker tasks for batch execution across dataset items.
  - Test runner loop: per-item timeout enforcement, error isolation (individual item failure must not crash the run), metric accumulation.
  - Run management API: `POST /api/v1/runs`, `GET /api/v1/runs/{id}`, `GET /api/v1/runs/{id}/items`, `POST /api/v1/runs/{id}/cancel`.
  - `POST /api/v1/quick-test` one-shot test orchestration API.
  - UI integration: Connecting "Start test" button on New Test page to run dispatch and displaying live progress (stage, percentage, elapsed time, cancel button).

### M7 — Judge & Calibration: NOT STARTED
- LLM-as-a-judge profiles and structured evaluation prompts.
- Judge failure handling (single retry, default to REVIEW on unparseable output).
- Human review queue for borderline scores.
- Cohen's kappa calibration metric calculation.

### M8 — Safety Evaluation: NOT STARTED
- Built-in test sets for prompt injection, jailbreaks, prompt leakage, and harmful content.
- Critical safety hard gates (immediate NO-GO on critical safety breach).
- Dedicated safety report section.

### M9 — Regression & Reports: NOT STARTED
- Baseline management (`is_baseline` flag, setting/clearing baseline).
- Run comparison view (case-by-case regression, status PASS / WARN / BLOCK).
- Multi-format report export: HTML (standalone printable), PDF, JSON, CSV (with CSV formula injection protection).

### M10 — Demo & Polish: NOT STARTED
- `demo-app` FastAPI container in docker-compose (`profile: ["demo"]`).
- Embedded demo data: helpdesk dataset, `outputs_good.csv`, `outputs_broken.csv`, `helpdesk_info.pdf`.
- "Try the demo" one-click button in UI.
- "Right-reason" tests confirming expected explanations for good and broken targets.
- Playwright end-to-end tests.
- Final `HANDOVER.md` and documentation polish.

---

## 4. Git & Stash Audit

- **Branch:** `master` (clean working tree, no uncommitted changes).
- **Stashes:** Two stashes exist (`stash@{0}` and `stash@{1}`: "freebuff step1 wip").
  - *Audit Note:* These contain broken, duplicate imports and aborted edits from the previous agent's edit loop. They should **not** be applied directly.

---

## 5. Identified Bugs & Technical Debt

1. **Frontend Prettier Inconsistencies:** 5 frontend files deviate slightly from Prettier rules. Easily fixed with `npm run format`.
2. **Password Reset Email Delivery:** Password reset generates and returns a `debug_token` in dev mode. A production mail adapter is required before deployment.
3. **Run Execution Not Hooked to UI:** The New Test page UI currently has mock/disabled execution hooks because M6b was incomplete.

---

## 6. Next Steps (Action Plan for M6b)

1. Format frontend files to ensure 100% clean `npm run format:check`.
2. Implement run execution service (`app/services/run_executor.py`) to run connector queries over dataset items with error isolation and timeout controls.
3. Wire Celery tasks in `app/tasks/runs.py` and connect `celery_app.py`.
4. Implement Run REST API endpoints (`/api/v1/runs`, `/api/v1/runs/{id}`, cancel, and `/api/v1/quick-test`).
5. Update Frontend New Test page to trigger runs and display live progress.
6. Write unit and integration tests for the execution lifecycle and verify all tests pass.
