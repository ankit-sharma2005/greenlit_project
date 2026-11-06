"""A minimal MCP client for the "MCP server" test target (MCP Streamable HTTP).

GreenLit tests a tool, not a process: every case calls one chosen tool of an MCP
server over Streamable HTTP and scores the text it returns, exactly like an HTTP
endpoint answer. There is deliberately **no stdio transport** — nothing here can
start a command from a value a user typed — and no OAuth flow.

The protocol work is small and explicit rather than delegated to an SDK, because
the backend image does not ship the official ``mcp`` package and adding a runtime
dependency for four request types would buy nothing:

* ``initialize`` then the ``notifications/initialized`` notification, once per
  session, keeping the ``Mcp-Session-Id`` the server hands back;
* ``tools/list`` (the tool picker) and ``tools/call`` (one case);
* an ``MCP-Protocol-Version`` header once the version is negotiated;
* either a plain ``application/json`` reply or an SSE stream, since a server may
  answer the same request in both shapes.

Everything on the wire goes through :class:`app.utils.request_client.RequestClient`,
so the SSRF guard, same-host redirect rule, ``Retry-After`` handling, retry
counting and deadlines are the HTTP connector's, not a second implementation.
Tool names, descriptions and results are untrusted text: this module reads them
as data, truncates them and never executes or interpolates them into a request.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.connectors import ConnectorError, Trace, _connection_failure, _http_failure
from app.services.target_error import redact_snippet, target_of
from app.utils.request_client import (
    BlockedPrivateURLError,
    RedirectBlockedError,
    RequestClient,
    RequestDeadlineExceededError,
    RequestInterruptedError,
    TooManyRedirectsError,
)

# The revision this client speaks. A server may negotiate an older one; whatever
# it names is what the following requests declare, because the spec requires the
# header to match what was agreed.
MCP_PROTOCOL_VERSION = "2025-06-18"
ACCEPT_HEADER = "application/json, text/event-stream"

MAX_TOOLS = 50
MAX_TOOL_DESCRIPTION = 300
# A tool answer is scored text, like an HTTP answer: the same 100 KB ceiling.
MAX_TOOL_TEXT_BYTES = 100_000
# A JSON-RPC envelope is small; anything past this is not a reply we can read.
MAX_BODY_BYTES = 1_000_000

_SESSION_HEADER = "mcp-session-id"
_PROTOCOL_HEADER = "MCP-Protocol-Version"

_TRANSPORT_HINT = (
    "this server may use the older HTTP+SSE transport or stdio, which GreenLit does not "
    "support; point GreenLit at the same URL your MCP client uses with the streamable HTTP "
    "transport"
)


@dataclass
class _Reply:
    """One HTTP reply: the status, the JSON-RPC message it carried, and the id."""

    status: int
    message: dict[str, Any] | None
    session_id: str | None
    snippet: str


def _bounded_text(raw: bytes) -> str:
    """A body as text, cut at the ceiling so one server cannot exhaust memory."""
    if len(raw) > MAX_BODY_BYTES:
        raw = raw[:MAX_BODY_BYTES]
    return raw.decode("utf-8", errors="replace")


def _sse_message(text: str) -> dict[str, Any] | None:
    """The JSON-RPC message in an SSE answer (the last complete one wins)."""
    found: dict[str, Any] | None = None
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = [line[5:].strip() for line in block.split("\n") if line.startswith("data:")]
        if not data:
            continue
        try:
            parsed = json.loads("\n".join(data))
        except ValueError:
            continue
        if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
            found = parsed
    return found


def _message_from(content_type: str, text: str) -> dict[str, Any] | None:
    """The JSON-RPC message in either supported answer shape."""
    if "text/event-stream" in content_type.lower():
        return _sse_message(text)
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _truncate_bytes(text: str, limit: int) -> tuple[str, bool]:
    """Cut text at a UTF-8 byte limit without splitting a character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore").rstrip(), True


def clean_description(value: Any) -> str:
    """A tool description as one bounded line of plain text, never as markup."""
    if not isinstance(value, str):
        return ""
    collapsed = " ".join(value.split())
    if len(collapsed) > MAX_TOOL_DESCRIPTION:
        return collapsed[: MAX_TOOL_DESCRIPTION - 1].rstrip() + "…"
    return collapsed


