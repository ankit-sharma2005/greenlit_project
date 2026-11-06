"""A local MCP server (Streamable HTTP) for the MCP target tests.

It speaks just enough of the protocol for GreenLit's client: ``initialize``, the
``notifications/initialized`` note, ``tools/list`` and ``tools/call``, answering
either a plain JSON body or an SSE stream. Every switch the tests need (an error
result, a JSON-RPC error, a forgotten session, a 405, an oversized answer, a
cross-host redirect) is an attribute, so one small server covers the whole list
without a dozen handlers.

The server is local only: it binds 127.0.0.1 on a free port and never talks to
anything else.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

PROTOCOL_VERSION = "2025-06-18"

DEFAULT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search",
        "description": "Search the helpdesk knowledge base",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
    },
    {
        "name": "compare",
        "description": "Compare two documents",
        "inputSchema": {
            "type": "object",
            "properties": {"left": {"type": "string"}, "right": {"type": "string"}},
            "required": ["left", "right"],
        },
    },
]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        return

    @property
    def mock(self) -> MockMcpServer:
        return self.server.mock  # type: ignore[attr-defined]

    # -- helpers -----------------------------------------------------------
    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            parsed = json.loads(raw or b"{}")
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _send(self, status: int, payload: Any, *, session: str | None = None) -> None:
        mock = self.mock
        if mock.transport == "sse":
            body = f"event: message\ndata: {json.dumps(payload)}\n\n".encode()
            content_type = "text/event-stream"
        else:
            body = json.dumps(payload).encode()
            content_type = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if session:
            self.send_header("Mcp-Session-Id", session)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _session_ok(self) -> bool:
        mock = self.mock
        if mock.deny_sessions:
            return True
        return (self.headers.get("Mcp-Session-Id") or "") == mock.session_id and not mock.expired

    # -- routes ------------------------------------------------------------
    def do_DELETE(self) -> None:
        self.mock.deletes += 1
        self._empty(204)

    def do_POST(self) -> None:
        mock = self.mock
        message = self._body()
        mock.requests.append(
            {"message": message, "headers": {k.lower(): v for k, v in dict(self.headers).items()}}
        )
        if mock.redirect_location:
            self.send_response(302)
            self.send_header("Location", mock.redirect_location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mock.status is not None:
            self._send(mock.status, {"detail": mock.secret or f"HTTP {mock.status}"})
            return
        method = message.get("method")
        if method == "initialize":
            mock.initializations += 1
            if mock.initialize_status is not None:
                self._send(mock.initialize_status, {"detail": "not an MCP endpoint"})
                return
            mock.session_id = f"sess-{mock.initializations}"
            mock.expired = False
            self._send(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mock-mcp", "version": "0.1"},
                    },
                },
                session=mock.session_id,
            )
            return
        if method == "notifications/initialized":
            self._empty(202)
            return
        if method == "tools/list":
            if not self._session_ok():
                self._empty(404)
                return
            self._send(
                200,
                {"jsonrpc": "2.0", "id": message.get("id"), "result": {"tools": mock.tools}},
            )
            return
        if method == "tools/call":
            mock.tool_calls += 1
            if mock.expire_first_call:
                # The server forgot the session: one 404, then a fresh one works.
                mock.expire_first_call = False
                mock.expired = True
                self._empty(404)
                return
            if mock.always_404 or not self._session_ok():
                self._empty(404)
                return
            if mock.rpc_error is not None:
                self._send(
                    200,
                    {"jsonrpc": "2.0", "id": message.get("id"), "error": mock.rpc_error},
                )
                return
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            mock.calls.append(dict(arguments))
            texts = list(mock.tool_texts)
            if mock.secret:
                texts.append(f"the key you sent was {mock.secret}")
            content: list[dict[str, Any]] = [{"type": "text", "text": text} for text in texts]
            content.append({"type": "image", "data": "…", "mimeType": "image/png"})
            self._send(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "result": {"content": content, "isError": mock.is_error},
                },
            )
            return
        self._send(400, {"detail": f"unknown method {method}"})


class _Server(ThreadingHTTPServer):
    mock: MockMcpServer


class MockMcpServer:
    """A configurable MCP server on 127.0.0.1, started and stopped by the test."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(self, *, transport: str = "json") -> None:
        self.transport = transport
        self.tools: list[dict[str, Any]] = [dict(tool) for tool in DEFAULT_TOOLS]
        self.tool_texts: list[str] = ["Hello", "world"]
        self.is_error = False
        self.rpc_error: dict[str, Any] | None = None
        self.status: int | None = None
        self.initialize_status: int | None = None
        self.expire_first_call = False
        self.always_404 = False
        self.redirect_location: str | None = None
        self.secret: str | None = None
        self.deny_sessions = False
        self.session_id = "sess-0"
        self.expired = False
        self.initializations = 0
        self.tool_calls = 0
        self.deletes = 0
        self.calls: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> MockMcpServer:
        server = _Server(("127.0.0.1", 0), _Handler)
        server.mock = self
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def __enter__(self) -> MockMcpServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- addresses ---------------------------------------------------------
    @property
    def port(self) -> int:
        assert self._server is not None, "server is not running"
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    @property
    def other_host_url(self) -> str:
        """The same port under a different hostname, for the redirect test."""
        return f"http://localhost:{self.port}/elsewhere"
