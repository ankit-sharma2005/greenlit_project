ROLE
You are a principal engineer (backend, ML evals, security, product design).
Build "GreenLit": a production-grade, OFFLINE pre-launch evaluation platform
for LLM-powered APPLICATIONS (RAG, chatbot, agent, extraction workflow), not
for benchmarking raw models. Work phase by phase (Section 16). After each
phase follow the PHASE COMPLETION PROTOCOL (Section 17), then STOP and wait for
"proceed". Ask questions only if truly blocked; otherwise make sensible
assumptions and list them. Save this spec as docs/PROJECT_SPEC.md and re-read
it at the start of every phase.

QUALITY BAR
- No placeholders or TODO stubs in product code. Fake data only in the seed script.
- mypy strict, TypeScript strict, ruff, eslint, prettier, pre-commit.
- Every feature has tests. Every endpoint has typed, validated, documented I/O.
- UI must look like a premium SaaS product (Linear / Vercel / Langfuse level).
- Target deployment: LOCAL Docker Compose, ~5 users. Do not over-engineer for
  scale; do engineer for correctness, security and polish.

1. PURPOSE
Users connect an LLM application (a staging/test copy), build or upload a
golden dataset, define success criteria, run a repeatable eval suite, and get a
GO / NO_GO launch verdict. It must answer: Can this model/system do this task?
Is it good enough for production? Did prompt v2 beat v1 (statistically)? Is the
RAG answer grounded in retrieved context? Is the chatbot safe for real users?
Is latency and cost under control? Did my latest change cause a regression?
Evals are SYSTEMATIC (defined suites, no ad hoc prompts), REPEATABLE (same
suite re-runnable on any new version: prompt, model, chunking, retriever,
embedding), and CRITERIA-DRIVEN. "Good" is defined by the application's task,
not the model: the same criteria and golden dataset judge every candidate.
Criteria = HARD GATES (any failure => NO_GO, e.g. safety, JSON validity) +
SOFT SCORES (weighted thresholds).
Core workflow (model in code and as a UI stepper): define task/target -> define
success criteria -> build golden dataset -> choose eval methods -> run the app
on the dataset -> evaluate results -> analyze results -> if not good, improve
and re-run the SAME suite; else approve and deploy.
Failure points to evaluate:
 - Components: prompt, retriever, reranker, query rewriter, embedding model,
   vector database, output parser, tool selector, memory, guardrails, and
   whether the chosen LLM suits the task.
 - Workflows: RAG, multi-turn conversation, document extraction, agent loops.
 - Whole application: latency, token cost, error rate.
Offline means: evaluate a staging/test copy on a fixed dataset, with test keys
and fake or anonymized data, never real user traffic.

2. TECH STACK
Backend: Python 3.11+, FastAPI (async), SQLAlchemy 2.0 async + Alembic,
PostgreSQL, Pydantic v2, Celery + Redis, httpx, structlog, OpenAI Python SDK
(pointed at GitHub Models / Ollama), numpy/scipy, Playwright (URL discovery),
pytest + pytest-asyncio.
Frontend: React 18 + TypeScript + Vite, Tailwind, shadcn/ui (Radix), Framer
Motion, TanStack Query + Table, React Router, Zustand, React Hook Form + Zod,
Recharts (+ d3/visx for the trace waterfall), cmdk, Sonner, lucide-react.
Infra: Docker Compose (api, worker, beat, redis, postgres, web), Makefile,
GitHub Actions CI (lint, types, tests, build). Single `docker compose up` must work.

3. LLM PROVIDER LAYER (provider-agnostic; GitHub Models + Ollama by default)
GreenLit makes all of its own LLM and embedding calls (judges, dataset
generation, built-in sample apps) through ONE internal `LLMGateway` service
using the OpenAI Python SDK against any OpenAI-compatible endpoint. No gateway
product is required.
- Providers configured in Settings (and env):
  * GITHUB_MODELS: base URL https://models.github.ai/inference, token from
    GITHUB_TOKEN (a PAT with models access). Free tier, strict rate limits.
  * OLLAMA: base URL http://localhost:11434/v1, no key. Local, no daily cap.
  * Any other OpenAI-compatible endpoint (base URL + key) as a custom provider.
- Model lists load from each provider's models endpoint where available
  (cached) with manual-entry fallback. Dropdowns show "provider / model".
- Per-provider rate limiter: configurable RPM, RPD and max input/output tokens
  (conservative defaults for GitHub Models free tier). Requests queue instead
  of failing; show queue length and estimated time. When a daily quota is
  exhausted, runs PAUSE and RESUME automatically (idempotent, resumable) and
  the UI shows "waiting for quota".
- Fallback chain per role (app model, dev judge, final judge, generator,
  embeddings), e.g. GitHub Models -> Ollama. Record the provider and model
  ACTUALLY used on every Trace and Score.
- Reliability: backoff + jitter on 429/5xx, timeouts, per-run concurrency
  limits, circuit breaker, request ids, structured JSON output with schema
  validation and auto-repair retry, truncation handling for token caps.
