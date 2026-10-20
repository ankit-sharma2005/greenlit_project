# GreenLit presentation pack

## Five-line project summary

1. GreenLit is a local pre-launch evaluation platform for LLM-powered applications.
2. It evaluates an application against a repeatable dataset, not a model leaderboard.
3. It combines trace-aware metrics, configurable launch criteria, safety checks, and regression comparisons.
4. The backend is FastAPI/Python; the frontend is React/TypeScript; Docker Compose runs the local services.
5. The project is substantially implemented, but the audit records known gaps and the latest full test run has failures.

## Files in this folder

| File | How to use it |
|---|---|
| [01-project-overview.md](01-project-overview.md) | Introduce the problem, product, users, and outputs in non-technical language. |
| [02-architecture.md](02-architecture.md) | Explain system components, connector/trace contracts, metrics, verdicts, and regression flow. Mermaid source files are in `assets/`. |
| [03-technology-stack.md](03-technology-stack.md) | Present technologies, repository-pinned versions, reasons, and locations. |
| [04-features-by-phase.md](04-features-by-phase.md) | Compare the ten phase records with their code and test evidence. |
| [05-challenges-and-solutions.md](05-challenges-and-solutions.md) | Use the implementation stories for the viva; unsupported personal anecdotes are explicitly marked. |
| [06-results-and-limitations.md](06-results-and-limitations.md) | Use this for measured outcomes, current validation status, gaps, and future work. |
| [07-demo-script.md](07-demo-script.md) | Follow the timed local demo and its no-provider/no-stack fallback. |
| [08-viva-questions.md](08-viva-questions.md) | Rehearse short, evidence-based answers to likely questions. |
| [09-slides-outline.md](09-slides-outline.md) | Use as a 15-slide Marp-compatible starting outline. |
| [10-code-map.md](10-code-map.md) | Navigate the tracked source files, tests, migrations, and three request flows. |
| [assets/architecture.mmd](assets/architecture.mmd) | Standalone Mermaid component diagram. |
| [assets/evaluation-flow.mmd](assets/evaluation-flow.mmd) | Standalone Mermaid evaluation-flow diagram. |

## Screenshots to capture manually

No screenshots or binary assets are included. Capture only what is actually available in the running build:

- Landing page: show the workflow summary and the dark theme.
- Landing page: show the light theme and the theme toggle.
- Signup or login page: show the form and keyboard focus order.
- Workspace page: show the entry-point list and the visible disabled reasons for unsupported types.
- Dataset Studio: show a real upload preview, validation result, and approval state if populated data is available.
- Run/result view: show a populated run, its verdict, and a trace only if the screen is available and the run completed.
- API docs at `http://localhost:8000/docs`: show `/healthz`, `/readyz`, and the available API routes.
- Regression example: show the source-backed GOOD/BROKEN/REGRESSING scenario mapping; label it illustrative unless a real stored run is shown.

If a screen or populated state is not available in the current build, do not substitute a mock-up and describe it as a live feature. The docs and test results in this pack distinguish implemented behavior from contract-only, mocked, disabled, or unverified behavior.
