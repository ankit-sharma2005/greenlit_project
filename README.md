# GreenLit

Pre-launch testing and evaluation for LLM-powered applications. GreenLit tests the
**application** — its prompt, retrieval, tools and guardrails — and combines quality,
safety and operational checks into one decision: **GO / REVIEW / NO-GO**, with evidence,
a safety section, the judge that scored it, and an exportable report.

## What works today

- **Accounts and sessions:** Argon2id passwords, httpOnly cookie sessions with rotating
  refresh tokens, roles (`admin`, `member`, `reviewer`) and an append-only audit log.
  The first account to register becomes the admin.
- **Providers:** Ollama and any OpenAI-compatible endpoint, with a connection test,
  encrypted keys and rate limits.
- **Datasets:** upload a CSV/JSON golden set (or have the model generate one), then
  approve a version. Every version stores a hash.
- **Runs:** three entry points (HTTP endpoint, prompt app, uploaded outputs), executed in
  a Celery worker with live progress and cancel. A run snapshots its settings, so
  changing a provider later never rewrites history.
- **Scoring:** criteria profiles with weights, thresholds and hard gates; metrics that
  were not measured are reported as **not instrumented**, never as zero.
- **Safety (spec 8.3):** a versioned built-in attack set (44 cases across five
  categories, with a planted canary) and 26 harmless prompts, scored as
  `attack_resisted` and `over_refusal`. A leaked marker or a missing refusal is a hard
  NO-GO, and the result appears as its own section.
- **Judge (spec 8.2):** a saved judge profile grades the answers at temperature 0 and
  stores its model, rubric version and prompt-template hash; unavailable or unsure
  judges fall back to REVIEW instead of failing the run. A profile can cap how many
  cases it judges per run — the card then says "judged N of M cases" and the capped
  cases are excluded from the answer-quality average, not scored 0.
- **Reports (spec 8.5):** export any finished run as self-contained printable HTML, full
  JSON or case-level CSV. Request headers are redacted and no key is ever exported.
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

**Create the first account and it becomes the admin.** Every later account is a member;
changing a role is an admin API call for now (`PATCH /api/v1/users/{id}/role`, see
`/docs`) — there is no user-administration screen yet.

## Try the demo (no model needed)

The repo ships a college-helpdesk demo: the same app in a healthy and a broken flavour,
plus a 12-case golden dataset.

```bash
docker compose --profile demo up -d
```

Open the app, sign in, and press **Try the demo** on the New Test page. It runs the
golden set against both apps through the normal runs API and shows both verdicts side by
side: **GO** for the healthy app, **NO-GO** for the broken one with the weighted score
and the REVIEW threshold in the reason. Nothing is precomputed, and no provider is
involved.

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

## Connect an app

Everything starts on the **New Test** page. Pick an entry point, choose or generate a
dataset, then press **Start test**.

### HTTP endpoint

1. Entry point **HTTP endpoint**.
2. Target URL, for example `http://host.docker.internal:9000/chat`. Use
   `host.docker.internal` for a service on your own machine when the API runs in Docker,
   or the container name when it runs alongside it.
3. Tick **This app runs on my computer** for a local or private target. Only do that for
   targets you trust.
4. GreenLit probes the endpoint once to detect the request/response shape (method, body
   template, answer path, context path) and shows what it found. Adjust it if the guess
   is wrong.
5. Choose an approved dataset version, or leave it empty to have the model write cases.

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

The script creates a **disposable** stack and drops it afterwards, so it never restarts or
rebuilds the docker stack you use in the browser:

- Postgres + Redis run in their own Compose project (`greenlit-e2e`) on ports 5536/6482
  with a fresh volume — the e2e database is empty every run, so the first registered user
  is asserted to be `admin` on that clean database;
- the API (8103), a solo Celery worker and the Vite dev server (5277) start as local
  processes and are killed on exit;
- two demo helpdesk servers (healthy on 9501, broken on 9502) start the same way, since
  the disposable stack runs the API on the host and "Try the demo" needs somewhere to
  point;
- Playwright runs the whole suite in `frontend/tests` (`e2e-admin`, `e2e-baseline`,
  `e2e-calibration`, `e2e-demo`, `e2e-judge`, `e2e-prompt-app`, `e2e-report`,
  `e2e-safety`, `e2e-setup-audit`, `e2e-upload-outputs`) against
  `http://localhost:5277` (`E2E_BASE_URL`), then tears the project down with
  `docker compose down -v`.

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

```bash
API=http://localhost:8003
JAR=$(mktemp)

# 1. Sign in (register first on a fresh database).
curl -sS -c "$JAR" -H 'Content-Type: application/json' \
  -d '{"email":"ci@example.com","password":"correct horse battery"}' \
  "$API/api/v1/auth/login"

# 2. Start a test. Send `csv` (question,answer columns) or `dataset_id` to skip generation.
RUN=$(curl -sS -b "$JAR" -H 'Content-Type: application/json' \
  -d '{"entry_point":"http_endpoint","target":"http://localhost:9000/chat","tests":["quality","operations"],"csv":"question,answer\nHow do I reset my password?,Use the reset link on the sign-in page.\n"}' \
  "$API/api/v1/quick-test" | python -c 'import json,sys; print(json.load(sys.stdin)["run"]["id"])')

# 3. Poll until the worker finishes (live counters: /api/v1/runs/$RUN/progress).
for _ in $(seq 1 120); do
  curl -sS -b "$JAR" "$API/api/v1/runs/$RUN" > /tmp/greenlit-run.json
  grep -qE '"state":"(completed|cancelled|failed)"' /tmp/greenlit-run.json && break
  sleep 1
done

# 4. Fail the pipeline on anything but GO, and keep the report as an artifact.
python -c 'import json,sys; run=json.load(open("/tmp/greenlit-run.json")); print(run["verdict"], run["score"], run["verdict_reason"]); sys.exit(0 if run["verdict"] == "GO" else 1)'
curl -sS -b "$JAR" "$API/api/v1/runs/$RUN/report?format=html" -o greenlit-report.html
```

## Repository layout

```
backend/    FastAPI app, SQLAlchemy, Alembic migrations, worker, tests
frontend/   React + TypeScript + Vite UI, Vitest components, Playwright suite
demo/       Shipped demo dataset (the demo app itself lives in backend/app/demo_server.py)
docs/       Documentation and brand assets
scripts/    Developer utilities (brand asset generation, the disposable e2e stack)
```

See [HANDOVER.md](HANDOVER.md) for the architecture, how the tests are organised and the
known limitations.

## Brand assets

The logo mark and favicons are generated by `scripts/generate_brand_assets.py`
(Pillow). See [DECISIONS.md](DECISIONS.md) for why they are generated rather than copied.

![GreenLit](docs/greenlit-logo.png)

## Decisions

Product and engineering decisions are recorded in [DECISIONS.md](DECISIONS.md).
