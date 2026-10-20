---
marp: true
theme: default
paginate: true
---

# GreenLit
## Evidence-based evaluation for LLM applications

- A local pre-launch evaluation platform
- Tests applications, not just raw models
- Uses repeatable datasets and explicit criteria
- Current status: implemented core with known gaps

![Visual: GreenLit landing page, captured from the actual running app]

---

# The problem: model quality is not app readiness

- Prompts, retrieval, tools, and parsing interact
- Safety and latency matter alongside answer quality
- A change can break examples that used to pass
- Teams need repeatable evidence before launch

![Visual: application components around an LLM]

---

# What GreenLit aims to do

- Connect an app through an entry point
- Build or upload a golden dataset
- Score outputs and available traces
- Apply hard gates and weighted criteria
- Compare later versions with a baseline

![Visual: evaluation-flow.mmd]

---

# A concrete example

- Test a RAG support assistant on fixed questions
- Keep reference answers and source passages
- Inspect output and retrieved chunks
- Re-run the same dataset after a prompt change
- Investigate changed scores and new failures

![Visual: dataset item beside a trace]

---

# Architecture

- React/TypeScript web app
- FastAPI API with SQLAlchemy/Alembic
- PostgreSQL persistence
- Redis broker and Celery worker
- LLM gateway and connector boundary

![Visual: assets/architecture.mmd]

---

# Trace contract

- One minimum boundary: input to output
- Optional steps expose retrieval, tools, prompts, and guardrails
- Usage, latency, and model identity are recorded when available
- Missing trace evidence is “not instrumented”

![Visual: trace waterfall with missing fields explicitly marked]

---

# Entry points: visible does not mean available

- API registry lists 13 types
- HTTP, Prompt App, built-in RAG/Agent, and upload outputs are marked implemented
- Python execution, sandbox connectors, Website URL, and MCP are gated
- Unsupported requests should fail clearly, never return fake traces

![Visual: actual dropdown with disabled reasons]

---

# Dataset and run engine

- Upload CSV, JSON, JSONL, or XLSX
- Map fields, validate rows, track provenance
- Approve items and create hashed versions
- Process runs per item through Celery
- Pause, resume, cancel, and inspect failures

![Visual: dataset validation and run progress, if available]

---

# Metrics and judge outputs

- Deterministic rule metrics for baseline checks
- Configured judge profiles and rubric versions
- Validate JSON; retry malformed output once
- Cache repeated judge inputs
- Mocked provider tests are not live-model certification

![Visual: metric score table with status and provenance]

---

# Verdicts and readiness

- Hard gates are evaluated first
- Soft scores use weights and thresholds
- Failed gates can force NO_GO with reasons
- Readiness reports identify missing instrumentation
- A verdict is not a safety guarantee

![Visual: actual run report, if populated]

---

# Regression and statistics

- Approve a completed run as baseline
- Compare the same dataset version and split
- Use paired statistics and item-level diffs
- Report PASS, WARN, or BLOCK with reasons
- Current tests include a seeded regression case

![Visual: baseline/candidate comparison]

---

# Safety and human review

- Attack packs and canary/prompt leak checks
- Guardrail uplift calculation
- Review queue and blind comparison contract
- Calibration statistics are implemented
- No live red-team or human-label study is claimed

![Visual: attack category summary or calibration matrix]

---

# Implementation challenges

- Provider quotas: queue and pause; limiter remains process-local
- Run reliability: persist per-item state; restart check remains manual
- Judge reliability: validate, retry, cache, treat text as untrusted
- Untrusted integrations: gate unsupported runners rather than execute unsafely
- Keep mocked, contract, and live evidence separate

![Visual: challenge-to-solution table excerpt]

---

# Results and evidence

- Ruff: passed in the latest recorded run
- Strict mypy: 61 source files, no issues
- Frontend lint/typecheck/build: passed
- Backend tests: 76 passed, 4 failed, 2 warnings
- Pre-commit: failed due tool/Python environment resolution

![Visual: concise validation table]

---

# Limitations and next steps

- Reconcile failing connector tests with current disabled policy
- Prove one real provider/app end-to-end
- Verify worker restart and populated result screens
- Build a real database-backed demo seed if required
- Do not enable Website URL/MCP/sandbox features before evidence

![Visual: prioritized gap list]

---

# Closing

- GreenLit makes application-level evaluation repeatable
- Dataset, trace, criteria, and baseline provide context for decisions
- The system is useful as an evidence framework, not an automatic certification
- Current honest verdict: **COMPLETE WITH KNOWN GAPS**

![Visual: GO / NO_GO / BLOCK labels beside evidence sources]
