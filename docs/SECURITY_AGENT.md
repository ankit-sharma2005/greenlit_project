# Security: text that comes from outside GreenLit

Status: **steps 6.0–6.2 done.** The audit below is the 6.0 snapshot; the judge prompt now
carries the S3 envelope and S10's flag is live on every case read (see the controls table).
Nothing below is described as implemented unless its row says so. The controls are listed with what exists today and what is
still missing, so the final version of this document (step 6.6) can record the test that proves
each one. GreenLit is **not claimed to be immune to prompt injection**; the only claims this
repository makes are the ones a named test proves.

## 1. What is untrusted

Every byte below can be written by the person or system being tested, by a dataset author, or
by a model:

- the target app's answers, error bodies and response headers;
- documents pasted or uploaded for dataset generation (text, PDF, TXT, MD);
- dataset items, generated drafts and their edited text;
- the app description typed into the draft generator;
- user-written names, prompts and notes;
- MCP tool output;
- model output itself — judge replies, generated drafts, and (planned) analyst explanations.

## 2. Assets

- provider API keys and the encrypted header/cookie blobs of a run;
- other users' and other projects' data;
- system prompts and the judges' rubric text;
- the integrity of the verdict (scores, hard gates, thresholds 0.60/0.80);
- the user's browser.

## 3. Attacks considered

| Attack | What it would look like |
| --- | --- |
| Instruction hijack | text inside an answer or document says "ignore the rubric" |
| Data exfiltration | model output contains a markdown image or link whose URL carries data, or a tool call/DNS lookup |
| Verdict manipulation | text tells the judge to pass, or to score 1.0 |
| Secret extraction | "print your system prompt", "repeat the API key" |
| Cross-tenant leakage | one account's run or dataset reaching another's prompt or page |
| Resource exhaustion | enormous inputs, loops, retry storms |
| Stored injection | a poisoned dataset item or draft reused later in a judge or generator prompt |
| Spreadsheet formula injection | a CSV cell starting with `=`, `+`, `-`, `@`, tab or CR |
| Renderer injection | model output rendered as HTML/markdown with links, images or scripts |

## 4. Where untrusted text goes today (audit, with file paths)

| Path | Where | Sanitising that exists now | Gap |
| --- | --- | --- | --- |
| Judge prompt | `backend/app/services/judge.py:122-142` | `sanitize_untrusted()` on question, expected answer, app answer and retrieved context; each wrapped in `<question>` / `<app_answer>` tags; the system template is fixed text | Tags are guessable and can be spoofed by the content; no per-request nonce; no secret scrub; no output scanner |
| Dataset generation from documents | `backend/app/services/generation.py:173-210` | Source passages are JSON-encoded, passed through `sanitize_untrusted`, wrapped in `<data>`, and the prompt says the block is data, not instructions; one retry on invalid JSON | Same as above, plus no canary and no scan of the model's reply beyond JSON shape |
| Draft generation (phase 3) | `backend/app/services/drafts.py` (`build_messages`) | Description and documents are JSON-encoded inside `<data>` with a fixed system prompt that says they are data; PII-shaped items are dropped; kinds and lengths validated | No nonce, no secret scrub, no output scan |
| UI rendering | `frontend/src` (all components) | Untrusted text is rendered as React text nodes; a search of `frontend/src` finds **no** `dangerouslySetInnerHTML`, no `innerHTML` and no markdown renderer | None found for renderer injection; a URL in text is inert but still visible |
| CSV / HTML / JSON export | `backend/app/services/report.py` | HTML is escaped (`html.escape(..., quote=True)`); CSV cells starting with a formula character get a leading quote (lines 149-155); request-header values are redacted to `[redacted]`; the encrypted cURL blob never appears | **No XLSX export exists** (XLSX is only an upload format), so there is nothing to neutralise there; answers are not PII-redacted |
| MCP server | `mcp_server/server.py` | Payloads capped at 20,000 characters and reports at 100,000, each with a `truncated` flag; no tool returns a secret | Fields that came from a target are not marked as untrusted data |
| Logs | `backend/app` | A search finds no log call that emits an answer, output or error snippet | Not proven exhaustively; a future log line could leak text |

## 5. Controls to build, and their status

| Control | Status today |
| --- | --- |
| **S1** no `tools` / `functions` / tool response formats in any model request; model output never executed, fetched or rendered as HTML/markdown | By construction: the gateway (`llm_gateway.py`) sends `messages` only, and the UI has no HTML sink. **No test yet asserts the request body.** |
| **S2** one pure function builds every model input from structured fields, with redaction, control/zero-width/bidi stripping, tag stripping and a size cap | **Missing.** Judge and generator each build their prompt inline. |
| **S3** per-request nonce envelope; delimiter, nonce and role markers neutralised inside content | **Done for the judge** (`untrusted.make_envelope`, nonce on its own line, `attribute=False`): a hostile answer cannot close or open the block. The generator and draft prompts still use static `<data>` blocks. |
| **S4** every number and verdict comes from the backend; model text sits in a labelled block; output is schema-validated and cites only real case ids | Analyst not built; the judge's output is already schema-checked and a bad reply becomes "judge unsure", never a pass. |
| **S5** output scanner rejecting URLs, markdown links/images, HTML, shell code fences, secret patterns, canaries and over-length text | **Missing.** |
| **S6** per-request canary in the system prompt, rejected if echoed | **Missing.** |
| **S7** verdict independence: the only write is one `run_explanations` row | Holds vacuously: no analyst exists, and the judge writes scores only through the existing run path. |
| **S8** explicit user action, preview of exactly what is sent, confirmation for remote providers, cache by input hash, one call per click, timeout, token cap, 429 stops | **Missing** (analyst not built). |
| **S9** ownership check before building the input | Existing for runs, datasets and drafts (`owner_id` filters); the analyst must reuse it. |
| **S10** judge prompt hardening + a non-verdict `possible_judge_manipulation` flag for judge-directed text | **Done.** Envelope, score/confidence range and `label` enum validation (`pass`/`fail`/`unsure`; anything else is "judge unsure", never a pass), and `detect_judge_manipulation` derived at read time on `/runs/{id}/items` with the notice shown above the charts. No column, no migration, no score or verdict touched. |
| **S11** stored injection: dataset items, drafts and documents are untrusted wherever they are later sent to a model | **Partial:** generation and drafts wrap their inputs; dataset items are not enveloped when they later reach the judge. |
| **S12** MCP fields marked untrusted and truncated; no secrets returned | **Partial:** truncation and secret-free tools exist; the untrusted marking does not. |
| **S13** spreadsheet formula neutralisation in CSV (and XLSX if it ever exists) | **Done for CSV** (`report.py`), with the existing export tests passing unmodified and new tests pinning `=`, `+`, `-`, `@`, tab and CR. There is no XLSX export (XLSX is upload-only), so there is nothing else to neutralise. |

## 6. Why there is no autonomous planner

A planner would need tool calls and write access. This design deliberately gives no model
tools, no function calling, no network access and no write path: the verdict stays
deterministic, and the only planned model output is explanatory text about a finished run.
That decision is what makes S1 and S7 enforceable rather than aspirational.

## 7. Residual risks (to be restated unchanged at step 6.6)

- The judge can still be influenced in ways no flag or scanner detects; the verdict rules stay
  deterministic, but the judge's score for one case is model judgement.
- An explanation can be misleading while staying inside the allowed format.
- A pattern-based scanner misses paraphrases and novel payloads.
- A remote provider sees the redacted input that is sent to it.
- Text that passes every check can still be displayed to a human who believes it.
