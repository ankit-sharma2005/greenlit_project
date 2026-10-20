# Phase 10 manual verification: Website URL discovery and MCP

This document is intentionally a manual verification guide. The project contract tests validate the registry and request/response handling, but they do not prove live browser automation or a real MCP server runtime in this environment.

## Scope

This checklist covers the two Phase 10 entry-point types:
- WEBSITE_URL
- MCP_SERVER

These must not be treated as implemented complete without a real browser session and live MCP runtime evidence.

## Preconditions

1. Start the stack via Docker:
   ```powershell
   docker compose up --build -d
   docker compose ps
   ```
2. Confirm the API is ready:
   ```powershell
   Invoke-RestMethod http://localhost:8000/healthz
   Invoke-RestMethod http://localhost:8000/readyz
   ```
3. Ensure a seeded demo website is reachable, and the environment contains a browser runner capable of interacting with it. This is a manual verification requirement.
4. Ensure the MCP endpoint is reachable and configured with a real tool endpoint, not a mock or stub.

## A. Website URL discovery

### Steps

1. Open the app in a browser and create or open a workspace.
2. Create a new project or app entry point.
3. In the entry-point type dropdown, confirm `WEBSITE_URL` is present but disabled with a clear reason if the app is in the current unsupported state.
4. If the app allows a project flow that is intentionally gated, confirm the API rejects the request with a clear error such as: `This entry point type is not available yet; it requires manual browser verification against the seeded demo website.`
5. Launch the seeded demo site in a browser session.
6. Confirm the site exposes an embedded chatbot or widget that GreenLit can discover.
7. Run the Website URL test or flow using the real site URL.
8. Confirm the result includes a discovered title or source metadata, and the trace captures the page content and the tool-call metadata.

### Expected result

- The app does not claim the feature is fully implemented unless a real browser session proves it works.
- The discovered page is shown as a website and the tool-call metadata is recorded in trace output.
- The system does not create a fake success trace when the browser or site is unavailable.

### Negative cases

- If the site is blocked, login-gated, or CAPTCHA-protected, the flow should fail with a clear error and no success trace.
- If the authorization checkbox is left unchecked, the API must reject the request and explain that explicit authorization is required.
- If the URL is invalid or missing a host, the API must reject it before any network call is made.

## B. MCP verification

### Steps

1. Open the app and navigate to the project entry-point creation flow.
2. Confirm `MCP_SERVER` is present but disabled with a clear reason in the UI when the environment does not provide a live verified MCP runner.
3. If the API is invoked directly, confirm the request is rejected with an error saying the entry point is not available yet and that live MCP runtime verification is required.
4. Configure or connect to a real MCP server endpoint used by the seeded demo environment.
5. Submit a tool call with a known input and confirm that the tool name and prompt are mapped correctly.
6. Observe the returned output and trace metadata.

### Expected result

- A real MCP server call succeeds and the returned output appears in the trace.
- The app records the tool call result and maps it to the expected schema.
- It does not return a fake success trace when the MCP server is unavailable or unauthorized.

### Negative cases

- A dead or unreachable MCP endpoint must fail clearly and not return a fabricated success payload.
- Unauthorized or blocked MCP requests must fail explicitly.
- A CAPTCHA/login screen in front of the target site must be treated as a failure condition for website discovery and not as a fake success.

## C. Authorization gate

This must be checked explicitly:

1. Attempt Website URL discovery without ticking the authorization checkbox.
2. Confirm the backend rejects the request with a clear error.
3. Attempt an MCP server request in a configuration without required consent or authorization.
4. Confirm the request is rejected, not silently accepted.

## D. Required evidence to record

Record the following for both flows:
- the exact URL used
- the exact server or site response status
- the exact error or output seen
- a screenshot or trace snippet proving the result
- whether the flow was accepted or rejected

## E. Statement of status

Until a live browser and a real MCP server prove the end-to-end flow, the correct status remains:
- NEEDS MANUAL CHECK for Website URL discovery
- NEEDS MANUAL CHECK for MCP runtime verification
- Not complete as a production claim
