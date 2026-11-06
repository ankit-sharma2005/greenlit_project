"""The MCP client: JSON and SSE replies, sessions, and the failure kinds.

Every test drives the real client against a local mock MCP server, so the wire
format is exercised rather than mocked: the session header, the negotiated
protocol version, the text blocks of a tool result, and the four failures the
product needs to name (a tool error, a JSON-RPC error, an unsupported transport,
an expired session).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.services.connectors import ConnectorError
from app.services.error_kinds import INVALID_RESPONSE, OTHER, kind_for_code
from app.services.mcp_client import McpSession, normalize_tools
from tests.support.mcp_server import MockMcpServer


@pytest.fixture
def server() -> Iterator[MockMcpServer]:
    with MockMcpServer() as running:
        yield running


def session_for(server: MockMcpServer, **headers: str) -> McpSession:
    return McpSession(
        url=server.url,
        headers=dict(headers),
        timeout_seconds=5,
        allow_private_targets=True,
        max_retries=0,
    )


def test_initialize_happens_once_and_tools_list_is_normalized(server: MockMcpServer) -> None:
    session = session_for(server)
    tools = session.list_tools()
    session.list_tools()

    assert server.initializations == 1
    assert [tool["name"] for tool in tools] == ["search", "compare"]
    first, second = tools
    assert first["description"] == "Search the helpdesk knowledge base"
    assert first["required_arguments"] == ["query"]
    assert first["argument_names"] == ["query", "limit"]
    # Exactly one required string argument is the obvious question slot.
    assert first["suggested_question_arg"] == "query"
    # Two required strings are a choice, never a guess.
    assert second["suggested_question_arg"] is None


def test_the_session_headers_are_kept_and_echoed(server: MockMcpServer) -> None:
    session = session_for(server)
    session.call_tool("search", {"query": "hello"})

    calls = [entry for entry in server.requests if entry["message"].get("method") == "tools/call"]
    assert calls, "the tool call never reached the server"
    headers = calls[-1]["headers"]
    assert headers["mcp-session-id"] == server.session_id
    assert headers["mcp-protocol-version"] == "2025-06-18"
    assert headers["accept"] == "application/json, text/event-stream"


def test_a_tool_result_joins_its_text_blocks_and_counts_the_rest(
    server: MockMcpServer,
) -> None:
    server.tool_texts = ["Hello", "world"]
    session = session_for(server)
    trace = session.call_tool("search", {"query": "hello"})

    assert trace.output == "Hello\nworld"
    assert trace.raw["content_blocks"] == 3
    # The image block is counted, never scored as text.
    assert trace.raw["non_text_blocks"] == 1
    assert trace.status_code == 200
    assert server.calls == [{"query": "hello"}]


def test_an_sse_answer_is_understood(server: MockMcpServer) -> None:
    server.transport = "sse"
    session = session_for(server)
    tools = session.list_tools()
    trace = session.call_tool("search", {"query": "hi"})

    assert [tool["name"] for tool in tools] == ["search", "compare"]
    assert trace.output == "Hello\nworld"


def test_a_tool_error_is_a_structured_failure(server: MockMcpServer) -> None:
    server.is_error = True
    session = session_for(server)
    with pytest.raises(ConnectorError) as caught:
        session.call_tool("search", {"query": "hi"})

    assert caught.value.code == "mcp_tool_error"
    assert kind_for_code(caught.value.code) == INVALID_RESPONSE
    assert "reported an error" in caught.value.message


def test_a_json_rpc_error_keeps_its_code(server: MockMcpServer) -> None:
    server.rpc_error = {"code": -32602, "message": "Unknown tool: nope"}
    session = session_for(server)
    with pytest.raises(ConnectorError) as caught:
        session.call_tool("nope", {})

    assert caught.value.code == "mcp_protocol_error"
    assert caught.value.details["rpc_code"] == -32602
    assert "Unknown tool" in caught.value.message


def test_a_forgotten_session_is_re_initialised_once(server: MockMcpServer) -> None:
    server.expire_first_call = True
    session = session_for(server)
    trace = session.call_tool("search", {"query": "hi"})

    assert trace.output == "Hello\nworld"
    assert server.initializations == 2


def test_a_second_404_is_a_session_expired_failure(server: MockMcpServer) -> None:
    server.always_404 = True
    session = session_for(server)
    with pytest.raises(ConnectorError) as caught:
        session.call_tool("search", {"query": "hi"})

    assert caught.value.code == "mcp_session_expired"
    assert server.initializations == 2


def test_a_405_names_the_transport_it_cannot_use(server: MockMcpServer) -> None:
    server.status = 405
    session = session_for(server)
    with pytest.raises(ConnectorError) as caught:
        session.call_tool("search", {"query": "hi"})

    assert caught.value.code == "mcp_transport_unsupported"
    assert kind_for_code(caught.value.code) == OTHER
    assert "stdio" in caught.value.message
    assert "HTTP+SSE" in caught.value.message


def test_an_oversized_answer_is_capped(server: MockMcpServer) -> None:
    server.tool_texts = ["x" * 150_000]
    session = session_for(server)
    trace = session.call_tool("search", {"query": "hi"})

    assert len(trace.output.encode("utf-8")) <= 100_000
    assert trace.raw["truncated"] is True


def test_descriptions_are_one_bounded_line() -> None:
    tools = normalize_tools(
        [
            {
                "name": "noisy",
                "description": "<script>alert(1)</script>\n\n" + "y" * 500,
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
    )
    description = tools[0]["description"]
    assert len(description) <= 300
    assert "\n" not in description
    # The markup is data: it is kept as text and never interpreted here.
    assert description.startswith("<script>alert(1)</script>")


def test_a_secret_never_appears_in_an_error_or_a_trace(server: MockMcpServer) -> None:
    sentinel = "sk-mcp-secret-EXAMPLE-123456"
    server.secret = sentinel
    server.is_error = True
    session = session_for(server, Authorization=f"Bearer {sentinel}")

    with pytest.raises(ConnectorError) as caught:
        session.call_tool("search", {"query": "hi"})

    assert sentinel not in caught.value.message
    assert sentinel not in str(caught.value.details)


def test_a_cross_host_redirect_is_refused(server: MockMcpServer) -> None:
    server.redirect_location = server.other_host_url
    session = session_for(server)
    with pytest.raises(ConnectorError) as caught:
        session.list_tools()

    assert caught.value.code == "redirect_blocked"
    assert "another host" in caught.value.message


def test_closing_a_session_sends_one_delete(server: MockMcpServer) -> None:
    session = session_for(server)
    session.initialize()
    session.close()

    assert server.deletes == 1
