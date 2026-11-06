"""The MCP server as a test target: schema, snapshot, fingerprint and routes.

The rules a run follows are the HTTP target's (permission for a remote server, a
bound check before a full run, no private URLs unless the target is local), so
these tests concentrate on what is new: the tool call itself, the arguments, the
snapshot keys and the discovery endpoint.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas.runs import RunCreateRequest
from app.services import target_check
from app.services.mcp_client import McpToolSender
from app.services.run_executor import build_sender
from app.services.run_service import RunServiceError, build_snapshot
from tests.support.mcp_server import MockMcpServer

PASSWORD = "correct horse battery staple"
SECRET = "sk-live-SENTINEL-do-not-print-0123456789"


def register(client: TestClient, email: str = "mcp@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "MCP tester", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def mcp_payload(url: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target": url,
        "allow_private_targets": True,
        "mcp_tool": "search",
        "mcp_question_arg": "query",
        "timeout_seconds": 10,
        "max_retries": 0,
    }
    payload.update(overrides)
    return payload


def tools_payload(url: str, **overrides: Any) -> dict[str, Any]:
    """Discovery takes the connection settings only: no tool is chosen yet."""
    payload: dict[str, Any] = {
        "target": url,
        "allow_private_targets": True,
        "timeout_seconds": 10,
        "max_retries": 0,
    }
    payload.update(overrides)
    return payload


def mcp_snapshot(url: str, **overrides: Any) -> dict[str, Any]:
    payload = RunCreateRequest(entry_point="mcp_server", **mcp_payload(url, **overrides))
    return build_snapshot(payload, dataset_version_id=None, entry_point="mcp_server")


@pytest.fixture
def server() -> Iterator[MockMcpServer]:
    with MockMcpServer() as running:
        yield running


# -- schema ---------------------------------------------------------------
def test_there_is_no_stdio_field_to_fill_in() -> None:
    for forbidden in ({"mcp_transport": "stdio"}, {"mcp_command": "npx server"}, {"mcp_args": []}):
        with pytest.raises(ValidationError):
            RunCreateRequest(
                entry_point="mcp_server",
                target="http://127.0.0.1:9/mcp",
                **forbidden,
            )


def test_extra_arguments_are_bounded() -> None:
    with pytest.raises(ValidationError):
        RunCreateRequest(
            entry_point="mcp_server",
            target="http://127.0.0.1:9/mcp",
            mcp_extra_args={f"k{index}": "v" for index in range(41)},
        )
    with pytest.raises(ValidationError):
        RunCreateRequest(
            entry_point="mcp_server",
            target="http://127.0.0.1:9/mcp",
            mcp_extra_args={"blob": "x" * 9_000},
        )


def test_a_question_argument_must_be_a_plain_name() -> None:
    with pytest.raises(ValidationError):
        RunCreateRequest(
            entry_point="mcp_server",
            target="http://127.0.0.1:9/mcp",
            mcp_question_arg="query/../body",
        )


# -- snapshot -------------------------------------------------------------
def test_the_snapshot_carries_the_tool_and_its_arguments() -> None:
    snapshot = mcp_snapshot(
        "http://127.0.0.1:9/mcp", mcp_extra_args={"locale": "en"}, header_names=["Authorization"]
    )

    assert snapshot["entry_point"] == "mcp_server"
    assert snapshot["mcp_tool"] == "search"
    assert snapshot["mcp_question_arg"] == "query"
    assert snapshot["mcp_extra_args"] == {"locale": "en"}
    assert snapshot["header_names"] == ["Authorization"]
    assert snapshot["allow_private_targets"] is True
    # No permission record is invented for a target on this computer.
    assert "permission_confirmed" not in snapshot


def test_a_missing_tool_is_refused_before_a_run_can_start() -> None:
    payload = RunCreateRequest(entry_point="mcp_server", target="http://127.0.0.1:9/mcp")
    with pytest.raises(RunServiceError) as caught:
        build_snapshot(payload, dataset_version_id=None, entry_point="mcp_server")
    assert caught.value.status == 422


def test_a_remote_mcp_server_needs_permission() -> None:
    payload = RunCreateRequest(
        entry_point="mcp_server",
        target="http://127.0.0.1:9/mcp",
        mcp_tool="search",
        mcp_question_arg="query",
    )
    with pytest.raises(RunServiceError) as caught:
        build_snapshot(payload, dataset_version_id=None, entry_point="mcp_server")
    assert caught.value.status == 422
    assert "permission" in caught.value.message.lower()


def test_the_fingerprint_is_bound_to_the_tool_the_argument_and_the_extras() -> None:
    base = target_check.fingerprint(mcp_snapshot("http://127.0.0.1:9/mcp"))
    same = target_check.fingerprint(mcp_snapshot("http://127.0.0.1:9/mcp"))
    other_tool = target_check.fingerprint(
        mcp_snapshot("http://127.0.0.1:9/mcp", mcp_tool="compare")
    )
    other_arg = target_check.fingerprint(
        mcp_snapshot("http://127.0.0.1:9/mcp", mcp_question_arg="text")
    )
    other_extras = target_check.fingerprint(
        mcp_snapshot("http://127.0.0.1:9/mcp", mcp_extra_args={"locale": "de"})
    )

    assert base == same
    assert len({base, other_tool, other_arg, other_extras}) == 4


# -- the request a person is shown ---------------------------------------
def test_the_request_summary_masks_the_extra_argument_values() -> None:
    snapshot = mcp_snapshot(
        "http://127.0.0.1:9/mcp",
        mcp_extra_args={"api_key": SECRET},
        header_names=["Authorization"],
    )
    request = target_check._redacted_request(snapshot, "What is the refund policy?")
    rendered = str(request)

    assert request["tool"] == "search"
    assert request["arguments"]["api_key"] == "XXXX"
    assert request["arguments"]["query"] == "What is the refund policy?"
    assert SECRET not in rendered


# -- the executor's sender -----------------------------------------------
def test_build_sender_calls_the_tool_and_can_be_closed(server: MockMcpServer) -> None:
    snapshot = mcp_snapshot(server.url, mcp_extra_args={"locale": "en"})
    sender = build_sender(snapshot, session_factory=cast(Any, None))

    assert isinstance(sender, McpToolSender)
    trace = sender("How do I reset my password?")

    assert trace.output == "Hello\nworld"
    assert server.calls == [{"locale": "en", "query": "How do I reset my password?"}]
    sender.close()
    assert server.deletes == 1


# -- HTTP routes ---------------------------------------------------------
def test_the_tools_endpoint_lists_tools_and_audits(
    client: TestClient, server: MockMcpServer
) -> None:
    register(client)
    response = client.post("/api/v1/targets/mcp/tools", json=tools_payload(server.url))

    assert response.status_code == 200, response.text
    body = response.json()
    assert [tool["name"] for tool in body["tools"]] == ["search", "compare"]
    assert body["tools"][0]["suggested_question_arg"] == "query"
    assert body["server"] == "mock-mcp"
    assert server.tool_calls == 0, "discovery must not call a tool"

    audit = client.get("/api/v1/audit", params={"action": "target.mcp_tools"}).json()
    assert audit["total"] == 1
    assert audit["items"][0]["event_metadata"]["tools"] == 2


def test_a_remote_server_is_refused_before_a_tool_is_listed(
    client: TestClient, server: MockMcpServer
) -> None:
    register(client)
    response = client.post(
        "/api/v1/targets/mcp/tools",
        json=tools_payload(server.url, allow_private_targets=False),
    )

    assert response.status_code == 422
    assert "permission" in response.json()["error"]["message"].lower()
    assert server.requests == [], "nothing may be sent before the permission is recorded"


def test_the_check_endpoint_calls_the_tool_once(client: TestClient, server: MockMcpServer) -> None:
    register(client)
    response = client.post(
        "/api/v1/targets/check",
        json={
            **mcp_payload(server.url),
            "entry_point": "mcp_server",
            "mcp_extra_args": {"locale": "en"},
            "header_names": ["Authorization"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Hello\nworld"
    assert body["extraction_ok"] is True
    assert body["request"]["tool"] == "search"
    assert body["request"]["arguments"]["locale"] == "XXXX"
    assert server.tool_calls == 1


def test_a_tool_error_reaches_the_check_as_a_structured_failure(
    client: TestClient, server: MockMcpServer
) -> None:
    register(client)
    server.is_error = True
    response = client.post(
        "/api/v1/targets/check",
        json={**mcp_payload(server.url), "entry_point": "mcp_server"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extraction_ok"] is False
    assert body["error"]["kind"] == "invalid_response"
    assert "reported an error" in body["error"]["message"]