- Embeddings: provider endpoint if available, else local sentence-transformers.
- Cost = tokens x configurable price table (default 0 for free providers); show
  "cost unknown" instead of fabricating numbers.
- Judge call cache keyed by hash(rubric_version, provider, model, input).
- Settings: "Test connection" per provider, latency check, quota usage meter,
  health badge in the header.

4. JUDGE PROFILES AND FINAL REPORT MODE
- Judge Profiles per project: DEV JUDGE (fast, cheap/free model for iteration)
  and FINAL JUDGE (strongest available free model for report numbers). Optional
  secondary judge for agreement checks.
- "Final Report mode": one click re-scores a completed run (reusing stored
  traces, without re-running the app) with the Final Judge. Store both score
  sets; show dev-vs-final agreement; reports are stamped "Judged by <model>,
  rubric vX, date". Warn if judge model == app model (self-preference bias).
- All rubric prompts versioned; temperature 0; structured JSON
  {score, reasoning, confidence}; dataset text is untrusted inside judge
  prompts (delimiters, guard against judge injection).
- Pairwise comparisons run both orderings to cancel position bias.

5. AUTHENTICATION AND SECURITY (5 users, local)
- Email + password (argon2id), email verification/reset via console mailer in
  dev (SMTP optional via env). OAuth optional behind a feature flag (off).
- JWT access (15 min) + rotating refresh token in httpOnly SameSite cookie,
  reuse detection, logout everywhere, active-sessions page.
- Workspaces with RBAC: Owner, Admin, Engineer, Reviewer (human eval only),
  Viewer. Enforced via dependencies; every query workspace-scoped.
- Personal API tokens (hashed, scoped, shown once) so CI can trigger runs.
- Secrets (connector credentials, provider tokens) encrypted at rest (Fernet,
  key from env). Never log secrets; redact PII in logs.
- Login rate limiting, CORS allowlist, security headers, CSRF for cookie flows,
  upload validation (type/size), SSRF protection for outbound connectors
  (block private ranges unless an Admin explicitly allows localhost/private
  targets, e.g. host.docker.internal for a local app).
- Audit log of create/edit/run/override/approve actions and every
  "authorized to test" confirmation (Admin view).
- Sandbox rule: any imported code, container, or browser session runs isolated
  (no host access, network allowlist, CPU/memory/time limits).

6. BACKEND ARCHITECTURE
Layers: api -> services -> repositories -> domain (pure metrics, decision
engine, stats). Dependency injection, no business logic in routers. Alembic
migrations, UUID ids, timestamps, optimistic concurrency on editable rows.
Uniform error envelope {error:{code,message,details,request_id}}, cursor
pagination, filtering/sorting, idempotency keys for run creation. /healthz,
/readyz, /metrics (Prometheus), JSON structured logs with request/run/trace
ids. Server-Sent Events for live run progress.
Celery jobs (run orchestration, per-item execution, scoring, dataset
generation, report export, load test, discovery, scheduled re-evals) must be
idempotent, resumable after a crash, cancellable, retried with backoff,
concurrency-bounded, with per-item status/error capture. One failed item never
kills a run.
Reproducibility: each EvalRun snapshots app-version config, connector profile
(entry point type + settings), dataset-version hash, criteria version,
metric/rubric versions, judge models, seeds. "Re-run this suite on a new
version" reuses the snapshot.
Core entities: User, Workspace, Membership, ApiToken, AuditLog, Project,
AppVersion (with parent version), ConnectorProfile (entry_point_type enum +
validated JSON settings + encrypted credentials + access_level), Dataset,
DatasetVersion (immutable, content-hashed), DatasetItem (input or conversation
turns, reference answer, reference contexts, expected tool calls, tags,
category, provenance, status, regression-critical flag), CriteriaProfile
(versioned), EvalSuite, EvalRun, Trace, Score, HumanReview, ReviewQueueItem,
Baseline, ReferenceDocument, AttackPack, AttackCase, DiscoverySession.

7. ENTRY POINTS: HOW GREENLIT ACCESSES THE APP UNDER TEST
ENTRY POINT = the single place GreenLit sends an input and receives an output.
Minimum contract: input (question or conversation history) -> output. Anything
extra (retrieved chunks, tool calls, tokens) is optional and unlocks
component-level metrics.

7.1 ENTRY POINT DROPDOWN (required UI + API)
The "Connect your app" wizard starts with a prominent searchable dropdown
labelled "Entry point type" (shadcn Select/Combobox with icon, one-line
description and an access-level badge, black-box or white-box, per option).
Options (enum `EntryPointType`):
  1. HTTP_ENDPOINT        - "App running at a URL (staging or localhost)"
  2. PYTHON_FUNCTION      - "A Python function (module:function)"
  3. PYTHON_SDK_TRACED    - "Python app instrumented with greenlit-trace"
  4. PROMPT_APP           - "No-code: system prompt + model"
  5. BUILTIN_RAG_APP      - "Built-in RAG app (upload documents)"
  6. BUILTIN_AGENT_APP    - "Built-in tool-using agent"
  7. DOCKER_IMAGE         - "Docker image or compose file"
  8. GIT_REPO             - "Git repository + entrypoint"
  9. CLI_COMMAND          - "Command-line program with {{input}} template"
 10. PROXY_MODE           - "Point your app's LLM base URL at GreenLit"
 11. UPLOAD_OUTPUTS       - "Upload inputs/outputs you already generated"
 12. WEBSITE_URL          - "Website URL: discover the embedded chatbot"
 13. MCP_SERVER           - "App or agent exposed over MCP"
