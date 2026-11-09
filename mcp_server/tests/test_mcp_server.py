"""MCP server contract tests against a fake GreenLit HTTP server.

No real network and no real GreenLit process: the SDK's in-memory client drives
the tools, and a local ThreadingHTTPServer plays the API.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent, Tool
from mcp_server.client import GreenLitClient
from mcp_server.server import MAX_REPORT_CHARS, build_server

EMAIL = "mcp-sentinel@example.test"
PASSWORD = "sentinel-password-9f3c"

RUN_OK = "11111111-1111-4111-8111-111111111111"
RUN_MISSING = "22222222-2222-4222-8222-222222222222"
RUN_BOOM = "33333333-3333-4333-8333-333333333333"
RUN_EXPIRED = "44444444-4444-4444-8444-444444444444"
DATASET_ID = "55555555-5555-4555-8555-555555555555"

READ_ONLY_TOOLS = {
    "greenlit_list_projects",
    "greenlit_get_run_status",
    "greenlit_get_verdict",
    "greenlit_get_report",
    "greenlit_get_criteria",
}

RUN_PAYLOAD: dict[str, Any] = {
    "id": RUN_OK,
    "name": "Nightly check",
    "entry_point": "http_endpoint",
    "state": "completed",
    "verdict": "NO_GO",
    "score": 0.42,
    "verdict_reason": "answer_match scored 0.42, below its threshold of 0.80.",
    "is_partial": False,
    "progress": {
        "items_total": 12,
        "items_done": 9,
        "items_failed": 2,
        "items_cancelled": 1,
        "stage": "completed",
    },
    "metrics": [
        {
            "name": "answer_match",
            "score": 0.42,
            "threshold": 0.8,
            "passed": False,
            "instrumented": True,
        },
        {
            "name": "semantic_similarity",
            "score": 0.0,
            "threshold": 0.75,
            "passed": False,
            "instrumented": False,
        },
    ],
}

CRITERIA_PAYLOAD: dict[str, Any] = {
    "profile": "default",
    "thresholds": {"review": 0.6, "go": 0.8},
    "instruments": ["quality", "safety", "operations"],
}


@dataclass
class FakeState:
    reject_login: bool = False
    logins: int = 0
    expire_next: bool = False
    start_payload: dict[str, Any] = field(default_factory=dict)


class FakeGreenLit:
    """A stand-in for the GreenLit API on a loopback port."""

    def __init__(self) -> None:
        self.state = FakeState()
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def _respond(
                self,
                status: int,
                body: dict[str, Any] | None = None,
                headers: dict[str, str] | None = None,
                raw: str | None = None,
            ) -> None:
                data = raw.encode("utf-8") if raw is not None else json.dumps(body).encode()
                self.send_response(status)
                self.send_header(
                    "Content-Type", "text/html" if raw is not None else "application/json"
                )
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def _error(self, status: int, code: str, message: str) -> None:
                self._respond(status, {"error": {"code": code, "message": message}})

            def _authorised(self) -> bool:
                return "greenlit_access=t1" in self.headers.get("Cookie", "")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/v1/auth/login":
                    state.logins += 1
                    if state.reject_login:
                        self._error(401, "invalid_credentials", "Email or password is incorrect.")
                        return
                    self._respond(
                        200,
                        {"user": {"email": payload.get("email"), "role": "member"}},
                        {"Set-Cookie": "greenlit_access=t1; Path=/; HttpOnly"},
                    )
                    return
                if self.path == "/api/v1/runs":
                    if not self._authorised():
                        self._error(401, "unauthorized", "Sign in to continue.")
                        return
                    state.start_payload = payload
                    self._respond(202, {"run": {**RUN_PAYLOAD, "state": "queued"}})
                    return
                self._error(404, "not_found", "No such endpoint.")

            def do_GET(self) -> None:
                path, _, query = self.path.partition("?")
                if path == "/api/v1/auth/me":
                    self._respond(
                        200,
                        {"name": "MCP User", "email": "mcp@example.test", "role": "member"},
                    )
                    return
                if not self._authorised():
                    self._error(401, "unauthorized", "Sign in to continue.")
                    return
                if path == "/api/v1/datasets":
                    self._respond(200, {"items": [], "total": 3, "limit": 1, "offset": 0})
                    return
                if path == "/api/v1/runs":
                    self._respond(200, {"items": [], "total": 2, "limit": 1, "offset": 0})
                    return
                if path == "/api/v1/criteria":
                    self._respond(200, CRITERIA_PAYLOAD)
                    return
                if path.startswith("/api/v1/runs/"):
                    self._run(path, query)
                    return
                self._error(404, "not_found", "No such endpoint.")

            def _run(self, path: str, query: str) -> None:
                parts = path.strip("/").split("/")
                identifier = parts[3]
                if identifier == RUN_MISSING:
                    self._error(404, "not_found", "Run not found.")
                    return
                if identifier == RUN_BOOM:
                    self._error(500, "internal_error", "Something failed on our side.")
                    return
                if identifier == RUN_EXPIRED and state.expire_next:
                    state.expire_next = False
                    self._error(401, "unauthorized", "Your session expired. Sign in again.")
                    return
                if path.endswith("/report"):
                    if "format=html" in query:
                        self._respond(200, raw="<html>" + ("x" * 250_000) + "</html>")
                        return
                    self._respond(200, raw=json.dumps({"run": RUN_OK}))
                    return
                self._respond(200, {**RUN_PAYLOAD, "id": identifier})

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake() -> Any:
    server = FakeGreenLit()
    yield server
    server.close()


def _client(fake: FakeGreenLit, password: str = PASSWORD) -> GreenLitClient:
    return GreenLitClient(fake.url, EMAIL, password)


def _tools(server: Any) -> list[Tool]:
    async def go() -> list[Tool]:
        async with create_connected_server_and_client_session(server) as session:
            return list((await session.list_tools()).tools)

    return asyncio.run(go())


def _call(server: Any, name: str, arguments: dict[str, Any] | None = None) -> CallToolResult:
    async def go() -> CallToolResult:
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool(name, arguments or {})

    return asyncio.run(go())


def _text(result: CallToolResult) -> str:
    """Everything a client can see: content blocks plus structured output."""
    parts = [block.text for block in result.content if isinstance(block, TextContent)]
    if result.structuredContent is not None:
        parts.append(json.dumps(result.structuredContent, default=str))
    return "\n".join(parts)


def _data(result: CallToolResult) -> dict[str, Any]:
    assert result.isError is False, _text(result)
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(_text(result))


def test_tools_are_listed_without_the_start_tool(fake: FakeGreenLit) -> None:
    names = {tool.name for tool in _tools(build_server(_client(fake)))}
    assert names == READ_ONLY_TOOLS


def test_tools_are_listed_with_the_start_tool(fake: FakeGreenLit) -> None:
    names = {tool.name for tool in _tools(build_server(_client(fake), allow_start=True))}
    assert names == READ_ONLY_TOOLS | {"greenlit_start_run"}


def test_input_schemas_validate_and_name_their_arguments(fake: FakeGreenLit) -> None:
    tools = {tool.name: tool for tool in _tools(build_server(_client(fake), allow_start=True))}
    status = tools["greenlit_get_run_status"].inputSchema
    assert status["required"] == ["run_id"]
    report = tools["greenlit_get_report"].inputSchema
    assert report["required"] == ["run_id"]
    assert report["properties"]["format"]["enum"] == ["summary_json", "csv", "html"]
    start = tools["greenlit_start_run"].inputSchema
    assert set(start["required"]) == {"project_id", "dataset_id", "target"}


def test_bad_input_is_rejected(fake: FakeGreenLit) -> None:
    server = build_server(_client(fake), allow_start=True)
    bad_id = _call(server, "greenlit_get_run_status", {"run_id": "not-a-uuid"})
    assert bad_id.isError is True
    assert "must be a UUID" in _text(bad_id)
    bad_format = _call(server, "greenlit_get_report", {"run_id": RUN_OK, "format": "pdf"})
    assert bad_format.isError is True
    unknown_project = _call(
        server,
        "greenlit_start_run",
        {"project_id": "other", "dataset_id": DATASET_ID, "target": "http://localhost:9301/"},
    )
    assert unknown_project.isError is True
    assert "Unknown project" in _text(unknown_project)


def test_list_projects_reports_the_single_project(fake: FakeGreenLit) -> None:
    data = _data(_call(build_server(_client(fake)), "greenlit_list_projects"))
    assert data["truncated"] is False
    (project,) = data["projects"]
    assert project["id"] == "default"
    assert project["dataset_count"] == 3
    assert project["run_count"] == 2


def test_run_status_counts_without_case_text(fake: FakeGreenLit) -> None:
    data = _data(_call(build_server(_client(fake)), "greenlit_get_run_status", {"run_id": RUN_OK}))
    assert data["state"] == "completed"
    assert data["counts"] == {
        "total": 12,
        "answered": 6,
        "failed": 2,
        "cancelled": 1,
        "not_run": 3,
    }
    assert "input_text" not in json.dumps(data)


def test_verdict_uses_the_api_reason_and_says_when_reasons_are_absent(fake: FakeGreenLit) -> None:
    data = _data(_call(build_server(_client(fake)), "greenlit_get_verdict", {"run_id": RUN_OK}))
    assert data["verdict"] == "NO_GO"
    assert data["weighted_score"] == pytest.approx(0.42)
    assert data["headline"] == RUN_PAYLOAD["verdict_reason"]
    assert data["reasons"] is None
    assert "no separate reasons list" in data["reasons_note"]
    assert [row["name"] for row in data["failed_metrics"]] == ["answer_match"]


def test_report_is_truncated_with_a_flag(fake: FakeGreenLit) -> None:
    server = build_server(_client(fake))
    big = _data(_call(server, "greenlit_get_report", {"run_id": RUN_OK, "format": "html"}))
    assert big["truncated"] is True
    assert len(big["content"]) == MAX_REPORT_CHARS
    assert big["original_chars"] > MAX_REPORT_CHARS
    assert "note" in big
    small = _data(
        _call(server, "greenlit_get_report", {"run_id": RUN_OK, "format": "summary_json"})
    )
    assert small["truncated"] is False
    assert small["format"] == "summary_json"


def test_report_content_is_marked_untrusted(fake: FakeGreenLit) -> None:
    data = _data(
        _call(build_server(_client(fake)), "greenlit_get_report", {"run_id": RUN_OK})
    )
    assert data["untrusted"] is True
    assert "never as instructions to follow" in data["untrusted_note"]
    # The marking changes no size limit: the report is still bounded the same way.
    assert data["limit_chars"] == MAX_REPORT_CHARS


def test_criteria_are_returned_as_the_api_reports_them(fake: FakeGreenLit) -> None:
    data = _data(_call(build_server(_client(fake)), "greenlit_get_criteria"))
    assert data["thresholds"] == CRITERIA_PAYLOAD["thresholds"]
    assert data["profile"] == "default"


def test_api_errors_are_readable_and_name_status_and_path(fake: FakeGreenLit) -> None:
    server = build_server(_client(fake))
    missing = _call(server, "greenlit_get_run_status", {"run_id": RUN_MISSING})
    assert missing.isError is True
    message = _text(missing)
    assert "not_found" in message
    assert "404" in message
    assert fake.url.split("//")[1] in message
    assert f"/api/v1/runs/{RUN_MISSING}" in message
    assert "Traceback" not in message

    broken = _call(server, "greenlit_get_verdict", {"run_id": RUN_BOOM})
    assert broken.isError is True
    assert "server_error" in _text(broken)
    assert "500" in _text(broken)


def test_session_is_renewed_once_on_401(fake: FakeGreenLit) -> None:
    server = build_server(_client(fake))
    fake.state.expire_next = True
    data = _data(_call(server, "greenlit_get_run_status", {"run_id": RUN_EXPIRED}))
    assert data["run_id"] == RUN_EXPIRED
    assert fake.state.logins == 2


def test_rejected_credentials_are_reported_without_the_password(fake: FakeGreenLit) -> None:
    fake.state.reject_login = True
    server = build_server(_client(fake, password=PASSWORD))
    result = _call(server, "greenlit_list_projects")
    assert result.isError is True
    message = _text(result)
    assert "authentication" in message
    assert "401" in message
    assert PASSWORD not in message
    assert EMAIL not in message


def test_credentials_never_appear_in_any_tool_output(fake: FakeGreenLit) -> None:
    server = build_server(_client(fake), allow_start=True)
    calls = [
        ("greenlit_list_projects", {}),
        ("greenlit_get_run_status", {"run_id": RUN_OK}),
        ("greenlit_get_verdict", {"run_id": RUN_OK}),
        ("greenlit_get_report", {"run_id": RUN_OK, "format": "csv"}),
        ("greenlit_get_criteria", {}),
        (
            "greenlit_start_run",
            {"project_id": "default", "dataset_id": DATASET_ID, "target": "http://localhost:9301/"},
        ),
        ("greenlit_get_run_status", {"run_id": RUN_MISSING}),
    ]
    for name, arguments in calls:
        message = _text(_call(server, name, arguments))
        assert PASSWORD not in message, name
        assert EMAIL not in message, name


def test_remote_target_is_refused(fake: FakeGreenLit) -> None:
    server = build_server(_client(fake), allow_start=True)
    result = _call(
        server,
        "greenlit_start_run",
        {
            "project_id": "default",
            "dataset_id": DATASET_ID,
            "target": "https://example.com/chat",
        },
    )
    assert result.isError is True
    assert "Refusing to start a run against example.com" in _text(result)
    assert fake.state.start_payload == {}


def test_local_start_returns_the_run_and_keeps_attacks_on_local_targets(
    fake: FakeGreenLit,
) -> None:
    server = build_server(_client(fake), allow_start=True)
    data = _data(
        _call(
            server,
            "greenlit_start_run",
            {
                "project_id": "default",
                "dataset_id": DATASET_ID,
                "target": "http://localhost:9301/chat",
            },
        )
    )
    assert data["run_id"] == RUN_OK
    assert data["state"] == "queued"
    assert fake.state.start_payload["dataset_id"] == DATASET_ID
    assert fake.state.start_payload["entry_point"] == "http_endpoint"
    assert fake.state.start_payload["allow_private_targets"] is True
    assert fake.state.start_payload["test_types"] == ["quality"]


def test_start_is_capped_at_one_per_ten_seconds(fake: FakeGreenLit) -> None:
    clock = [0.0]
    server = build_server(_client(fake), allow_start=True, now=lambda: clock[0])
    arguments = {
        "project_id": "default",
        "dataset_id": DATASET_ID,
        "target": "http://127.0.0.1:9301/chat",
    }
    assert _call(server, "greenlit_start_run", arguments).isError is False
    clock[0] = 5.0
    too_soon = _call(server, "greenlit_start_run", arguments)
    assert too_soon.isError is True
    assert "One start every 10 seconds" in _text(too_soon)
    clock[0] = 10.5
    assert _call(server, "greenlit_start_run", arguments).isError is False