def normalize_tools(tools: Any) -> list[dict[str, Any]]:
    """The tool list a picker can show: bounded, plain text, with no surprises.

    Only names, a truncated description and the argument names travel onward; the
    raw schema is not echoed back, so a server cannot stuff a page with markup or
    a huge document.
    """
    if not isinstance(tools, list):
        return []
    normalized: list[dict[str, Any]] = []
    for tool in tools[:MAX_TOOLS]:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        raw_schema = tool.get("inputSchema")
        schema: dict[str, Any] = raw_schema if isinstance(raw_schema, dict) else {}
        raw_properties = schema.get("properties")
        properties: dict[str, Any] = raw_properties if isinstance(raw_properties, dict) else {}
        raw_required = schema.get("required")
        required = (
            [str(item) for item in raw_required if isinstance(item, str)]
            if isinstance(raw_required, list)
            else []
        )
        string_required = [
            argument
            for argument in required
            if isinstance(properties.get(argument), dict)
            and str(properties[argument].get("type") or "") == "string"
        ]
        normalized.append(
            {
                "name": name,
                "description": clean_description(tool.get("description")),
                "required_arguments": required,
                "string_arguments": string_required,
                "argument_names": [str(key) for key in properties],
                # Exactly one required string argument is the obvious question slot;
                # two means the person must choose rather than be guessed at.
                "suggested_question_arg": string_required[0] if len(string_required) == 1 else None,
            }
        )
    return normalized


def _non_text_blocks(result: dict[str, Any]) -> int:
    content = result.get("content")
    if not isinstance(content, list):
        return 0
    return sum(
        1 for block in content if not (isinstance(block, dict) and block.get("type") == "text")
    )


def _result_text(result: dict[str, Any]) -> tuple[str, bool]:
    """The text content blocks joined; images and audio are counted, not scored."""
    content = result.get("content")
    pieces: list[str] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str) and text:
                pieces.append(text)
    elif isinstance(result.get("structuredContent"), dict):
        # No content blocks: fall back to the structured payload as JSON text.
        pieces.append(json.dumps(result["structuredContent"], sort_keys=True, default=str))
    return _truncate_bytes("\n".join(pieces), MAX_TOOL_TEXT_BYTES)


def _protocol_error(error: Any, url: str, snippet: str | None = None) -> ConnectorError:
    """A JSON-RPC error reply as a structured failure with its code."""
    code: Any = None
    detail = ""
    if isinstance(error, dict):
        code = error.get("code")
        detail = str(error.get("message") or "")
    elif error is not None:
        detail = str(error)
    detail = redact_snippet(detail) or "no message"
    label = code if code is not None else "?"
    message = f"the MCP server returned a JSON-RPC error ({label}): {detail}"
    details: dict[str, Any] = {
        "target": target_of(url),
        "rpc_code": code if isinstance(code, int) else None,
        "snippet": snippet or detail,
        "message": message,
    }
    return ConnectorError(message, code="mcp_protocol_error", details=details)


def _unsupported(status: int, url: str) -> ConnectorError:
    """404/405 to a JSON-RPC POST: this is not a streamable-HTTP endpoint."""
    message = f"the MCP server answered HTTP {status}; {_TRANSPORT_HINT}"
    return ConnectorError(
        message,
        code="mcp_transport_unsupported",
        details={
            "status_code": status,
            "target": target_of(url),
            "message": message,
        },
    )