Behaviour:
 - Selecting a type renders a DYNAMIC FORM (react-hook-form + Zod; schema per
   type shared with the backend via a Pydantic discriminated union) showing
   only that type's fields, with inline help, examples and validation.
 - Below the form: (a) "Input/Output mapping" (which field holds the input and
   which the output; JSONPath/regex or column names), (b) optional mapping for
   retrieved chunks, tool calls, token usage, citations, (c) "Test call"
   button that sends a sample input and shows the parsed trace, raw response,
   latency, and which trace fields were detected vs missing, (d) "Where does my
   app run?" helper with presets: "Deployed staging server", "On my laptop
   (localhost)", "Inside Docker", "Not reachable", which pre-select sensible
   entry point types and explain host.docker.internal / shared Docker network.
 - Save is blocked until Test call succeeds (Admin override with a warning).
 - The chosen type, settings, access level and a content hash are stored on the
   ConnectorProfile and snapshotted into every EvalRun; changing the entry
   point creates a new AppVersion.
 - Backend exposes GET /api/v1/entry-point-types (label, description, access
   level, JSON Schema of settings) so the UI form is generated from it, plus
   POST /api/v1/connectors/test-call.

7.2 Fields per entry point type
 - HTTP_ENDPOINT: URL, method, headers/auth (secret fields encrypted), request
   body template with variables ({{input}}, {{history}}, {{context}}), response
   mappings (JSONPath), streaming (SSE) toggle, timeout, retries, rate limit.
   Preset "OpenAI-compatible chat endpoint".
 - PYTHON_FUNCTION: module path + function name, uploaded source or mounted
   path, requirements, env vars; runs in a sandbox subprocess.
 - PYTHON_SDK_TRACED: same plus snippet generator for the `greenlit-trace`
   decorator/context manager that emits steps (rewritten_query,
   retrieved_chunks, reranked_chunks, prompt_sent, raw_llm_output,
   parsed_output, tool_calls, memory_state, guardrail_events).
 - PROMPT_APP: system prompt, provider/model (from LLMGateway), temperature,
   optional output JSON schema.
 - BUILTIN_RAG_APP: document upload, chunk size/overlap, embedding model,
   top-k, reranker, prompt, model, vector store (Chroma or FAISS).
 - BUILTIN_AGENT_APP: tool definitions (JSON schema), mock tool backends,
   model, max steps.
 - DOCKER_IMAGE: image name or compose file, exposed port, route, health check,
   env vars, resource limits; started in an isolated sandbox network and torn
   down after the run.
 - GIT_REPO: repo URL, branch, entrypoint (e.g. app.py:answer), install
   command, env vars; cloned and run in a sandbox.
 - CLI_COMMAND: command template such as `python run.py --q "{{input}}"`,
   working directory, timeout, how to read output (stdout/JSON file).
 - PROXY_MODE: GreenLit shows a per-project OpenAI-compatible base URL + key;
   the app under test points its LLM base URL there; GreenLit forwards to the
   configured provider and records prompts, responses, tokens, latency as
   traces tagged to the active run.
 - UPLOAD_OUTPUTS: CSV/JSON/JSONL with inputs, outputs, optional retrieved
   contexts, tool calls, latency, tokens; column-mapping UI and validation;
   GreenLit only scores them.
 - WEBSITE_URL (stretch, black-box): see 7.4.
 - MCP_SERVER: server URL/command, tool name to call, argument mapping.

7.3 Standard trace and access levels
Every connector yields the same trace:
{ output, steps:{ rewritten_query?, retrieved_chunks?[{text,score,source}],
reranked_chunks?, prompt_sent?, raw_llm_output?, parsed_output?, tool_calls?
[{name,args,result,error}], memory_state?, guardrail_events? },
usage:{tokens_in,tokens_out}, latency_ms, model_used? }
Missing steps skip only the component metrics that need them; the UI marks them
"not instrumented" with instructions. Black-box types give end-to-end, safety,
latency and cost evals; white-box types also give component-level evals. Show
the access level on every app version and on the results page.

7.4 WEBSITE_URL discovery module
The user enters a website URL (staging/test site) and ticks "I own or am
authorized to test this site" (stored in the audit log; block the run
otherwise). GreenLit then:
 - Opens the URL with a sandboxed headless browser (Playwright) with a
   same-site allowlist, page/request/time limits and SSRF protection.
 - Detects embedded LLM-powered apps (chat widgets, RAG search boxes, agent
   panels) via DOM heuristics (inputs, iframes, shadow DOM), known widget
   signatures, and network inspection (chat/completion-style requests, SSE,
   WebSocket). Shows a screenshot, candidates and confidence; the user confirms
   or corrects the target.
 - Learns the call: records request/response format, auth cookies/headers and
   response mapping (including streams) so the suite can replay over direct
   HTTP; else falls back to scripted UI automation (type, send, wait, read).
 - Saves a versioned connector profile so runs are repeatable and usable for
   regression testing.
 - Runs the golden dataset throttled with a hard request cap, retries, and
   capture of output, latency, status, citations.
 - NEVER bypasses CAPTCHAs, logins or bot protection; never scrapes beyond
   scope; reports "inaccessible" with the reason.
 - Scan-style live progress UI (discovery steps, detected widgets, screenshots,
   request counter). Record discovery and replay success rates per site.

