# GreenLit

GreenLit is an offline pre-launch evaluation platform for LLM-powered applications.
The current work covers the foundation, app setup, golden datasets, evaluation
runs, metrics, launch verdicts, and trace inspection.

## Quick start

1. Copy `.env.example` to `.env` and set local secrets (PowerShell: `Copy-Item .env.example .env`).
2. Run `docker compose up --build`.
3. Open `http://localhost:5173` for the web app and `http://localhost:8000/docs` for the API docs.

Compose waits for PostgreSQL and Redis before starting the API, then waits for the
API readiness check before starting the web app. The readiness check verifies a
database connection. Use `docker compose ps` to inspect service health and
`docker compose down` to stop the stack without deleting the database volume.

The login and signup screens use the API at `VITE_API_URL` (default:
`http://localhost:8000`). Access tokens remain in memory; refresh tokens are
sent as httpOnly cookies and rotated by `POST /api/v1/auth/refresh`. In
development, password-reset instructions are printed to the API console. For
SMTP delivery, set `SMTP_HOST` and `SMTP_FROM_EMAIL`; optionally set
`SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_PORT`.

## Stack
- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, Celery
- Frontend: React + TypeScript + Vite + CSS design system

## Roadmap status

Phase 1 is DONE. It delivers the app shell, authentication, workspaces, RBAC,
audit events, migrations, Compose stack, and verified dark/light and keyboard
navigation behavior. The UI smoke check is not a full WCAG accessibility audit.

The web shell supports API-backed signup, login, session restoration, workspace
listing, logout, and password reset. Password reset uses a one-time expiring token,
stored hashed, and invalidates existing refresh sessions. Workspace role checks use
the user's role in that workspace membership. Alembic has an initial schema migration
and Compose applies it before starting the API.

Phase 2 is complete with documented limitations. Provider configurations (GitHub
Models, Ollama, and custom OpenAI-compatible endpoints), workspace projects, app
versions, judge profiles, connector validation/test calls, secret encryption,
trace responses, Prompt App, built-in RAG and Agent, and the 13-type entry-point
registry are implemented. Connector configurations require a successful matching
test call before they can be saved. Python Function and Python SDK Traced are
disabled until a safe isolated execution runner is available; arbitrary user
Python is not executed.

Phase 3 is complete with documented gaps. Dataset Studio supports CSV, JSON,
JSONL, and XLSX uploads, four template-driven generation paths, human approval,
version hashing, and dev/test splits. Celery runs approved examples per item,
streams progress, and supports pause, resume, cancel, and recovery of persisted
running items. See [Phase 3 evidence and limitations](docs/PROGRESS.md),
including the live 20-item browser run and the worker-kill/restart manual check
that remains.

Phase 4 is complete with documented limitations. A typed metric catalog offers
deterministic answer-quality, RAG, tool-use, JSON-schema, latency, and token
instrumentation checks, plus configured versioned LLM judge profiles. The `answer_match` metric case-folds text, removes punctuation and common stop
words, and scores exact normalized matches as 1.0. Other answers are scored
using the greater of Jaccard token overlap and character sequence similarity.
This is a lightweight heuristic, not a guarantee of semantic equivalence; older
`answer_exact_match` runs remain readable and display under the canonical
`answer_match` label. Judge profiles are snapshotted with each new run, including
the selected provider, model, rubric, and rubric version. Judge requests have a bounded timeout;
a configured judge error requires REVIEW rather than allowing an otherwise
high-scoring run to silently receive GO. Results are schema-validated, retried
once if malformed, cached by rubric and input identity, and stored alongside
per-item scores. Missing trace fields are reported as not instrumented. Judge
prompt-injection tests use a mocked provider; they are not a certification
against real judge models. See
[Phase 4 evidence and limitations](docs/PROGRESS.md).

Phase 5 adds project-level GO/REVIEW/NO_GO criteria with hard gates, immutable
criteria snapshots per run, weighted category results, readiness diagnostics,
and answer/trace/chunk drill-down. Criteria and verdict behavior are covered by
backend tests. A populated authenticated result screen still needs a manual
browser check. Authenticated run reports can be downloaded as self-contained,
printable HTML, PDF, JSON, or case-level CSV from
`/api/v1/runs/{run_id}/report?format=...` (and the workspace/project-scoped
Results route). Exports include the run metadata, applied criteria, metric
thresholds, failed cases, safety/regression status, and calibration status. Results includes authenticated download actions for each
format;
secret-like settings and trace fields are omitted. Calibration is explicitly
marked unavailable until human labels are persisted. See
[Phase 5 evidence and limitations](docs/PROGRESS.md).

Phase 6 adds baseline approval, paired-run comparison, bootstrap/permutation/
McNemar statistics, regression detection, and regression-critical failure
reporting. It is implemented and validated with focused and full backend
integration tests. See [Phase 6 evidence](docs/PROGRESS.md).

Phase 7 has tested safety helper functions, but does not yet provide an
integrated red-team runner, persisted assessments, attack promotion, or safety
launch gates. Phase 8 has tested calculation helpers, but does not yet provide a
persisted review queue, reviewer audit trail, or human-review UI. These phases
are partial, not complete.

Phase 9 adds the remaining CI and polish tooling: API-token-based CI
regression checks, deterministic demo seeding for GOOD/BROKEN/REGRESSING,
research summaries for kappa and confidence intervals, and export scripts for
Markdown, CSV, and PDF output. The demo/export tooling is checked by backend
tests and its artifacts are saved under `.tmp` during validation. The Docker,
Git, CLI, and Proxy connector sandbox work and browser E2E remain incomplete.

The latest automated validation has 85 backend tests passing and 8 frontend
tests passing. Backend Ruff check/format and strict mypy, frontend ESLint,
Prettier, TypeScript typecheck, and production build pass. These checks do not
mean all product acceptance criteria are complete; see
[docs/PROGRESS.md](docs/PROGRESS.md).

## Known limitations

- Docker/Git/CLI/Proxy sandbox execution, Website URL discovery, and MCP runtime verification are unavailable. The UI disables these entry points with clear reasons, the API rejects them with a "not available yet" error, and no fake trace is returned.
- Phase 7 safety assessments and Phase 8 human reviews are not yet integrated, persisted workflows; current code provides helper calculations only.
- The provider rate limiter is process-local, so limits are not persisted across restarts or coordinated across multiple API processes.
- Provider connection and RAG tests use mocked provider responses; configure real credentials/endpoints to test external providers.
- Generated-data embedding-similarity deduplication, self-verification, quality filtering, and coverage reports are not yet implemented.

### Local checks

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Push-Location backend
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy --strict app alembic tests
.\.venv\Scripts\python.exe -m pytest -q tests
Pop-Location
npm ci --prefix frontend
npm --prefix frontend run lint
npm --prefix frontend run format:check
npm --prefix frontend run typecheck
npm --prefix frontend run build
$env:PATH = (Resolve-Path 'backend\.venv\Scripts').Path + ';' + $env:PATH
.\backend\.venv\Scripts\python.exe -m pre_commit validate-config
.\backend\.venv\Scripts\python.exe -m pre_commit run --all-files
```

Install the repository hooks with
`.\backend\.venv\Scripts\python.exe -m pre_commit install`.
