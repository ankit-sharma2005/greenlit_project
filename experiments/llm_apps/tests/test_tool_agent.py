"""A4: the MCP tool-agent, unit-tested and through the official SDK client.

Run with the app's own virtualenv, which is the only place the ``mcp`` package is
installed: ``experiments/llm_apps/.venv/Scripts/python -m pytest``.
"""

from __future__ import annotations

import asyncio
import builtins
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from fake_llm import FakeLLM
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from tool_agent.server import (
    UnsafeExpression,
    assistant_answer,
    order_lookup,
    safe_evaluate,
)

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
UNSAFE = (
    "__import__('os').system('echo x')",
    "().__class__",
    "x + 1",
    "open('/etc/passwd').read()",
    "2 ** 999",
    "1/0",
    "1" * 121,
)


def test_the_calculator_does_arithmetic() -> None:
    assert safe_evaluate("2+2") == 4
    assert safe_evaluate("(3*4)-5") == 7
    assert safe_evaluate("2**3") == 8
    assert safe_evaluate("7/2") == 3.5
    assert safe_evaluate("-4 + 1.5") == -2.5


@pytest.mark.parametrize("expression", UNSAFE)
def test_the_calculator_refuses_anything_but_arithmetic(expression: str) -> None:
    with pytest.raises(UnsafeExpression):
        safe_evaluate(expression)


def test_the_order_lookup_knows_its_three_orders_and_says_when_it_does_not() -> None:
    assert "shipped" in order_lookup("ACME-1001")
    assert "not found" in order_lookup("ACME-9999")
    assert "not found" in order_lookup("")


def test_calculator_and_lookup_touch_no_file_and_no_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("this tool must not read a file or open a socket")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(socket, "socket", refuse)
    assert safe_evaluate("6*7") == 42
    assert "ACME-1002" in order_lookup("ACME-1002")


def test_the_assistant_goes_through_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with FakeLLM() as fake:
        monkeypatch.setenv("LLM_BASE_URL", fake.url)
        monkeypatch.setenv("LLM_MODEL", "fake-model")
        monkeypatch.setenv("APP_MODE", "guarded")
        answer = assistant_answer("When do you ship?")
    assert "user=When do you ship?" in answer
    assert fake.last["messages"][0]["role"] == "system"
    assert "INTERNAL-NOTE" not in fake.last["messages"][0]["content"]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise AssertionError("the MCP server did not start listening")


async def _round_trip(port: int, fake: FakeLLM) -> None:
    url = f"http://127.0.0.1:{port}/mcp"
    async with (
        streamablehttp_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        names = sorted(tool.name for tool in listed.tools)
        assert names == ["ask_assistant", "calculator", "lookup_order"]
        schemas = {tool.name: tool.inputSchema for tool in listed.tools}
        assert "expression" in json.dumps(schemas["calculator"])
        assert "order_id" in json.dumps(schemas["lookup_order"])

        added = await session.call_tool("calculator", {"expression": "19 + 23"})
        assert added.content[0].text == "42"
        refused = await session.call_tool(
            "calculator", {"expression": "__import__('os').system('echo x')"}
        )
        assert refused.content[0].text.startswith("Refused")
        missing = await session.call_tool("lookup_order", {"order_id": "ACME-7777"})
        assert "not found" in missing.content[0].text
        asked = await session.call_tool(
            "ask_assistant", {"question": "Where is my parcel?"}
        )
        assert asked.content[0].text
        assert "Where is my parcel?" in json.dumps(fake.requests[-1])


def test_a_real_mcp_client_lists_and_calls_all_three_tools() -> None:
    port = _free_port()
    with FakeLLM() as fake:
        environment = {
            **os.environ,
            "LLM_BASE_URL": fake.url,
            "LLM_MODEL": "fake-model",
            "APP_MODE": "guarded",
        }
        process = subprocess.Popen(
            [str(PYTHON), str(ROOT / "tool_agent" / "server.py"), "--port", str(port)],
            cwd=str(ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for(port)
            asyncio.run(_round_trip(port, fake))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