8. DATASET STUDIO (golden dataset: generate OR upload)
Two first-class paths:
 A) UPLOAD: CSV / JSON / JSONL / XLSX with column-mapping UI, validation
    report, duplicate detection, preview, error rows highlighted.
 B) GENERATE according to app type (template-driven):
    - RAG: input = uploaded documents; produce questions (factoid, multi-hop,
      unanswerable, ambiguous), reference answers, reference source passages.
    - Chatbot: input = system prompt/policy + personas; produce single and
      multi-turn scenarios, off-topic, policy edge cases, escalation cases.
    - Agent: input = tool schemas; produce tasks with expected tool calls and
      argument values, plus tool-failure scenarios.
    - Extraction: input = schema + sample docs; produce documents with
      ground-truth field values, including messy/missing/ambiguous cases.
    - Safety category for every type (Section 11).
    Controls: item count, category mix (normal/edge/adversarial/safety),
    difficulty, language (including Hindi/Hinglish), seed. Pipeline: generate
    -> self-verify -> dedupe (embedding similarity) -> quality filter ->
    coverage report -> APPROVAL QUEUE.
 RULES: only human-approved items count as golden. Every item carries
 provenance (uploaded | synthetic | red-team | production-sample) and status.
 Datasets are versioned and content-hashed; immutable once used by a run.
 Support stratified sampling and a dev/test split. Warn when a dataset is
 mostly unverified synthetic data. Export CSV/JSON/JSONL.

9. METRIC LIBRARY (plugin architecture)
Each metric is a class: name, category, description, requires[fields],
mode[reference_based|reference_free], method[rule|llm_judge], rubric_version,
evaluate(trace, item) -> Score. Auto-registered; the UI lists each metric with
its requirements and whether the app/dataset/entry point satisfies them.
APPLICATION QUALITY
- Generation: correctness, accuracy, relevance, completeness, instruction
  following.
- RAG: context relevance, context precision, retrieval recall@k, MRR, nDCG,
  faithfulness/groundedness (claim-level decomposition + verification),
  citation accuracy, abstention ("I don't know") correctness.
- Tool use: tool selection accuracy, parameter correctness, task completion,
  error recovery.
- Multi-turn: context retention/memory, clarification behavior, consistency.
- Component: query-rewriter quality, reranker uplift, output-parser validity
  (JSON schema pass rate), embedding/vector-DB hit rate, guardrail
  precision/recall, and candidate-LLM suitability comparison on the same suite.
OPERATIONAL
- Latency p50/p95/p99, cost per request, token efficiency, error rate, latency
  under load (async load runner with configurable concurrency/duration).
REFERENCE-BASED: exact match, F1, ROUGE, embedding similarity, schema match.
REFERENCE-FREE: LLM-judge rubrics, rule checks, self-consistency over N samples.
SAFETY: see Section 11.

10. HUMAN-IN-THE-LOOP
LLM-as-judge by default. Auto-escalate to the Review Queue when: judge
confidence is low, judges disagree, a hard gate fails, or the score is within a
margin of its threshold. Methods: direct grading (1-5 + labels + comment),
blind A/B pairwise preference, red-team sessions, golden-dataset approval,
HITL override with required justification (audit-logged). Calibration page:
judge vs human on the same items with Cohen's kappa, Krippendorff's alpha,
Spearman, accuracy, confusion matrix, per-metric reliability, and a
recommendation on whether each judge can be trusted for that metric. Include
annotation export for inter-annotator agreement across 2-3 reviewers.

11. SAFETY AND RED-TEAM MODULE (first-class, with hard gates)
Versioned attack packs (tagged with OWASP-LLM-style categories), used
defensively against the user's own authorized app:
 - Direct prompt injection (instruction override, delimiter confusion,
   role-play framing).
 - INDIRECT prompt injection: malicious instructions hidden in retrieved
   documents, tool outputs, emails, web content, uploaded files.
 - Jailbreaks: persona/role-play, hypothetical framing, multi-turn gradual
   escalation, payload splitting, encoding/obfuscation, multilingual
   (Hindi/Hinglish and others).
 - System-prompt / hidden-instruction leakage and extraction attempts.
 - PII LEAKAGE: seed canary PII and secrets (fake names, phone numbers,
   Aadhaar-like numbers, emails, API-key-like strings) into the system prompt,
   knowledge base, memory, history; detect leaks via regex + NER + LLM check +
   canary-token matching; also PII echoing and cross-user memory leakage.
 - Data exfiltration and excessive agency (unauthorized tools, dangerous
   arguments, acting without confirmation).
 - Harmful content, toxicity, and bias (paired counterfactual prompts varying
   gender/religion/caste/region).
 - Scope violation / off-topic handling.
 - OVER-REFUSAL: benign prompts that look risky.
