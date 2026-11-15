"""A4 — an MCP server over Streamable HTTP with exactly three tools.

* ``calculator(expression)`` — a whitelisted AST evaluator; no ``eval``, no names,
  no attribute access, no calls, and a length cap.
* ``lookup_order(order_id)`` — a small fixed table of invented orders.
* ``ask_assistant(question)`` — the support persona through the shared LLM client;
  it cannot call other tools, read files or reach the network.

No tool reads a file or opens a socket (the assistant's provider call is the one
network use, and it is the app's own client). Local test subject only: binds
127.0.0.1 by default and must never be exposed to the internet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.arithmetic import UnsafeExpression, format_number, safe_evaluate
from common.config import load_settings
from common.llm import LLMClient, LLMError, ProviderUnavailable
from common.prompts import system_prompt
from mcp.server.fastmcp import FastMCP

APP = "tool-agent"
DEFAULT_PORT = 9114

ORDERS: dict[str, dict[str, str]] = {
    "ACME-1001": {"status": "shipped", "items": "2 notebooks", "eta": "2 working days"},
    "ACME-1002": {
        "status": "processing",
        "items": "1 desk lamp",
        "eta": "4 working days",
    },
    "ACME-1003": {"status": "delayed", "items": "1 travel mug", "eta": "unknown"},
}


def order_lookup(order_id: str) -> str:
    """One invented order, or a clear not-found sentence."""
    order = ORDERS.get((order_id or "").strip().upper())
    if order is None:
        return f"Order {order_id} was not found."
    return (
        f"Order {order_id.strip().upper()}: {order['status']}, "
        f"items: {order['items']}, estimated delivery: {order['eta']}."
    )


def assistant_answer(question: str, settings: Any | None = None) -> str:
    """The support persona; the one place this server calls a model."""
    resolved = settings or load_settings()
    client = LLMClient(resolved)
    try:
        return client.chat(
            [
                {"role": "system", "content": system_prompt(resolved.mode)},
                {"role": "user", "content": question},
            ]
        )
    except ProviderUnavailable:
        return "The assistant is unavailable right now (provider_unavailable)."
    except LLMError:
        return "The assistant could not answer that right now."


def build_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    """The MCP server, with only the three tools this app advertises."""
    server = FastMCP(APP, host=host, port=port)

    @server.tool()
    def calculator(expression: str) -> str:
        """Evaluate a plain arithmetic expression (+ - * / // % ** and brackets)."""
        try:
            return format_number(safe_evaluate(expression))
        except UnsafeExpression as exc:
            return f"Refused: {exc}."

    @server.tool()
    def lookup_order(order_id: str) -> str:
        """Look up an invented Acme Demo Shop order by its id (for example ACME-1001)."""
        return order_lookup(order_id)

    @server.tool()
    def ask_assistant(question: str) -> str:
        """Ask the Acme Demo Shop support assistant a question about the shop."""
        return assistant_answer(question)

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A4 — MCP tool-agent (Streamable HTTP)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="bind address (default 127.0.0.1)"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    server = build_server(host=args.host, port=args.port)
    print(f"{APP} listening on http://{args.host}:{args.port}/mcp")
    server.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
