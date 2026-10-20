# Viva questions and honest answers

### 1. What problem does GreenLit solve?

It organizes repeatable pre-launch testing for LLM applications, where prompts, retrieval, tools, parsing, safety, latency, and model choice interact. It targets application readiness rather than raw model ranking. See `docs/PROJECT_SPEC.md`, section 1.

### 2. How is this different from a model benchmark?

A model benchmark ranks model behavior on benchmark tasks. GreenLit intends to evaluate a team's app version against its own approved examples and criteria, including optional application trace data.

### 3. What is a golden dataset?

A versioned, content-hashed collection of test examples. The dataset code stores the prompt/input, optional references, category, provenance, review status, split, and application-specific data. Only approved items should be used as golden examples.

### 4. What is an entry point?

It is the connector boundary where GreenLit sends one test input and receives an output. The API registry lists 13 types, but the current metadata marks several unavailable.

### 5. What is the trace contract?

A common shape for output, optional steps such as retrieved chunks or tool calls, token usage, latency, and model identity. Optional fields let one scorer serve black-box and more instrumented apps.

### 6. Why report “not instrumented”?

If an app does not return a field a metric needs, GreenLit should not invent a value or score it as a product failure. The metric can explain which instrumentation is absent.

### 7. How does the decision engine work?

It checks hard gates first, then applies weighted scores and thresholds. A hard-gate failure can force NO_GO and report the reason. The result is a decision aid, not a production-safety guarantee.

### 8. What makes a regression comparison meaningful?

The two runs must use the same dataset version and split. The service pairs item results, calculates statistical comparisons, and can flag new regression-critical failures.

### 9. Why use paired statistics?

The same items are evaluated under two versions, so item-level differences are more informative than comparing unrelated average scores. The code includes bootstrap intervals, permutation testing, and McNemar's exact test.

### 10. Which providers are supported?

The gateway is built around OpenAI-compatible APIs, and the repo names GitHub Models, Ollama, and custom-compatible providers. The provider tests use mocks; a successful live provider run is not proven by those tests.

### 11. What happens at a provider rate limit?

An in-process limiter queues requests by provider and tracks per-day counts. Daily exhaustion raises a pause condition that the run engine can persist. The limiter is process-local and does not coordinate between API replicas or survive a restart.

### 12. Does the gateway always fall back to Ollama?

No. Fallback IDs are configured, and the gateway can try another provider for retryable provider failures. It is not an unconditional switch to Ollama; daily quota exhaustion is handled as a pause. No live fallback run is recorded.

### 13. How do you make judge output reliable?

The result must validate against a Pydantic schema; malformed output is retried once. The cache keys rubric/provider/model/input identity. Prompt-injection tests use a mocked provider, so they do not prove real-model immunity.

### 14. How do you know whether the judge agrees with people?

The human-review service can calculate Cohen's kappa, Krippendorff's alpha, Spearman correlation, and a confusion matrix. The repository proves calculations with tests, not a real human-labeled study or calibrated model.

### 15. How do you prevent unsafe user-code execution?

Python Function and Python SDK Traced are disabled until an isolated runner is available. Other sandbox-dependent connector types are also gated in the registry. The project should not be presented as having a verified arbitrary-code sandbox.

### 16. What SSRF protection exists?

The connector source includes a public-target validation path and per-connector settings. That is evidence of checks in code, not an independent security certification; sandboxed connector execution is explicitly a known limitation.

### 17. How are passwords and provider secrets handled?

Passwords are hashed using Argon2 via Passlib. Refresh/reset/API tokens are stored as hashes where applicable. Provider and connector secrets use Fernet encryption. The auth and provider tests check flows and redaction.

### 18. How does refresh-token rotation work?

The refresh token is an httpOnly cookie. The backend stores a hash and replaces it during `/api/v1/auth/refresh`; the old token no longer matches the stored hash. Tests cover refresh and logout. Avoid claiming a broader session-management product not evidenced by the UI.

### 19. How are roles and workspaces enforced?

FastAPI dependencies resolve workspace membership and role, while route queries commonly include workspace/project IDs. Tests cover viewer restrictions and cross-workspace denial.

### 20. What is actually seeded by `make seed`?

The tracked `scripts/seed_demo.py` creates static GOOD/BROKEN/REGRESSING report data and writes JSON. It does not populate the live database, users, site, or apps described by the original spec.

### 21. Are all ten phases complete?

The audit says “COMPLETE WITH KNOWN GAPS”; Phases 1–9 are marked implemented/tested at the audit-summary level, while Phase 10 is partial. The progress doc preserves manual checks and gaps. The latest backend run has four failures, so I do not claim all checks currently pass.

### 22. What are the current test results?

The latest full recorded backend run had 76 passed, 4 failed, and 2 warnings. Ruff and strict mypy passed; frontend lint, typecheck, and build passed. The recorded pre-commit run failed because its system hooks could not resolve tools and its Python test environment lacked `openpyxl`.

### 23. Why does the Phase 10 test fail?

The current connector registry intentionally returns an unavailable error while an older contract test expects a successful Website URL/MCP call. The test and current acceptance policy have diverged; it should be reconciled before claiming Phase 10 works.

### 24. What is the biggest technical limitation?

Safe, verified execution boundaries and end-to-end evidence. Several connector types are disabled, Website URL and MCP need real validation, the Phase 9 seed is static, and current tests are not all green.

### 25. What would you do differently next?

First align tests and documentation with actual connector policy, make pre-commit use the same local tool environment, and obtain a clean full test run. Then validate one real app/provider flow and worker recovery before enabling any sandbox-dependent connector.

### 26. What role did AI coding assistants play?

The repository defines phase acceptance checklists and a completion protocol that require evidence and stop before the next phase. It does not record a detailed Copilot incident history or track a `.github/copilot-instructions.md`, so I would not claim specific stalls, account changes, or solved context-limit incidents as repository facts.

### 27. How do you measure GreenLit's own accuracy?

Currently there are unit/integration tests for metric behavior, known-value tests for statistics, and a calibration calculation. A proper platform-level accuracy study still needs human labels and injected defects to measure judge agreement, defect precision/recall, and verdict agreement.

### 28. Does a GO verdict prove the application is safe?

No. It means the evaluated run met its configured criteria on the available data and instrumentation. Coverage, metric validity, live-provider behavior, and untested failure modes remain important.
