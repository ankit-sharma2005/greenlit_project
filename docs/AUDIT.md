# GreenLit audit

## Status

Updated: 2026-10-09
Verdict: COMPLETE WITH KNOWN GAPS

This project is validated for the implemented, tested phases and the later-phase browser/sandbox items remain explicitly deferred unless backed by real execution evidence.

## Summary by phase

| Phase | Status | Evidence | Key gaps |
|---|---|---|---|
| 1 | IMPLEMENTED+TESTED | Docker health, `/healthz`, `/readyz`, `/docs`, backend + frontend validation, and auth tests | Manual theme/keyboard checks remain UI-only smoke checks |
| 2 | IMPLEMENTED+TESTED | `backend/tests/test_phase2.py` validates provider behavior, connector registry, and safe test-call flows | Python Function / Python SDK Traced remain intentionally gated behind an isolated runner |
| 3 | IMPLEMENTED+TESTED | Dataset upload and validation tests in backend suite | None in the implemented core |
| 4 | IMPLEMENTED+TESTED | Metric and judge-profile tests | None in the implemented core |
| 5 | IMPLEMENTED+TESTED | Verdict and trace viewer tests | None in the implemented core |
| 6 | IMPLEMENTED+TESTED | Regression/comparison tests | None in the implemented core |
| 7 | IMPLEMENTED+TESTED | Safety and guardrail tests | None in the implemented core |
| 8 | IMPLEMENTED+TESTED | Human-review and calibration tests | None |
| 9 | IMPLEMENTED+TESTED | CI regression, demo seeding, export, and research tooling tests | Real connector sandbox/browser E2E remains deferred |
| 10 | PARTIAL | `backend/tests/test_phase10.py` validates registry exposure and contract-level Website URL / MCP server calls | End-to-end browser discovery and MCP runner automation are not proven in production conditions |

## Blocker fix completed

### Proxy-mode test-call request template

Issue: At the proxy connector boundary, the default `request_body_template` was being interpolated with JSON strings in a way that produced invalid JSON when the template contained a quoted value. That caused a 422 during connector test calls and blocked the safe connector contract path.

Fix: [backend/app/services/connectors.py](../backend/app/services/connectors.py) now renders template tokens as JSON-safe values before parsing, and rejects invalid templates with a clear validation error instead of letting the request fail at the API boundary.

Evidence:
- Command: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_phase2.py tests/test_phase10.py`
- Result: `15 passed in 26.58s`
- Additional validation: `ruff check` and `mypy` passed for the touched files.

## Known limitations

- Real Docker/Git/CLI/Proxy sandbox execution is not implemented as a full isolated runner; the project keeps those connector types behind explicit contract validation and does not claim live sandbox execution beyond tests.
- Browser automation and Website URL discovery need manual validation with a real browser or seeded demo website when the environment has a verified browser runner.
- MCP server testing is contract-validated, not proven against a production-like MCP server runtime in a live browser workflow.

## Evidence and required manual checks

The project requires the following manual checks before claiming full end-to-end browser coverage:

1. Launch the seeded demo website and confirm the embedded app is discovered via the Website URL flow.
2. Open a browser session in a sandboxed runner and confirm the UI can be interacted with without escaping the allowed domain or leaking credentials.
3. Run an MCP server endpoint against the seeded demo environment and confirm tool invocation and output mapping match the contract.

These items remain as explicit manual validation tasks rather than being silently marked as complete.
