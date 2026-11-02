# Driving GreenLit from an MCP client

`mcp_server/` is a small stdio MCP server that lets an MCP client (Claude Desktop,
Freebuff, Copilot or any other) inspect GreenLit runs by calling the **existing**
REST API. It is a thin client: it signs in like a browser does, keeps the session
cookie in memory, and returns what the API said.

## What it can do

| Tool | What it returns |
| ---- | --------------- |
| `greenlit_list_projects` | The one GreenLit project this account can drive, with the account and the API's dataset and run totals. |
| `greenlit_get_run_status` | A run's state and counts: total cases, answered, failed, cancelled, not run. No case text or answers. |
| `greenlit_get_verdict` | GO / REVIEW / NO-GO, the weighted score, the API's own `verdict_reason`, and the instrumented metrics that failed. |
| `greenlit_get_report` | A run's report as `summary_json`, `csv` or `html`, truncated at 100,000 characters with `"truncated": true`. |
| `greenlit_get_criteria` | The engine's own weights, thresholds, hard gates and ordered decision rules. |
| `greenlit_start_run` | Only when `GREENLIT_MCP_ALLOW_START=1`: starts a run against a target **on this machine** and returns its id immediately. |

Every tool returns JSON with a `truncated` flag and caps its size (20,000 characters
for the small payloads, 100,000 for a report). API failures come back as tool errors
in plain words — the kind, the HTTP status, and the host and path — never a stack
trace and never a credential.

## What it cannot do

- It cannot change a decision rule, a weight or a threshold: `greenlit_get_criteria`
  reads them from `GET /api/v1/criteria`.
- It cannot edit settings, delete anything, create users, change tokens, export
  credentials or touch a baseline.
- It cannot start a run against a remote app. GreenLit wants the permission record
  (checkbox plus reference) stored with that run, and this server never sets or
  changes that record, so it refuses anything that is not `localhost`, `127.0.0.1`,
  `::1` or `host.docker.internal`. Use the GreenLit UI for those.
- It cannot import the application, read its database or bypass the API. It speaks
  HTTP to `GREENLIT_URL` and nothing else.
- GreenLit has a single project per deployment, so `greenlit_list_projects` always
  returns exactly one entry (`"id": "default"`), built from the API rather than
  invented; there is no projects endpoint to page through.

## Security rules

1. **Use a dedicated, low-privilege account — never the admin one.** The server only
   needs an account that can read runs and datasets and (if you enable it) start one.
   An MCP client is another program with your credentials; give it the smallest set
   that works. Registering the account is a normal sign-up, and the first account on
   a fresh deployment is the admin, so create the admin first and this account second.
2. **Configuration is environment only.** `GREENLIT_URL`, `GREENLIT_EMAIL`,
   `GREENLIT_PASSWORD`, `GREENLIT_MCP_ALLOW_START`. There is no config file, no
   command-line flag and no default password.
3. **The password never leaves the process.** It is sent only in the login request,
   and every error message and tool response is scrubbed of the password and the
   email before it is returned (the tests assert this with sentinel values).
4. **One sign-in, one renewal.** The session cookie lives in memory; a 401 triggers
   exactly one fresh sign-in and one retry, then a readable error.
5. **Starts are local-only and rate-capped**: one `greenlit_start_run` per 10
   seconds, and nothing remote.
6. **Do not put the password in a repository.** Keep it in your MCP client's own
   environment or secret store; this repository's `.gitignore` already excludes
   `.env`.

## Client configuration (stdio)

Install the one dependency from the repository root, on the machine that runs the
MCP client:

```bash
python -m pip install -r mcp_server/requirements.txt
```

Then point your client at the module. Replace `/path/to/greenlit` with the checkout
and `XXXX` with the password of the dedicated account:

```json
{
  "mcpServers": {
    "greenlit": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/greenlit",
        "GREENLIT_URL": "http://localhost:8003",
        "GREENLIT_EMAIL": "mcp-reader@example.com",
        "GREENLIT_PASSWORD": "XXXX"
      }
    }
  }
}
```

Add `"GREENLIT_MCP_ALLOW_START": "1"` to `env` to list the start tool at all; without
it the tool is not registered and cannot be called.

The server logs nothing and prints nothing on stdout except the MCP protocol, so the
credentials cannot leak through a log line.

## Example conversation

```
You:  List my GreenLit projects.
      → greenlit_list_projects → one project ("Default project"), dataset_count 4, run_count 11
You:  Start a quality run on my local demo app (http://localhost:9301/chat) with dataset 5555…
      → greenlit_start_run → run_id 1111…, state "queued"   (needs GREENLIT_MCP_ALLOW_START=1)
You:  Is it finished?
      → greenlit_get_run_status → state "running", counts: 4 answered, 0 failed, 6 not run
You:  What is the verdict?
      → greenlit_get_verdict → NO-GO, weighted score 0.42, headline "answer_match scored 0.42, below its threshold of 0.80."
You:  Give me the CSV report.
      → greenlit_get_report(format="csv") → case-level rows, "truncated": false
```

`greenlit_get_verdict` reports `"reasons": null` with a note: the API returns one
plain-language reason (`verdict_reason`) and no separate reasons list yet, so the
headline is the whole explanation rather than a fabricated breakdown.

## Tests

```bash
python -m pytest mcp_server/tests -q      # needs mcp, pytest (see requirements.txt)
python -m mypy --strict mcp_server/client.py mcp_server/server.py \
  mcp_server/__main__.py mcp_server/__init__.py
python -m ruff check --config backend/pyproject.toml mcp_server
python -m ruff format --config backend/pyproject.toml --check mcp_server
```

The 16 tests drive the tools through the SDK's in-memory client against a local fake
GreenLit HTTP server — no real network, no GreenLit process. They prove: the five
read-only tools are listed and `greenlit_start_run` appears only with the flag; the
input schemas require `run_id` and enumerate the report formats; bad input is
rejected; the password and email never appear in any tool output or error; a 401
causes exactly one re-login; a remote target is refused; a 250,000-character report
is truncated at the cap with the flag; and 404/500/401 map to readable errors naming
the status and path.
