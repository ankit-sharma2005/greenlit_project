"""Interop check: GreenLit's MCP client against the official SDK's FastMCP server.

This is a manual, dev-only check, not part of the test suite: the backend image
does not ship the official ``mcp`` package, and this file is deliberately not
named ``test_*`` so pytest never collects it. Run it in a throwaway venv that
has the SDK, with the backend importable::

    cd backend
    PYTHONPATH=. /path/to/sdk-venv/bin/python tests/support/mcp_interop_check.py

It starts a real FastMCP server with one tool, ``echo(text: str) -> str``, on a
free loopback port, then drives GreenLit's own client through ``initialize``,
``tools/list``, ``tools/call`` and ``close`` and prints what it got. A mismatch
exits non-zero, so a change in the SDK's behaviour is visible instead of silent.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time

import uvicorn
from mcp.server.fastmcp import FastMCP

from app.services.mcp_client import McpSession, McpToolSender


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def start_server(port: int) -> tuple[uvicorn.Server, threading.Thread]:
    server = FastMCP("interop", host="127.0.0.1", port=port)

    @server.tool()
    def echo(text: str) -> str:
        """Return the text it was given."""
        return text

    config = uvicorn.Config(
        server.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning"
    )
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not running.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not running.started:
        raise SystemExit("the SDK server did not start")
    return running, thread


def main() -> int:
    port = free_port()
    running, thread = start_server(port)
    url = f"http://127.0.0.1:{port}/mcp"
    failures: list[str] = []
    session = McpSession(url=url, timeout_seconds=20, allow_private_targets=True)
    try:
        session.initialize()
        print("INITIALIZE session_id:", session.session_id)
        print("INITIALIZE server_info:", json.dumps(session.server_info, sort_keys=True))
        print("INITIALIZE protocol:", session.protocol_version)

        tools = session.list_tools()
        print("TOOLS/LIST:", json.dumps(tools, indent=2, sort_keys=True))
        names = [tool["name"] for tool in tools]
        if names != ["echo"]:
            failures.append(f"tools/list returned {names!r}")

        sender = McpToolSender(session, tool="echo", question_arg="text")
        try:
            first = sender("hello from GreenLit")
            second = sender("second case")
        finally:
            sender.close()
        for trace, expected in ((first, "hello from GreenLit"), (second, "second case")):
            print("TOOLS/CALL:", json.dumps(trace.raw, sort_keys=True), repr(trace.output))
            if trace.error or trace.output != expected:
                failures.append(f"tools/call returned {trace.output!r} / {trace.error!r}")
        if session.initializations != 1:
            failures.append(f"session initialised {session.initializations} times")
    finally:
        running.should_exit = True
        thread.join(timeout=10)

    if failures:
        print("DISAGREEMENT:", "; ".join(failures))
        return 1
    print("AGREEMENT: the SDK server and GreenLit's client agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
