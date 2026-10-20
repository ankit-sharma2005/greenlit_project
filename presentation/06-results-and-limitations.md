# Results and limitations

## Current validation snapshot

The figures below come from the most recent full validation output available for this working tree, not the older headline in `README.md` or `docs/AUDIT.md`.

| Check | Observed result | Evidence and interpretation |
|---|---|---|
| Backend lint | Passed: `ruff check .` reported `All checks passed!` | Executed from `backend` using `.venv\Scripts\python.exe -m ruff check .`. |
| Strict backend typing | Passed: `Success: no issues found in 61 source files` | `mypy --strict app alembic tests`. |
| Backend tests | **76 passed, 4 failed, 2 warnings; 80 tests total** | `pytest -q tests` completed in 40.89 seconds. Failures: `test_website_url_and_mcp_server_test_calls_are_validated`, `test_entry_point_registry_lists_phase10_types`, `test_registry_lists_all_thirteen_types_and_validates_type_settings`, `test_sandboxed_docker_git_cli_and_proxy_connectors_execute`. |
| Failure detail | Phase 10 call test expected HTTP 200 but received 422 “not available yet”; another expected `coming_in == "phase 10"` but received the explicit manual-verification message. The Phase 2 registry test received 401 where it expected 422, and the Docker/Git/CLI/Proxy execution test expected success but received 422 under current gating. | Test output and current metadata are inconsistent. This pack does not change tests or code. |
| Frontend lint | Passed; ESLint emitted no findings | `npm run lint` in `frontend`. |
| Frontend typecheck | Passed; `tsc --noEmit` emitted no findings | `npm run typecheck` in `frontend`. |
| Frontend build | Passed; Vite `5.4.21`, 37 modules, built in 19.60 seconds | `npm run build` in `frontend`. These are build output facts, not an end-to-end browser proof. |
| pre-commit | **Failed in the recorded run** | System hooks could not find `ruff`/`mypy` on PATH; the backend-tests hook used a Python environment missing `openpyxl`. This is distinct from the direct `.venv` lint/type commands. |
| Compose | Five services reported healthy: API, worker, web, Redis, PostgreSQL | `docker compose ps`. The latest captured `Invoke-RestMethod` output did not include serialized response bodies. |
| Health and readiness | Prior project evidence records `/healthz` as `{"status":"ok"}` and `/readyz` as `{"status":"ready"}`; the latest invocation did not render the bodies in its capture | `docs/PROGRESS.md` and earlier validation logs. Treat the latest response body as not independently captured. |
| Seed scenario | The script ran and printed the state names `BROKEN`, `GOOD`, and `REGRESSING`. Source maps them to `NO_GO`, `GO`, and `BLOCK` respectively. | `scripts/seed_demo.py` and `backend/tests/test_phase9_seed.py`. This is a JSON summary of static examples, not a seeded live database or demo website. |

### Correcting an older count

`README.md` and `docs/AUDIT.md` report 77 passing backend tests from a previous validation state. The latest observed run collected 80 tests and had four failures. For a presentation of the current tree, use **76 passed / 4 failed**, not the historical 77-pass figure. The latest failures are directly related to the conflict between disabled connector metadata and tests that still expect those connectors to succeed.

## What is measured

- Rule metrics include answer presence, normalized exact match, lexical context-term recall, tool-call matching, latency threshold, token-usage presence, and JSON-schema validity.
- Judge responses are schema-validated, retried once when malformed, and cached by a content/rubric/provider/model identity.
- Baseline comparisons use paired item results and statistical helpers; tests check deterministic expected values.
- Safety services calculate rates from supplied samples and detect configured canary-like strings.
- Test suites validate contracts and edge cases. They do **not** measure real-world defect-detection precision/recall or certify model safety against live attacks.

## Known limitations

These limitations are recorded in `docs/AUDIT.md`, `docs/PROGRESS.md`, or are visible from current code:

- Phase 10 Website URL discovery and MCP runtime behavior need real browser/server verification. Both are gated in the registry; current tests expecting successful calls are failing.
- The WEBSITE_URL authorization checkbox/audit trail, real-site discovery screenshot/confidence, request cap/throttling, and CAPTCHA/login inaccessible behavior are not proven by current live evidence. Follow `docs/manual-tests/phase-10.md` only when a real authorized demo site and browser runner are available.
- Docker, Git, CLI, and Proxy sandbox execution is not a verified supported runtime. Python Function and Python SDK Traced are intentionally disabled until safe isolation exists.
- A live external provider was not used for the provider/RAG/judge contract tests. Those tests mock provider responses.
- The provider rate limiter is process-local and is not shared across API processes or persisted across restarts.
- Generated-data embedding-similarity deduplication, self-verification, quality filtering, and coverage reporting are not implemented, according to README.
- The Phase 9 seed output is static JSON. It does not create the production-like demo workspace, users, website, and running apps described in the spec.
- The repo has no tracked `.github/` workflow and does not prove GitHub Actions execution.
- Phase 5 populated result/trace UI and Phase 3 worker-kill recovery still need manual verification in `docs/PROGRESS.md`.
- The current `.pre-commit` system-hook invocation is environment-sensitive: direct project-venv checks pass, but the captured pre-commit run could not resolve all tools and used a Python missing `openpyxl`.
- The exact screenshot/manual state is not included in the repo; capture only real screens and label unavailable pages as unavailable.

The formal audit verdict is **COMPLETE WITH KNOWN GAPS**. The latest failed tests mean the current tree should not be described as “all checks passing.”

## Future work, in evidence order

1. Reconcile the disabled-entry-point policy with the older tests: test deliberate API rejection and no fake trace, or implement and validate the runtime before changing the gate.
2. Make pre-commit resolve the same local tool environment used by direct checks, then rerun all hooks.
3. Prove the HTTP endpoint and a real provider run end-to-end with non-production test credentials, without exposing secrets.
4. Validate recovery after killing and restarting a worker.
5. Complete authenticated browser inspection of populated results and trace views.
6. Only enable Website URL, MCP, Docker, Git, CLI, Proxy, or arbitrary Python execution after safe live runtime evidence exists.
7. Build actual report export from stored evaluation runs and an actual database-backed demo seed, if required by the project spec.
8. Add and run a real CI workflow if GitHub Actions is a deliverable.
9. Collect real human review labels and use them to evaluate judge agreement before making calibration claims.
