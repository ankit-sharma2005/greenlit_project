# Architecture

## Component view

![GreenLit component diagram](assets/architecture.mmd)

The web app uses the API for authentication, workspace/project operations, connectors, datasets, runs, and reports. The API persists application data in PostgreSQL. Celery workers use Redis as the broker for asynchronous work. GreenLit calls configured LLM providers through one internal gateway; the connector layer sends evaluation inputs to supported applications and normalizes responses into trace-like records.

`docker-compose.yml` currently defines five services: PostgreSQL, Redis, API, worker, and web. There is no `beat` service in the current Compose file even though it is mentioned in the specification's desired stack. Production deployment, distributed scaling, and scheduled evaluation are not demonstrated by this local Compose setup.

## Evaluation flow

![GreenLit evaluation flow](assets/evaluation-flow.mmd)

The criteria and dataset version are part of the run's stored configuration. In particular, `EvalRun` stores an app version, dataset version, split, and criteria snapshot. The run engine processes per-item work and records output, trace, score, and status. A decision is made from those results. A later run can be compared with an approved baseline if both runs share a dataset version and split.

## Trace contract

The code's connector result is normalized around fields with this shape:

```text
{
  output,
  steps: {
    rewritten_query?,
    retrieved_chunks?,
    reranked_chunks?,
    prompt_sent?,
    raw_llm_output?,
    parsed_output?,
    tool_calls?,
    memory_state?,
    guardrail_events?
  },
  usage: { tokens_in?, tokens_out? },
  latency_ms,
  model_used?
}
```

The minimum useful contract is input to output. Optional step fields provide deeper visibility. A missing field is not a measured failure: metrics that require it can report `not_instrumented`. That is important for black-box applications, which may expose only request/response behavior, versus white-box applications that can supply internal trace fields. The Python SDK traced entry point remains disabled, so this does not mean arbitrary Python apps are presently instrumented.

## Entry-point dropdown and connector types

The API registry exposes 13 types from `GET /api/v1/entry-point-types`; the UI uses the registry and displays type-specific reasons for disabled choices.

| Type | Current registry status |
|---|---|
| `HTTP_ENDPOINT` | Implemented |
| `PYTHON_FUNCTION` | Disabled; isolated execution required |
| `PYTHON_SDK_TRACED` | Disabled; isolated execution required |
| `PROMPT_APP` | Implemented |
| `BUILTIN_RAG_APP` | Implemented |
| `BUILTIN_AGENT_APP` | Implemented |
| `DOCKER_IMAGE` | Disabled; verified sandbox required |
| `GIT_REPO` | Disabled; verified sandbox required |
| `CLI_COMMAND` | Disabled; verified sandbox required |
| `PROXY_MODE` | Disabled; verified outbound sandbox required |
| `UPLOAD_OUTPUTS` | Implemented |
| `WEBSITE_URL` | Disabled; manual browser verification required |
| `MCP_SERVER` | Disabled; manual MCP verification required |

When a type has `implemented: false`, connector validation rejects it with a clear unavailable message. The source includes connector code paths for some of these formats, but a path in code is not proof of a safe, supported runtime. The latest test run also exposes disagreement between older tests that expect execution and the current gating behavior.

## Metric registry

Metrics are represented by `MetricDefinition` records in `backend/app/services/metrics.py`. A definition names the category, description, required trace/dataset fields, evaluation mode, method, rubric version, and evaluator function. The catalog can report which required fields are absent. This is a registry in the application code, not a plug-in installation system for third-party extensions.

Deterministic checks include answer presence, normalized exact match, lexical context recall, expected tool-call match, latency, token-usage presence, and JSON-schema validity. LLM-judge scores use configured judge profiles and are stored with related metadata. The project's own docs call out that several rules are intentionally simple baselines rather than broad quality measurements.

## Decision engine: hard gates and soft scores

The decision service evaluates hard gates first: a hard-gate failure can force `NO_GO` with an explanation. Weighted category scores and configured thresholds determine other outcomes such as `GO` or `REVIEW`. A run stores its criteria snapshot so later edits do not rewrite what an earlier run was judged against.

This is a deterministic rules framework around measured scores; a verdict is only as reliable as its data, instrumentation, metrics, and criteria. It is not an automatic certification of an application.

## Regression testing and baselines

An administrator can approve a completed run as a project's baseline. The comparison service pairs items from the same dataset version and split and uses paired statistics, including bootstrap intervals, permutation testing, and exact McNemar calculations. Regression results include status and newly failing items. A regression-critical item can contribute to a `BLOCK`.

The Phase 9 CI route authenticates a workspace API token and formats a status from supplied checks. The tracked workflow does not demonstrate an actual GitHub Actions job running GreenLit evaluations, and the repository contains no tracked `.github/` workflow.
