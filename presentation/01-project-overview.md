# Project overview

## The problem

Testing an LLM application before launch is harder than asking whether a model scored well on a benchmark. A benchmark may compare raw models on a fixed academic task; a real product combines a prompt, retrieval, documents, tools, output parsing, guardrails, and an application workflow. A model can look strong in isolation and still return an invalid JSON object, cite the wrong source, fail to call a required tool, leak information, or become too slow after a change.

GreenLit's specification addresses this gap with a repeatable, criteria-driven suite for a staging or test copy of an application. It explicitly targets the application and its configured task, not raw model ranking. The intended process is offline: use test credentials and fixed test data, not live user traffic. Evidence of actual connector support is narrower than the specification; see [limitations and results](06-results-and-limitations.md).

## What GreenLit does

In simple terms, GreenLit lets a team:

1. Set up a workspace and project.
2. Connect an application through an entry point.
3. upload or generate evaluation examples and approve them.
4. Define quality and hard safety/validity criteria.
5. Run examples through the app and collect a common trace shape.
6. Score the outputs, inspect issues, and compare later versions with a baseline.

The flow is built from backend services and API contracts, with some front-end project and dataset workflows. The existence of a service or test does not imply a complete, live browser workflow.

### Simple example

Imagine a company has a retrieval-augmented generation (RAG) support assistant. It uploads a small set of questions with reference answers and source passages, then runs the assistant against that fixed set. A trace may include the answer and retrieved chunks. GreenLit can compare the answer to a reference, check retrieved context, report unavailable trace fields as “not instrumented,” and apply the configured launch gates. After a prompt or retriever change, the same test set can be compared to an approved baseline.

This example describes the intended workflow. Provider-dependent RAG responses in the test suite use mocked provider responses; a real external-provider run requires a configured live provider and was not established by the repository's latest validation.

## Who uses it

- **Owners and administrators** configure a workspace, providers, projects, and launch criteria.
- **Engineers** connect supported applications, build datasets, start runs, and inspect failures.
- **Reviewers** can use the human-review contract and calibration operations described in Phase 8.
- **Viewers** can inspect allowed workspace information without write access.

The role checks are implemented through FastAPI dependencies and workspace memberships. The project targets a small local deployment; the spec names approximately five users rather than a large multi-tenant cloud service.

## Main outputs

| Output | Meaning |
|---|---|
| **GO** | The candidate meets configured launch criteria in the decision service. It is evidence for review, not a guarantee of production safety. |
| **NO_GO** | A hard gate failed or configured score criteria were not met. The report can include reasons and item-level results. |
| **Readiness report** | Shows run results and issues such as failed items or missing trace instrumentation. |
| **Regression PASS / WARN / BLOCK** | Compares a candidate to a baseline and reports changes, critical failures, and reasons. |
| **Safety findings** | Summaries can include attack success, canary/prompt leakage, over-refusal, unsafe tool calls, and guardrail uplift. The tested safety calculations are contract-level and are not a live red-team certification. |

The static Phase 9 seed script encodes examples of GOOD=GO, BROKEN=NO_GO, and REGRESSING=BLOCK. It writes a JSON summary; it does not provision live demo users, a database-backed project, or a website.

## How it differs from a model benchmark

| Raw model benchmark | GreenLit's application-evaluation goal |
|---|---|
| Asks how a model performs on benchmark tasks. | Asks whether this configured application is ready for its users and task. |
| Often treats the model as the unit being measured. | Treats the app version, connector, dataset, criteria, and evaluator configuration as the unit. |
| May produce an overall score or ranking. | Can combine hard gates with weighted scores and item-level reasons. |
| Does not necessarily see application traces. | Uses optional trace fields such as retrieved chunks, tool calls, latency, and token usage where the connector supplies them. |
| May not compare a team's prompt/retriever change to its prior version. | Supports baseline comparison and regression reporting for paired runs on the same dataset version. |

The application-level distinction is the design goal written into [the project spec](../docs/PROJECT_SPEC.md), sections 1 and 12. The current implementation and gaps are summarized in [the audit](../docs/AUDIT.md).
