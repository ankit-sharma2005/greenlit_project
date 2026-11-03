# GreenLit

Pre-launch testing and evaluation for LLM-powered applications. GreenLit tests the
**application** — its prompt, retrieval, tools and guardrails — and combines quality,
safety and operational checks into one decision: **GO / REVIEW / NO-GO**, with evidence,
a safety section, the judge that scored it, and an exportable report.

## What works today

- **Accounts and sessions:** Argon2id passwords, httpOnly cookie sessions with rotating
  refresh tokens (access 15 min, refresh 14 days), roles (`admin`, `member`, `reviewer`) and
  an append-only audit log. A 401 triggers one silent refresh and one replay of the request;
  ten parallel 401s share a single refresh, and the refresh runs inside
  `navigator.locks.request("greenlit-refresh")` when the browser has Web Locks. If the
  14-day refresh cookie is missing or revoked the user is signed out and sent to `/login`
  with "Your session expired. Please sign in again." Each claim is tested: retry-once,
  one refresh for parallel 401s, no loop on a second 401, auth endpoints exempt, and no
  sign-out on a refresh 5xx or network error in `frontend/src/lib/api.test.ts`; one expiry
  signal, the Web Locks path and its fallbacks in `frontend/src/lib/session.test.ts`; the
  mount-time refresh and the anonymous fallback in `frontend/src/auth/AuthProvider.test.tsx`.
  Not proven: browsers without Web Locks beyond the stubbed fallback, idle sessions longer
  than 14 days, and the backend's refresh-token reuse detection (unchanged here). The first
  account to register becomes the admin.
- **Providers:** Ollama and any OpenAI-compatible endpoint, with a connection test,
  encrypted keys and rate limits.
- **Datasets:** upload a CSV/JSON golden set, then approve a version. Dataset Studio can
  also generate draft cases from pasted text or PDF/TXT/MD sources (up to 5 MB); source
  text is split into at most 20 passages and each generated case stores its supporting
  passage as `reference_context`. Review and approve generated versions before running them.
  Every version stores a hash.
- **Runs:** three entry points (HTTP endpoint, prompt app, uploaded outputs), executed in
  a Celery worker with live progress and cancel. A run snapshots its settings, so
  changing a provider later never rewrites history.
- **Scoring:** criteria profiles with weights, thresholds and hard gates; metrics that
  were not measured are reported as **not instrumented**, never as zero. **Settings →
  Criteria** shows the engine's real numbers read-only: a No-Go / Review / Go scale built
  from the 0.60 and 0.80 thresholds, every metric with its weight, group and hard-gate
  bar, the five decision rules in the order they run, and the not-instrumented rule.
  Editing criteria is not supported yet.
- **Operations:** every run also reports p50/p95 latency, error and timeout rates and
  token totals, on the verdict card and in the exports. An estimate of cost is shown only
  when token prices are configured for the provider; otherwise it says "not configured".
  Values nobody reported stay **null** rather than becoming zero. A timeout is recognised
  from the failure kind the connector and gateway record (a real slow server is covered by
  a test), not guessed from error text; runs recorded before that fall back to the text.
- **Safety (spec 8.3):** a versioned built-in attack set (44 cases across five
  categories, with a planted canary) and 26 harmless prompts, scored as
  `attack_resisted` and `over_refusal`. A leaked marker or a missing refusal is a hard
  NO-GO, and the result appears as its own section. **Settings → Safety** shows exactly
  what a run sends: every case with its category, severity, prompt and expected
  behaviour, the category counts and the canary rule in words; the marker shown there
  (`CANARY-7F3A`) is a synthetic test marker, not a secret. Selecting a subset of sets
  is supported by the API (`safety_sets` on a run, catalogue at `GET /api/v1/safety/sets`)
  but has no UI yet — the panel is read-only.
- **Judge (spec 8.2):** a saved judge profile grades the answers at temperature 0 and
  stores its model, rubric version and prompt-template hash; unavailable or unsure
  judges fall back to REVIEW instead of failing the run. A profile can cap how many
  cases it judges per run — the card then says "judged N of M cases" and the capped
  cases are excluded from the answer-quality average, not scored 0.