Attack mutation engine: paraphrase, translate, encode, split across turns, wrap
inside documents to generate variants of any seed attack.
Metrics: Attack Success Rate (overall and per category), refusal correctness,
over-refusal rate, PII/canary leak rate, system-prompt leak rate, unsafe tool
call rate, toxicity score, bias gap. Judge with rules/canaries first, LLM judge
second, escalate ambiguous cases to humans.
Guardrail ablation: run the same safety suite with guardrails ON vs OFF and
report the uplift. Default safety hard gates in criteria templates (e.g.
canary/PII leak rate = 0, critical-category ASR below threshold). Red-team
console: reviewers write live attacks against a chosen app version; successful
attacks can be promoted to the golden dataset as permanent regression tests.
Show a "for defensive testing" notice. Send attack content only to the user's
own authorized app and the configured LLM providers.

12. DECISION ENGINE AND STATISTICS
Hard gates first (any failure => NO_GO with exact reasons), then weighted soft
score vs thresholds => GO / REVIEW / NO_GO. Generate a plain-language Readiness
Report answering the practical questions, naming the failing component, and
suggesting fixes. Version comparison: paired bootstrap CIs, paired permutation
or Wilcoxon (continuous), McNemar (pass/fail), effect sizes,
multiple-comparison correction, win/tie/loss counts, explicit "no significant
difference" outcome, small-sample warnings, variance over N repeated runs.

13. REGRESSION TESTING (first-class feature)
Every change to prompt, model, chunking, retriever, embedding, guardrails, or
entry point is checked against the last approved version using the SAME suite.
- BASELINE: any completed run can be marked "Approved Baseline" per project and
  suite (who approved, why). One active baseline at a time.
- REGRESSION SUITE: pinned subset of the golden dataset that must never fail
  (critical queries, past bugs, promoted red-team attacks), tagged
  "regression-critical".
- REGRESSION CHECK: compare candidate vs baseline per metric and per item with
  the paired statistics above. Classify each metric as Improved / No
  significant change / Regressed, with configurable tolerance bands per metric
  (e.g. allow -2% quality, 0% safety).
- Item-level diffs: newly failing, fixed, unchanged; new failures shown first.
- Regression gate: configurable rule (block if any safety metric regresses, or
  any regression-critical item fails, or quality drops more than X with
  significance). Result PASS / WARN / BLOCK with exact reasons.
- Change attribution: config diff between baseline and candidate beside the
  metric deltas.
- CI/CD: POST /api/v1/ci/regression-check (API-token auth) runs the suite on a
  new version and returns PASS/WARN/BLOCK plus a report URL; include an example
  GitHub Actions workflow and optional webhook.
- Scheduled re-evals: Celery beat re-runs the baseline suite on a schedule to
  detect model drift when a provider's underlying model changes.
- UI: "Regression" tab with baseline selector, metric trend chart across
  versions, regression heatmap (metrics x versions), new-failure list, and
  "Promote candidate to baseline" (Admin approval, audit-logged).