class McpSession:
    """One MCP session over Streamable HTTP, initialised once and then reused."""

    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 60,
        allow_private_targets: bool = False,
        max_retries: int = 3,
        item_budget_seconds: float = 150.0,
        interrupt: threading.Event | None = None,
        protocol_version: str = MCP_PROTOCOL_VERSION,
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.timeout_seconds = timeout_seconds
        self.item_budget_seconds = item_budget_seconds
        self.interrupt = interrupt
        self.protocol_version = protocol_version
        self.session_id: str | None = None
        self.server_info: dict[str, Any] = {}
        self.initializations = 0
        self.client = RequestClient(
            allow_private_targets=allow_private_targets, max_retries=max_retries
        )
        self._lock = threading.Lock()
        self._initialized = False
        self._id = 0

    # -- transport ---------------------------------------------------------
    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _post(self, message: dict[str, Any]) -> _Reply:
        """POST one JSON-RPC message and read its reply (JSON or SSE)."""
        headers = {
            "Content-Type": "application/json",
            "Accept": ACCEPT_HEADER,
            **self.headers,
        }
        if self.session_id:
            headers[_SESSION_HEADER] = self.session_id
        if self._initialized:
            headers[_PROTOCOL_HEADER] = self.protocol_version
        try:
            with self.client.stream(
                "POST",
                self.url,
                json=message,
                headers=headers,
                timeout=self.timeout_seconds,
                interrupt=self.interrupt,
            ) as response:
                status = response.status_code
                content_type = response.headers.get("content-type") or ""
                raw = b""
                for chunk in response.iter_bytes():
                    raw += chunk
                    if len(raw) >= MAX_BODY_BYTES:
                        break
                session_id = response.headers.get(_SESSION_HEADER)
        except RequestInterruptedError as exc:
            raise ConnectorError(
                "this case was cancelled before the MCP server answered",
                code="cancelled",
                details={"target": target_of(self.url), "message": "cancelled"},
            ) from exc
        except RequestDeadlineExceededError as exc:
            budget = self.item_budget_seconds
            message_text = f"this case hit the {budget:g} s budget and was stopped"
            raise ConnectorError(
                message_text,
                code="timeout",
                details={
                    "target": target_of(self.url),
                    "timeout_seconds": budget,
                    "message": message_text,
                },
            ) from exc
        except httpx.TimeoutException as exc:
            message_text = (
                f"the MCP server did not answer within {self.timeout_seconds} s; increase the "
                "timeout or speed the server up"
            )
            raise ConnectorError(
                message_text,
                code="timeout",
                details={
                    "target": target_of(self.url),
                    "timeout_seconds": self.timeout_seconds,
                    "message": message_text,
                },
            ) from exc
        except RedirectBlockedError as exc:
            message_text = (
                f"the MCP server redirected to another host ({exc.target_host}); GreenLit "
                "follows only redirects that stay on the host you typed"
            )
            raise ConnectorError(
                message_text,
                code="redirect_blocked",
                details={"target": target_of(self.url), "message": message_text},
            ) from exc
        except TooManyRedirectsError as exc:
            message_text = "the MCP server redirected too many times; check the URL"
            raise ConnectorError(
                message_text,
                code="redirect_loop",
                details={"target": target_of(self.url), "message": message_text},
            ) from exc
        except BlockedPrivateURLError as exc:
            message_text = (
                "this URL points inside a private network; mark the target as running on your "
                "own computer to test it"
            )
            raise ConnectorError(
                message_text,
                code="connector_error",
                details={"target": target_of(self.url), "message": message_text},
            ) from exc
        except httpx.HTTPError as exc:
            raise _connection_failure(exc, self.url) from exc
        text = _bounded_text(raw)
        return _Reply(
            status=status,
            message=_message_from(content_type, text),
            session_id=session_id,
            snippet=redact_snippet(text),
        )

    def _notify(self, method: str) -> None:
        """A JSON-RPC notification: no id, and its 202 has no body to read."""
        try:
            self._post({"jsonrpc": "2.0", "method": method})
        except ConnectorError:
            # The spec allows the server to have already taken the session; a
            # failed courtesy note must not fail the run.
            return

    # -- protocol ----------------------------------------------------------
    def initialize(self) -> None:
        """Negotiate the protocol once for this session."""
        with self._lock:
            if self._initialized:
                return
            self.initializations += 1
            reply = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "greenlit", "version": "1.0"},
                    },
                }
            )
            if reply.status in (404, 405):
                raise _unsupported(reply.status, self.url)
            if not 200 <= reply.status < 300:
                raise _http_failure(reply.status, reply.snippet, target_of(self.url))
            message = reply.message
            if message is None:
                raise _unsupported(reply.status, self.url)
            if "error" in message:
                raise _protocol_error(message.get("error"), self.url)
            raw_result = message.get("result")
            result: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}
            self.session_id = reply.session_id or self.session_id
            negotiated = result.get("protocolVersion")
            if isinstance(negotiated, str) and negotiated.strip():
                self.protocol_version = negotiated.strip()
            info = result.get("serverInfo")
            self.server_info = info if isinstance(info, dict) else {}
            self._initialized = True
            self._notify("notifications/initialized")

    def _expire(self) -> None:
        """Forget the session so the next call initialises a fresh one."""
        with self._lock:
            self._initialized = False
            self.session_id = None

    def list_tools(self) -> list[dict[str, Any]]:
        """The server's tools, normalized for the picker."""
        self.initialize()
        reply = self._post(
            {"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}}
        )
        if reply.status in (404, 405):
            raise _unsupported(reply.status, self.url)
        if not 200 <= reply.status < 300:
            raise _http_failure(reply.status, reply.snippet, target_of(self.url))
        if reply.message is None or "result" not in reply.message:
            raise _protocol_error(
                (reply.message or {}).get("error"), self.url, snippet=reply.snippet
            )
        result = reply.message.get("result")
        tools = result.get("tools") if isinstance(result, dict) else None
        return normalize_tools(tools)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Trace:
        """Call one tool once and score the text it returns."""
        self.initialize()
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        started = time.monotonic()
        reply = self._post(message)
        if reply.status == 404:
            # A server may forget a session; re-initialise once and try again.
            self._expire()
            self.initialize()
            message["id"] = self._next_id()
            reply = self._post(message)
            if reply.status == 404:
                raise ConnectorError(
                    "the MCP server closed the session and a fresh one was refused too; "
                    "check that the server is healthy, then run the check again",
                    code="mcp_session_expired",
                    details={"status_code": reply.status, "target": target_of(self.url)},
                )
        if reply.status == 405:
            raise _unsupported(reply.status, self.url)
        if not 200 <= reply.status < 300:
            raise _http_failure(reply.status, reply.snippet, target_of(self.url))
        if reply.message is None:
            raise ConnectorError(
                "the MCP server's answer was not a JSON-RPC message",
                code="mcp_protocol_error",
                details={"status_code": reply.status, "target": target_of(self.url)},
            )
        if "error" in reply.message:
            raise _protocol_error(reply.message.get("error"), self.url, snippet=reply.snippet)
        result = reply.message.get("result")
        result = result if isinstance(result, dict) else {}
        # The final attempt alone, like the HTTP connector: a retried case must
        # not look slow because the server said "not now" twice.
        attempt = self.client.last_attempt_seconds or (time.monotonic() - started)
        latency_ms = int(attempt * 1000)
        text, truncated = _result_text(result)
        if bool(result.get("isError")):
            snippet = redact_snippet(text) or "no message"
            raise ConnectorError(
                f"the MCP tool reported an error: {snippet}",
                code="mcp_tool_error",
                details={
                    "status_code": reply.status,
                    "target": target_of(self.url),
                    "snippet": snippet,
                },
            )
        content = result.get("content")
        raw = {
            "tool": name,
            "content_blocks": len(content) if isinstance(content, list) else 0,
            "non_text_blocks": _non_text_blocks(result),
            "truncated": truncated,
            "server": self.server_info.get("name"),
        }
        return Trace(
            output=text,
            retrieved_context="not instrumented",
            tool_calls=[name],
            latency_ms=latency_ms,
            tokens_in=None,
            tokens_out=None,
            error=None,
            raw=raw,
            retry_count=self.client.last_retry_count,
            waited_ms=int(self.client.last_waited_seconds * 1000),
            status_code=reply.status,
        )

    def close(self) -> None:
        """Best-effort session cleanup: the server may ignore it."""
        if not self.session_id:
            return
        headers = {_SESSION_HEADER: self.session_id, _PROTOCOL_HEADER: self.protocol_version}
        try:
            with self.client.stream("DELETE", self.url, headers=headers, timeout=5):
                pass
        except Exception:
            # A DELETE is a courtesy; an MCP server may not implement it at all.
            return


class McpToolSender:
    """The run's per-case callable: one tool, one question argument, once per case.

    The session is created once per run and reused for every case, so a dataset of
    fifty rows initialises the protocol once rather than fifty times. The extra
    arguments are copied at construction, so a later edit of the run's settings
    cannot change what a queued run sends.
    """

    def __init__(
        self,
        session: McpSession,
        tool: str,
        question_arg: str,
        extra_args: dict[str, Any] | None = None,
    ) -> None:
        self.session = session
        self.tool = tool
        self.question_arg = question_arg
        self.extra_args = dict(extra_args or {})

    def __call__(self, input_text: str) -> Trace:
        arguments: dict[str, Any] = {**self.extra_args, self.question_arg: input_text}
        return self.session.call_tool(self.tool, arguments)

    def close(self) -> None:
        self.session.close()
