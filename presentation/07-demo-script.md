# 10-minute demo script

## Demo truth before starting

The repository does not provide a confirmed seeded login, a database-backed demo workspace, a bundled sample app, or a seeded demo website. `scripts/seed_demo.py` writes a static JSON scenario summary. Do not claim it populated the live app. Create a local account through signup, and use a project/provider/test app only if they are actually available in the environment.

## Setup before the clock

1. From the repository root, start the local stack:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

2. Confirm the available health endpoints:

   ```powershell
   Invoke-RestMethod http://localhost:8000/healthz
   Invoke-RestMethod http://localhost:8000/readyz
   ```

3. Open the web app at `http://localhost:5173` and API docs at `http://localhost:8000/docs`.
4. Have a reachable test HTTP endpoint and a provider configured through the UI if you intend to show a real evaluation. Do not use production data or expose a credential during the demo.
5. No seeded account names or passwords are documented. Use an account created through `/signup`; do not invent a demo login.

## Timed walkthrough

| Time | Action | What to say | Expected / honest result |
|---|---|---|---|
| 0:00–1:00 | Show the landing page at `http://localhost:5173`. Toggle dark/light if available. | “GreenLit is for application readiness, not just model rankings.” | Landing and theme toggle are in `frontend/src/App.tsx`. Do not call the theme check an accessibility audit. |
| 1:00–2:00 | Open `/docs`; show `/healthz` and `/readyz`. | “The API exposes health and database readiness separately.” | Historically documented responses are `{"status":"ok"}` and `{"status":"ready"}`. If current endpoints fail, stop the live demo and use the code/docs fallback. |
| 2:00–3:00 | Sign up at `http://localhost:5173/signup` with a throwaway local email; then enter `/workspace`. | “Signup creates the first workspace and the app uses an in-memory access token plus a refresh cookie.” | There is no repository-provided seeded account. Confirm signup actually succeeds before proceeding. |
| 3:00–4:00 | In the workspace, show the entry-point dropdown. | “The registry has 13 connector types, but a listed type is not necessarily runnable.” | Point out the clear disabled reasons for Python, sandbox, Website URL, and MCP types. Do not click a gated type expecting success. |
| 4:00–5:00 | If available, create a project and select an implemented type such as HTTP endpoint or Prompt App. | “The connector test is meant to verify the selected settings before they are saved.” | The live test depends on a reachable endpoint/provider. If absent, show the validation contract in API docs/source instead. |
| 5:00–6:00 | Open Dataset Studio. Upload only a small safe test dataset if that UI is available. | “Golden examples are approved and versioned before they should count as test cases.” | The code handles CSV/JSON/JSONL/XLSX. Do not claim generated embedding deduplication or a production-quality synthetic-data pipeline. |
| 6:00–7:00 | If a real supported connector and provider are configured, run the approved dataset and inspect progress. | “Each example is persisted independently, so item failures can be surfaced.” | Do not simulate a provider response. If the run cannot execute, switch to the tests and explain that provider tests are mocked. |
| 7:00–8:00 | Show a real run report/trace only if one was successfully produced; otherwise show the metric contract from API docs. | “Missing trace fields are reported as not instrumented, rather than made up.” | The UI may not expose the entire spec's results/trace screens. Label an unavailable screen rather than implying it exists. |
| 8:00–9:00 | Explain hard gates and baseline regression using `backend/app/services/verdicts.py` and `comparison.py`, or visible API responses if present. | “A hard gate can force NO_GO; a later run on the same dataset can be compared to the baseline.” | Show stored run evidence if available. Avoid claiming a live GitHub Actions workflow. |
| 9:00–10:00 | Show `scripts/seed_demo.py` source or the generated JSON if prepared earlier. | “This file demonstrates the scenario labels and expected mapping.” | Explicitly state it is static JSON, not a seeded project or live app. Close with known gaps and the current test summary: 76 passed, 4 failed in the latest recorded full run. |

## Fallback plan

- **Docker unavailable:** show the architecture Mermaid diagram and the Compose file; state clearly that no live service is running.
- **API or web container unavailable:** use the health/readiness routes and relevant source/test files as a code walkthrough; do not describe it as a live demo.
- **No real provider credential:** skip live LLM execution. Explain the gateway and show the mocked provider tests, labeled as mocked.
- **No sample app/connector:** show the registry and explain that unsupported types are intentionally rejected. Do not construct a fake trace.
- **Seed request:** use only the static scenario mapping in `scripts/seed_demo.py`; do not tell the audience it created a demo account or database state.