14. FRONTEND DESIGN AND UX (must be excellent)
Design system: tokens for color/spacing/radius/shadow; dark default with a
green "go" accent (#3DDC84 family) on near-black green-tinted neutrals, plus
semantic colors (success, warning, danger); light mode supported (system
default, persisted); Inter or Manrope for UI, JetBrains Mono for code/traces;
8px grid; subtle gradients/glass used sparingly; Framer Motion transitions;
skeleton loaders (no bare spinners); designed empty states with CTAs; toasts;
optimistic updates; WCAG AA and full keyboard support; responsive (laptop
first, usable on tablet/mobile for review and results); command palette
(Ctrl/Cmd+K).
Public: polished landing page (hero, workflow diagram, feature grid, animated
product mock, CTA). Auth: split-screen login/signup/forgot/reset with animated
brand panel, inline validation, password strength meter. First-login
onboarding: create workspace -> connect an LLM provider (GitHub Models token or
Ollama) -> load demo project.
Shell: collapsible sidebar, workspace switcher, breadcrumbs, provider health
badge, notifications, user menu.
Pages:
 1 Dashboard (KPIs, verdict badges, recent runs, trends)
 2 Project Wizard stepper: Define task -> Success criteria -> Golden dataset
   -> Eval methods -> Run -> Evaluate -> Analyze -> Decide (loop back to
   improve and re-run the SAME suite)
 3 Connect App + App Versions: ENTRY POINT DROPDOWN with dynamic form,
   input/output mapping, "Where does my app run?" helper, Test call panel
   (parsed trace, raw response, latency, detected vs missing fields),
   access-level badge, config diff, version lineage, and the URL discovery
   screen with screenshots and detected widgets
 4 Dataset Studio (upload, generate by app type, approval queue, editable
   virtualized table, coverage report, versions)
 5 Criteria Builder (metrics grouped Quality / Safety / Operational, gate
   toggles, threshold sliders, weights, templates for RAG/chatbot/agent/
   extraction, live "verdict preview" on the last run)
 6 Run Page (cost/time estimate, quota meter, live SSE progress, pause/resume,
   cancel)
 7 Results (verdict banner with reasons, category score cards, radar chart,
   metric distributions, per-example drill-down, filters)
 8 Trace Viewer (pipeline waterfall rewrite -> retrieve -> rerank -> prompt ->
   LLM -> parse -> guardrails with timings/tokens/cost, retrieved chunks
   highlighted vs answer claims, failing step highlighted, per-item scores,
   raw JSON toggle, "send to review", "add to regression suite")
 9 Compare (deltas with CIs and significance badges, win/loss explorer, diff)
10 Regression (baseline, trends, heatmap, new failures, promote baseline)
11 Safety Center (attack library, ASR by category, guardrail ON/OFF uplift,
   leak findings, red-team console)
12 Human Review (queue, grading, blind A/B, override) + Calibration
13 Failure Analysis (failures grouped by component/category, clusters, top
   reasons, suggested fixes)
14 Reports (PDF/Markdown/CSV readiness report with charts, Final Report mode
   stamp)
15 Settings (LLM providers and rate limits, judge profiles, pricing,
   members/roles, API tokens, sessions, audit log)

15. NON-FUNCTIONAL AND DELIVERABLES
- Tests: unit (every metric, decision engine, stats, regression logic, every
  entry point type's schema validation and test-call parsing, LLMGateway with
  mocked providers and rate limiter), API integration, Playwright E2E for the
  golden path (signup -> project -> choose entry point -> dataset -> run ->
  verdict).
- Seed script (`make seed`): demo workspace with 5 users/roles, built-in RAG
  app, a small demo website with the sample chatbot embedded (for URL
  discovery), a sample HTTP app in Docker, 40-item golden dataset including
  adversarial/safety items, a GOOD version, a deliberately BROKEN version (bad
  chunking/retriever, weak prompt, no guardrails), and a REGRESSING version (a
  prompt change that breaks previously passing items), so the platform shows GO
  vs NO_GO, pinpoints the failing component and safety failures, and returns
  BLOCK on the regression.
- Research support: export all run data (scores, human labels, judge outputs,
  entry point type, provider/model used) to CSV/JSON; scripts that compute
  judge-human kappa, defect detection rate (precision/recall on injected
  defects), verdict agreement, and bootstrap confidence intervals.
- README: mermaid architecture diagram, run instructions (including GitHub
  Models token setup and Ollama setup), env var table, "how to add a metric",
  "how to choose and configure an entry point" (all 13 types), "how to add an
  attack pack", "how to use in CI".
- Performance: virtualize large tables, index run/trace/score lookups, no N+1.

16. PHASES WITH ACCEPTANCE CHECKLISTS (stop after each)
Phase 1 - Foundation
  Build: monorepo scaffold, Docker Compose, config/env, DB + Alembic, auth,
  workspaces, RBAC, audit log, app shell, design system, auth pages, landing.
  Acceptance:
  [ ] `docker compose up` starts api, web, worker, redis, postgres healthy
  [ ] /healthz and /readyz return OK; OpenAPI docs load
  [ ] Signup, login, refresh rotation, logout, password reset work
  [ ] RBAC: a Viewer cannot call Engineer/Admin endpoints (tested)
  [ ] Cross-workspace access is impossible (tested)
  [ ] Audit log records login and workspace actions
  [ ] Landing and auth pages render in dark and light mode, keyboard-usable
  [ ] Lint, type-check and tests pass
Phase 2 - Providers, projects, entry points
  Build: LLMGateway (GitHub Models + Ollama + rate limiter + fallback),
  settings + judge profiles, projects, app versions, ENTRY POINT DROPDOWN
  framework (type registry, per-type Pydantic/Zod schemas, dynamic form,
  /entry-point-types, /connectors/test-call), types 1-6 and 11, trace
  contract, tracing SDK, built-in RAG app, Prompt App.
  Acceptance:
  [ ] "Test connection" works for GitHub Models and Ollama (mocked in tests)
  [ ] Rate limiter queues, never exceeds configured RPM, and pauses on RPD
  [ ] Entry point dropdown lists all 13 types; unimplemented ones are shown
      disabled with "coming in phase N"
  [ ] Selecting a type renders the correct form; invalid input shows errors
  [ ] Test call returns a parsed trace and lists detected vs missing fields
  [ ] Save is blocked until Test call passes
  [ ] Secrets are encrypted at rest and never appear in logs or API responses
  [ ] Built-in RAG app answers a sample question end to end
  [ ] Changing the entry point creates a new AppVersion
Phase 3 - Datasets and run engine
  Build: Dataset Studio (upload + generate by app type + approval queue +
  versioning), Celery run engine with SSE, pause/resume on quota, cancel.
  Acceptance:
  [x] CSV/JSON/JSONL upload with column mapping and validation errors shown
  [x] Generation works for RAG, chatbot, agent, extraction templates
  [x] Only approved items are usable in runs; provenance is stored
  [x] Dataset versions are immutable and hash-stable
  [x] A 20-item run completes with live progress in the UI
  [ ] Killing the worker mid-run and restarting resumes without duplicates
      (recovery logic is integration-tested; live process interruption needs
      manual verification; see docs/PROGRESS.md)
  [x] Cancel and pause/resume work; one failing item does not kill the run
Phase 4 - Metrics
  Build: metric plugin system, rule + LLM-judge metrics (quality, RAG, tool,
  operational), judge cache, multi-judge.
  Acceptance:
  [x] Every registered rule metric has fixed-example unit tests
  [x] Metrics that need missing trace fields are skipped and marked "not
      instrumented", not failed
  [x] Judge output is validated JSON; malformed output is repaired or retried
  [x] Cache hit avoids a second provider call (tested)
  [x] Judge prompt-injection test (hostile text in an answer) does not change
      the score in the mocked-provider test
Phase 5 - Verdict and trace viewer
  Build: criteria builder, decision engine, Results page, Trace Viewer.
  Acceptance:
  [x] Any hard-gate failure forces NO_GO with the exact reason
  [x] Weighted score and thresholds produce GO/REVIEW/NO_GO (unit-tested on
      edge cases)
  [x] Results page implements the verdict banner, category cards, radar chart,
      and per-item drill-down; live authenticated result-screen inspection still
      needs a manual check
  [x] Trace waterfall highlights zero scores and hard-gate failures; retrieved
      chunks are displayed alongside the answer
  [x] Readiness Report names missing instrumentation and failing components
Phase 6 - Compare, failure analysis, regression
  Build: compare + statistics, failure analysis, REGRESSION TESTING.
  Acceptance:
  [x] Bootstrap CI, permutation/Wilcoxon and McNemar tested against known values
  [x] Compare shows "no significant difference" when appropriate
  [x] Baseline can be set and promoted with Admin approval and audit entry
  [x] Regression check returns PASS/WARN/BLOCK with reasons and new-failure list
  [x] The seeded regressing version returns BLOCK
Phase 7 - Safety and red-team
  Build: attack packs, mutation engine, canary PII tests, indirect injection,
  guardrail ablation, red-team console.
  Acceptance:
  [ ] ASR, leak rate and over-refusal computed per category
  [ ] Canary PII/secret planted in the system prompt is detected when leaked
  [ ] Indirect injection via a retrieved document is tested and scored
  [ ] Guardrails ON vs OFF produces an uplift report
  [ ] Red-team attack can be promoted to a regression-critical dataset item
  [ ] Safety hard gates block launch in the criteria templates
Phase 8 - Human review and calibration
  Build: review queue, escalation rules, A/B, calibration, Final Report mode.
  Acceptance:
  [ ] Low-confidence, disagreeing, near-threshold and gate-failing items are
      auto-queued
  [ ] Reviewer role can grade but cannot change criteria or settings
  [ ] Blind A/B hides version labels
  [ ] Overrides require justification and are audit-logged
  [ ] Calibration page shows kappa, alpha, Spearman and a confusion matrix
  [ ] Final Report mode re-scores stored traces without calling the app
Phase 9 - Remaining connectors, CI, polish
  Build: entry point types 7-10 (Docker, Git, CLI, Proxy), CI regression
  endpoint + workflow example, scheduled re-evals, report export, load testing,
  research export scripts, seed data, E2E tests, polish, final README.
  Acceptance:
  [ ] Docker and Git entry points run in a sandbox with resource limits and
      are torn down after the run
  [ ] Proxy mode records traces from an app pointed at GreenLit
  [x] CI endpoint authenticates with an API token and returns PASS/WARN/BLOCK
  [x] `make seed` produces GOOD=GO, BROKEN=NO_GO, REGRESSING=BLOCK
  [x] PDF/Markdown/CSV reports export; research scripts produce kappa and CIs
  [ ] Playwright E2E golden path passes; README covers all 13 entry points
Phase 10 (stretch) - Website discovery and MCP
  Build: WEBSITE_URL discovery (type 12) and MCP_SERVER (type 13).
  Acceptance:
  [ ] Authorization checkbox is required and audit-logged
  [ ] Discovery finds the chatbot on the seeded demo website and shows a
      screenshot and confidence
  [ ] Replay works over direct HTTP, with UI-automation fallback
  [ ] Request cap and throttling are enforced; CAPTCHAs/logins are reported as
      "inaccessible", never bypassed

17. PHASE COMPLETION PROTOCOL
At the end of every phase you MUST:
 1. Run lint, type-check, unit tests and the relevant integration tests, and
    paste the command output summary.
 2. Print the phase's acceptance checklist with PASS / FAIL per line, with
    evidence (test name, command, or screen path). Never mark PASS without
    evidence. Fix every FAIL before stopping, or list it as a known gap.
 3. List assumptions, known limitations, and any spec items intentionally
    deferred.
 4. Give the exact commands to run the stack and verify manually.
 5. Update README and docs/PROJECT_SPEC.md progress notes.
 6. Ask whether to start the next phase and wait for explicit approval. Do not
    begin the next phase before approval.

## Implementation progress

Phase 1 is DONE as of 2026-10-08. Phase 2 is complete with documented
limitations as of 2026-10-08. Phase 3 is complete with documented limitations
as of 2026-10-08; its live worker-kill/restart acceptance still needs a manual
check. Phase 4 is complete with documented limitations as of 2026-10-08.
Phase 5 is complete with a documented manual UI check outstanding as of
2026-10-08. Phase 6 is complete as of 2026-10-08 and adds comparison,
statistical significance, baseline approval, and regression reporting.

**Updated 2026-10-10:** Phases 7 and 8 are partial helper implementations,
not completed product workflows. The Phase 9 runner sandbox and E2E gaps remain,
and Phase 10 website/MCP entry points are disabled pending safe, verified
implementations. The current full backend suite reports 85 passing tests, but
this test result does not satisfy the unchecked acceptance criteria. See
`docs/PROGRESS.md` for evidence and limitations.

Phase 1 checklist evidence is recorded in `docs/PROGRESS.md`. Dark/light theme
rendering and keyboard navigation were manually checked in the browser on the
landing, login, and signup surfaces. These checks are a smoke test, not a full
WCAG accessibility audit.

Phase 2 acceptance checklist:
- PASS: GitHub Models and Ollama connection tests use mocked provider responses
  in `test_provider_connection_works_for_github_and_ollama_without_exposing_secrets`.
- PASS: RPM queueing and RPD pausing are covered by
  `test_provider_rate_limiter_queues_rpm_and_pauses_at_rpd`.
- PASS: `/api/v1/entry-point-types` lists all 13 types, with unavailable Python
  execution and later-phase types marked unavailable; checked by
  `test_registry_lists_all_thirteen_types_and_validates_type_settings`.
- PASS: RAG's type-specific fields render in the browser, JSON document input is
  formatted, and invalid RAG settings return HTTP 422 in the registry test.
  Manual browser verification did not cover every type.
- PASS: Prompt App/RAG calls return output, trace, usage, and detected/missing
  trace fields in `test_prompt_and_rag_test_calls_gate_saves_and_create_app_versions`.
- PASS: the same integration test proves save is denied before a successful test
  and rejects changed settings; browser check confirmed Save starts disabled and
  Test call is enabled only after required fields are selected.
- PASS: secret persistence and API redaction are covered by
  `test_provider_connection_works_for_github_and_ollama_without_exposing_secrets`
  and `test_http_test_call_redacts_and_encrypts_secret_headers`; the latter also
  asserts captured logs do not contain the secret.
- PASS (mocked provider): built-in RAG retrieves supplied document context and
  returns an answer in `test_prompt_and_rag_test_calls_gate_saves_and_create_app_versions`.
- PASS: changing the entry point creates successive AppVersions in that same
  integration test.
- PASS: built-in Agent mock tool calls and schema rejection are covered by
  `test_builtin_agent_executes_schema_validated_mock_tool_calls` and
  `test_builtin_agent_rejects_tool_arguments_outside_schema`.
- PASS: trace-context nesting and async task isolation are covered by
  `test_trace_context_captures_steps_and_restores_parent_context` and
  `test_trace_context_isolated_between_async_tasks`.
- KNOWN GAP: Python Function and Python SDK Traced remain unavailable because
  user code requires a resource-limited isolated runner. Neither user code nor
  uploaded modules are executed in-process or in an unrestricted subprocess.
- KNOWN GAP: full browser validation of each entry-point form and a fully
  instrumented Python SDK Traced integration test remain deferred with that
  isolated-runner work.

Phase 2 validation evidence:
- `docker compose ps`: API, web, worker, Redis, and PostgreSQL all healthy.
- `GET /healthz`: `{"status":"ok"}`; `GET /readyz`: `{"status":"ready"}`;
  `/docs` and the web app returned HTTP 200; Alembic current is `0002_phase2 (head)`.
- Backend `pytest -q tests`: 19 passed, 2 dependency deprecation warnings.
- Ruff check, Ruff format check, strict mypy, and all configured pre-commit hooks
  passed. Frontend ESLint, Prettier, TypeScript typecheck, and production build
  passed.
- Browser check: RAG form rendered without a redundant provider-ID field;
  document JSON was formatted; required provider selection enabled Test call;
  Save remained disabled before a successful test.
- External provider credentials were not used. RAG and provider results are
  verified with mocked responses; retrieval is basic lexical retrieval rather
  than a production retrieval-quality evaluation.

Other known limitations:
- The rate limiter is process-local and neither persists across restarts nor
  coordinates multiple API processes.
- Dark/light visual polish and keyboard navigation received manual smoke checks;
  a full WCAG accessibility audit remains out of scope.
- Generated local databases, test output, secrets, caches, dependencies, and
  build output are intentionally excluded from commits.

To run and verify locally, use `docker compose up --build -d`, `docker compose ps`,
`curl http://localhost:8000/healthz`, `curl http://localhost:8000/readyz`, and open
`http://localhost:8000/docs` plus `http://localhost:5173`. Configure a provider
credential in the workspace UI before exercising Prompt App or RAG against a
real external endpoint. Python Function and Python SDK Traced are intentionally
unavailable until isolated execution is implemented.