- **Reports (spec 8.5):** export any finished run as self-contained printable HTML, full
  JSON or case-level CSV. Request headers are redacted and no key is ever exported.
  When the target was not the user's own app, the report names the recorded permission
  and its reference.
- **A real company chatbot (HTTP endpoint):** the connector is polite by default — one
  request at a time, at least 500 ms apart, and a busy target (429, 502, 503, 504) is
  retried three times with exponential backoff plus jitter, honouring `Retry-After`
  (seconds or an HTTP date, capped at 60 s). Set retries to 0 to send each request once.
  A response that still fails keeps its structured error and still trips the run's
  circuit breaker. A case that needed retries is still a success: its latency is the
  final attempt alone, `retry_count` and `waited_ms` are stored and exported beside it,
  and Operations reports how many cases were retried. A case has a 150 s budget, so a
  slow target cannot hold a worker, and Cancel interrupts a wait immediately.
- **Streamed answers:** a target that streams is understood: `sse`, `ndjson` or plain
  `text`, plus the current single-JSON-body mode. Streamed pieces are joined into one
  answer (an explicit JSON path, or auto-detected OpenAI-style deltas and plain `data:`
  text), `[DONE]` and keepalive comments are ignored, the answer is capped at 100 KB,
  and both time to first byte and total latency are recorded.
- **Pasted cURL credentials:** a pasted `curl` brings its headers, cookies (`-b`),
  basic auth (`-u`) and body into the connector. Values are stored encrypted, the API
  returns only their names, exports and errors redact them, and the `Host` header is
  never imported (the URL decides the host, so the SSRF check still applies). A 401/403
  says the session may have expired and to paste a fresh cURL.
- **Permission to test:** a target that is not the user's own computer needs a ticked
  "I own this application or have permission to test it" (an unconfirmed run is a 422)
  plus an optional reference. Both are stored with the run, shown on the verdict card,
  in every export and in the audit log. Safety attack probes against such a target stay
  off unless a second checkbox repeats the permission explicitly.
- **Baselines and regression (spec 8.5):** set a completed run as the baseline for its
  dataset version; the next run is compared with it and shows **PASS / WARN / BLOCK** with
  the metric deltas and the cases that passed before and fail now, on the verdict card and
  in every export.
- **Human review (M7):** reviewers and admins get a queue of the cases the judge could not
  settle (unavailable, unsure, or a label that disagrees) and label them; the Calibration
  page reports raw agreement and Cohen's kappa, so a judge that always says "pass" cannot
  look accurate. Plain members can run tests but cannot label.
- **Setup and audit:** the New Test page lists the three things a first test needs with
  their real state, and Settings → Audit log is a real, paged, filterable admin view of the
  append-only event trail.

Anything still missing is visibly marked "soon" in the UI rather than faked.

## Quick start

Requirements: Docker Desktop (WSL2 on Windows) with Compose v2.

```bash
git clone <your-fork-url> greenlit
cd greenlit
cp .env.example .env          # optional; compose has working defaults
docker compose up --build
```

Then open:

| Service  | URL                        |
| -------- | -------------------------- |
| Web UI   | http://localhost:5177      |
| API      | http://localhost:8003      |
| API docs | http://localhost:8003/docs |

Host ports are configurable through `.env` without editing the compose file:
`WEB_PORT` (5177), `API_PORT` (8003), `POSTGRES_PORT` (5436), `REDIS_PORT` (6382).
Container ports stay 5173, 8000, 5432 and 6379. If you change `WEB_PORT` or `API_PORT`,
update `WEB_ORIGIN` (CORS) and `VITE_API_BASE_URL` to match.

Health checks: `GET /healthz` (liveness) and `GET /readyz` (Postgres + Redis readiness).

### Troubleshooting API connection errors

The browser must reach the API through its **host** URL, normally
`http://localhost:8003`; `api:8000` is only for traffic between Compose containers.
The web container receives this value through `VITE_API_BASE_URL`, while API CORS allows
the web origin in `WEB_ORIGIN` (normally `http://localhost:5177`). If you change host ports,
keep those two variables aligned. Network errors in the UI now include the exact API URL
and endpoint it tried.

