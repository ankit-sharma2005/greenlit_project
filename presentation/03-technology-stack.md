# Technology stack

Versions below come from the repository manifests, container tags, and the recorded build output. A range is shown as a range rather than presented as an exact installed version. Tools not identified by the repository are explicitly marked.

| Layer | Technology | Version from repo / observation | Why it was chosen | Where it is used |
|---|---|---|---|---|
| Backend runtime | Python | `3.11-slim` container base; `pyproject.toml` targets 3.11 | Async API, type-friendly domain logic, and mature evaluation libraries | `backend/Dockerfile`, `pyproject.toml` |
| API | FastAPI | `0.111.1` | Typed request/response validation and OpenAPI generation | `backend/requirements.txt`, `backend/app/routers/`, `backend/app/main.py` |
| Validation/config | Pydantic / pydantic-settings | `2.7.4` / `2.2.1` | Validate connector and API payloads; load settings | `backend/requirements.txt`, `backend/app/*schemas.py`, `config.py` |
| ORM and migrations | SQLAlchemy / Alembic | `2.0.31` / `1.13.2` | Async persistence and versioned schema changes | `backend/requirements.txt`, `backend/app/models.py`, `backend/alembic/` |
| Database | PostgreSQL | `16-alpine` image | Relational storage for users, workspaces, datasets, runs, and scores | `docker-compose.yml` |
| Queue and cache broker | Redis / Celery | Redis `7-alpine`; Celery `5.4.0` | Separate API request handling from queued evaluation work | `docker-compose.yml`, `backend/requirements.txt`, `backend/app/worker.py` |
| HTTP client | HTTPX | `0.27.2` | Async outbound provider and connector calls; mock transport in tests | `backend/requirements.txt`, connector/gateway services |
| Provider SDK | OpenAI Python SDK | `>=1.109.0,<3.0.0` | Common OpenAI-compatible API for configured providers | `backend/requirements.txt`, `backend/app/services/llm_gateway.py` |
| Providers | GitHub Models, Ollama, custom OpenAI-compatible API | Endpoints/configuration in code/spec; no repository-pinned provider service version | One gateway can target different providers; credentials are configured per workspace | `backend/app/services/llm_gateway.py`, `backend/app/routers/phase2.py` |
| Frontend runtime | Node.js | `20-alpine` container base | Runs Vite and frontend tooling | `frontend/Dockerfile` |
| Frontend UI | React / React DOM | `^18.3.1` | Component-based interactive workspace and dataset screens | `frontend/package.json`, `frontend/src/` |
| Frontend language/build | TypeScript / Vite | TypeScript `^5.5.4`; Vite `^5.4.2` in manifest. Recorded build used Vite `5.4.21`. | Typed UI and local dev/build pipeline | `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts` |
| Routing | React Router DOM | `^6.28.0` | Routes for landing, auth, password reset, and workspace | `frontend/package.json`, `frontend/src/App.tsx` |
| Frontend lint/format | ESLint / Prettier | ESLint `^10.0.0`; Prettier `^3.5.3` | Catch static issues and enforce consistent formatting | `frontend/eslint.config.js`, `frontend/.prettierrc.json`, package scripts |
| Backend tests | pytest / pytest-asyncio | `8.2.2` / `0.23.7` | Unit and asynchronous API integration tests | `backend/requirements.txt`, `backend/tests/` |
| Backend lint/types | Ruff / mypy | `0.11.13` / `1.15.0` in dev requirements | Fast lint/format checks and strict static typing | `backend/requirements-dev.txt`, `pyproject.toml` |
| Security: passwords and tokens | Passlib Argon2 / PyJWT | Passlib `1.7.4`; PyJWT `2.8.0` | Password hashing and signed access/refresh tokens | `backend/requirements.txt`, `backend/app/security.py` |
| Security: secret encryption | cryptography / Fernet | `>=44.0.0,<46.0.0` | Encrypt stored provider and connector credentials | `backend/requirements.txt`, `backend/app/services/secrets.py` |
| Security: schemas | jsonschema | `>=4.23.0,<5.0.0` | Validate structured outputs and tool arguments | `backend/requirements.txt`, connectors/metrics |
| Containers | Docker Compose | Compose file version not pinned; individual service image tags are recorded | Reproducible local API, worker, web, database, and Redis stack | `docker-compose.yml`, backend/frontend Dockerfiles |
| Local hooks | pre-commit | `4.2.0` | Provides a single configured command for lint, types, tests, and frontend checks | `.pre-commit-config.yaml`, `backend/requirements-dev.txt` |
| CI | GitHub Actions | Not present in tracked files | No repository workflow can be named or versioned; local hooks are configured instead | No tracked `.github/` directory |
| Development editor | VS Code | Not specified in tracked repo files | User-provided environment; repository does not record editor version | Not applicable |
| AI coding assistant | GitHub Copilot | Not specified in tracked repo files | User-provided development environment; no `.github/copilot-instructions.md` is tracked | Not applicable |
| Windows container tooling | Docker Desktop / WSL 2 | Not specified in tracked repo files | Cannot verify setup steps or versions from this repository | Not applicable |
| Version control | Git | Commit history exists; client version not recorded | Tracks phase-sized implementation commits | Git repository history |

## Environment variable names

The repository's `.env.example` names the following settings: `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `ENCRYPTION_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_TTL_MINUTES`, `REFRESH_TOKEN_TTL_DAYS`, `APP_ENV`, `WEB_ORIGIN`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL`. This document intentionally omits example values and never reads or reproduces `.env`.