If that URL is correct but the API is unreachable, check `docker compose ps`,
`docker compose logs api --tail 80` and `http://localhost:8003/readyz`. A missing runtime
package can stop Uvicorn while the frontend reports a network error; for example, the API's
key-encryption imports require `cryptography` to be installed in the image. Rebuild and
recreate the API after changing runtime dependencies:
`docker compose up --build -d --no-deps api`. Do not remove the database or Redis volumes.

**Create the first account and it becomes the admin.** Every later account is a member;
changing a role is an admin API call for now (`PATCH /api/v1/users/{id}/role`, see
`/docs`) — there is no user-administration screen yet.

## Before you deploy or share this repo

- **Change the default secret key and database password in `.env` first.** The compose
  defaults (`APP_SECRET_KEY`, `POSTGRES_PASSWORD`) are public in this repo; `APP_SECRET_KEY`
  encrypts provider keys at rest, so a known value means readable keys.
- **Never commit `.env`, cookie jars, tokens or API keys.** `.gitignore` already ignores
  `.env`, `.env.*` (except `.env.example`), `*.cookies.txt` and `*.log`; check `git status`
  before you push and keep real credentials in the environment, not in the tree.
- **Free-tier model providers see what you send them.** Dataset generation, the prompt-app
  entry point and the judge all send prompts (and case text) to the provider you configure,
  and free tiers may train on it — do not paste private or customer data into a test set.
  Source files are treated as untrusted prompt data; scanned PDFs without selectable text
  are rejected rather than OCR'd.
- **One old dev session jar was committed once.** `cookies.txt` (added in commit `d953cff`,
  removed later) held expired local session tokens; the file is gone from the tree but still
  in that commit's history. If this repo is ever made public, rewrite the history with
  `git filter-repo --path cookies.txt --invert-paths`.

## Try the demo (no model needed)

The repo ships a college-helpdesk demo: the same app in a healthy and a broken flavour,
plus a 12-case golden dataset.

```bash
docker compose --profile demo up -d
```

Open the app, sign in, and press **Try the demo** on the New Test page. It runs the
golden set against both apps through the normal runs API and shows both verdicts side by
side: **GO** for the healthy app, **NO-GO** for the broken one with the weighted score
and the REVIEW threshold in the reason. The demo scores quality only, so it is not penalized
solely by the operations latency metric; very slow calls can still time out. Safety and
operations are available on normal runs.
Nothing is precomputed, and no provider is involved.

To see regression: open the healthy run in **Results**, press **Set as baseline**, then
run the broken app on the same dataset. Its verdict card reports **BLOCK** and names the
metric that dropped (`answer_match`).

## Add a model with Ollama

GreenLit needs a model for three things: generating a dataset if you do not upload one,
the prompt-app entry point, and the judge.

1. Install [Ollama](https://ollama.com) and pull a model: `ollama pull hermes3:8b`.
2. In GreenLit open **Settings → Providers and models**.
3. Press **Use Ollama defaults**: kind `ollama`, base URL
   `http://host.docker.internal:11434/v1`, model `hermes3:8b`. `host.docker.internal` is
   how the API container reaches Ollama on your machine; if you run the API outside
   Docker, use `http://localhost:11434/v1` instead.
4. Press **Add provider**, then **Test connection**. A green _healthy_ badge means the
   gateway reached the model. If it fails, check that Ollama is running and that the
   model name matches exactly.

OpenAI, Groq and any other OpenAI-compatible endpoint work the same way: choose
`openai-compatible`, set the base URL and paste the API key. Keys are encrypted at rest
and never returned by the API.

The provider form also takes **Price per 1K input tokens** and **Price per 1K output
tokens**. They are optional and only feed the rough cost estimate on the verdict; leave
them empty (now or when editing) and the estimate says "not configured" instead of
inventing a number. When they are set, the Operations block shows the arithmetic behind
the estimate (tokens × price) so it is never a bare total.

## Connect an app

Everything starts on the **New Test** page. Pick an entry point, choose or generate a
dataset, then press **Start test**.

### HTTP endpoint

1. Entry point **HTTP endpoint**.
2. Target URL, for example `http://host.docker.internal:9000/chat`. Use
   `host.docker.internal` for a service on your own machine when the API runs in Docker,
   or the container name when it runs alongside it.
3. Tick **This app runs on my computer** for a local or private target. Only do that for
   targets you trust. For any other target, tick **I own this application or have
   permission to test it** (and optionally say who gave it); without that the run is
   refused with a 422. Security attack probes against such a target need the second
   checkbox that repeats the permission wording, and otherwise stay off.
4. For a chatbot that needs a session, press **Paste cURL** and paste the full command:
   its headers, cookies and token are imported encrypted and only their names are shown.
5. Under **Advanced connector options**, set the polite rate (defaults: 1 concurrent
   request, 500 ms apart, 3 retries) and how the app answers — one JSON body, `sse`,
   `ndjson` or plain `text` — plus the JSON path inside each event when it is not the
   OpenAI-style delta.
6. GreenLit probes the endpoint once to detect the request/response shape (method, body
   template, answer path, context path) and shows what it found. Adjust it if the guess
   is wrong.
7. Choose an approved dataset version, or leave it empty to have the model write cases.

### Prompt app

Entry point **Prompt app** tests a system prompt against a saved provider instead of a
URL. Type the system prompt, pick the provider and model (the model defaults from the
provider), and optionally a temperature. This is the fastest way to compare two prompt
variants.

### Upload outputs

Entry point **Upload outputs** scores answers your app already produced. Drop a CSV or
JSON file with an `id`, `input` and `output` column; `retrieved_context`, `latency_ms`,
`tokens_in` and `tokens_out` are optional. Only `input` and `output` are required, and
GreenLit auto-detects the columns (with a mapping view when detection is ambiguous).
Cases with no matching output fail with a clear reason instead of scoring zero, and
missing optional columns are reported as not instrumented.

## Read the verdict

A finished run shows the verdict word, the weighted score, the reason rule that produced
it, the metric table, the cases that failed, the safety section, the judge's model and
rubric version, and — when a baseline exists — the regression status with its deltas.
Three **Export** buttons download the same result as HTML (printable and self-contained),
JSON (the full result) or CSV (one row per case). The export never contains a secret:
header values are redacted and provider keys never enter it.

## Quality checks

```bash
# backend
cd backend && ruff check . && ruff format --check . && mypy && pytest

# frontend
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

### End-to-end tests

```bash
bash scripts/run-e2e.sh
```

The script creates a uniquely named **disposable** stack and stops its containers afterwards,
so it never restarts or rebuilds the Docker stack you use in the browser. It preserves the
e2e stack's named volumes (it never uses `down -v`); each invocation gets a new Compose
project and therefore a fresh database:

- Postgres + Redis run in their own uniquely named Compose project (`greenlit-e2e-*`) on
  ports 5536/6482 with a fresh volume — the e2e database is empty every run, so the first registered user
  is asserted to be `admin` on that clean database;
- the API (8103), a solo Celery worker and the Vite dev server (5277) start as local
  processes and are killed on exit;
- two demo helpdesk servers (healthy on 9501, broken on 9502) start the same way, since
  the disposable stack runs the API on the host and "Try the demo" needs somewhere to
  point;
- Playwright runs the whole suite in `frontend/tests` (`e2e-admin`, `e2e-baseline`,
  `e2e-calibration`, `e2e-dataset-generation`, `e2e-demo`, `e2e-judge`, `e2e-prompt-app`,
  `e2e-report`, `e2e-safety`, `e2e-setup-audit`, `e2e-upload-outputs`) against
  `http://localhost:5277` (`E2E_BASE_URL`), then stops only that project with
  `docker compose down`; its volume is preserved. The last full run from a clean stack
  passed every test: `18 passed (9.8m)`, exit code 0.

Because the whole suite takes longer than one command on a slow machine, a single spec can
be run on the same disposable stack:

```bash
bash scripts/run-e2e.sh tests/e2e-baseline.spec.ts
```

To run the suite against an already-running dev stack instead:

```bash
cd frontend && npm run e2e   # defaults to http://localhost:5177
```

CI runs the same commands on every push (see `.github/workflows/ci.yml`).

## Run GreenLit in CI

Everything works through the API alone. `POST /api/v1/quick-test` creates what a test needs
(connector settings, dataset, approved version and the run) and returns the run id at once;
the Celery worker executes the cases and `GET /api/v1/runs/{id}` returns the stored verdict.
The standard-library runner logs in with `GREENLIT_EMAIL` and `GREENLIT_PASSWORD`, polls the
run to completion, and reports the verdict, weighted score, and failed instrumented metrics.
Exit codes are 0 for GO, 1 for NO_GO, 2 for REVIEW, and 3 for request errors or timeouts;
`--fail-on review` maps REVIEW to exit 1. A copyable, inactive GitHub Actions example is at
`.github/workflows/greenlit-example.yml.disabled`.

```bash
export GREENLIT_API_URL=http://localhost:8003
export GREENLIT_EMAIL=ci@example.com
export GREENLIT_PASSWORD='use-a-provisioned-ci-password'

python scripts/greenlit_ci.py \
  --entry-point http_endpoint \
  --target http://host.docker.internal:9301/chat \
  --csv-file demo/helpdesk_golden.csv \
  --tests quality \
  --allow-private-targets \
  --timeout 180
```

The example assumes the API user has already been registered and the demo profile is
running (`docker compose --profile demo up -d`). Use `--dataset-id` instead of `--csv-file`
to select an existing approved dataset. Only enable `--allow-private-targets` for a target
you trust. To use the runner against your own application, replace the target and dataset.

## Testing a real company app

A first real test against somebody else's chatbot has its own hazards: an expiring
session, bot protection, redirects, TLS, a stream that stops halfway. The connector
reports each of those as its own structured failure instead of a crash or a wrong
score — a `403` challenge page is "blocked by the site", a cross-host redirect is
refused and named, an unreadable body says which paths were tried, and a stream that
stops early keeps its text marked incomplete so it is never scored as a whole answer.
Read [docs/REAL_WORLD_CHECKLIST.md](docs/REAL_WORLD_CHECKLIST.md) before the first
request: permission first, a test account, concurrency 1, attack probes off unless
written permission covers them, and never production customer data.

## Drive GreenLit from an MCP client

`mcp_server/` is a small stdio MCP server that lets an MCP client (Claude, Freebuff,
Copilot) read GreenLit through the same REST API: the project and its counts, a run's
state and case counts, the verdict and weights, the engine's criteria, and a run's report
as JSON, CSV or HTML. It is a thin client — no app imports, no database access, and it
never changes a decision rule or threshold. Responses are size-capped with a `truncated`
flag, and API failures come back as plain-language tool errors naming the HTTP status and
path.

`greenlit_start_run` exists only when `GREENLIT_MCP_ALLOW_START=1`, starts at most one run
every 10 seconds and refuses any target that is not on your own machine, because testing
somebody else's app needs the permission record this server never sets.

It signs in with `GREENLIT_EMAIL` and `GREENLIT_PASSWORD` like the CI runner does, so give
it a dedicated low-privilege account and never the admin one. Setup, the copy-paste client
config and the security rules are in [docs/MCP.md](docs/MCP.md).

## Repository layout

```
backend/    FastAPI app, SQLAlchemy, Alembic migrations, worker, tests
frontend/   React + TypeScript + Vite UI, Vitest components, Playwright suite
demo/       Shipped demo dataset (the demo app itself lives in backend/app/demo_server.py)
docs/       Documentation and brand assets (incl. MCP.md for the MCP client)
mcp_server/ stdio MCP server: a thin client over the REST API, with its own tests
scripts/    Developer utilities (brand assets, disposable e2e stack, CI runner)
```

See [HANDOVER.md](HANDOVER.md) for the architecture, how the tests are organised and the
known limitations.

## Brand assets

The logo mark and favicons are generated by `scripts/generate_brand_assets.py`
(Pillow). See [DECISIONS.md](DECISIONS.md) for why they are generated rather than copied.

![GreenLit](docs/greenlit-logo.png)

## Decisions

Product and engineering decisions are recorded in [DECISIONS.md](DECISIONS.md).
