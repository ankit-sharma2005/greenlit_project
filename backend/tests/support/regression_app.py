"""A deterministic stand-in app for the e2e regression spec.

It answers ``POST /`` with ``{"answer": "..."}`` for the arithmetic questions in a
CSV dataset and never calls a model, so a flip between modes is a real regression
and not sampling noise. ``POST /_control/mode`` switches between ``correct`` and
``faulty`` (every answer off by one). Started by ``scripts/run-e2e.sh`` only.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments" / "llm_apps"))

from common.arithmetic import UnsafeExpression, format_number, safe_evaluate  # noqa: E402

MODES = ("correct", "faulty")
PREFIXES = ("what is ", "what's ", "calculate ", "compute ")


def expression_of(question: str) -> str:
    text = (question or "").strip()
    lowered = text.lower()
    for prefix in PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.strip().rstrip("?").strip()


class Handler(BaseHTTPRequestHandler):
    mode = "correct"

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/health":
            self._send(
                200,
                {
                    "status": "ok",
                    "app": "math-solver",
                    "mode": type(self).mode,
                    "provider": "none",
                    "model": "none",
                },
            )
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
        if path == "/_control/mode":
            mode = payload.get("mode") if isinstance(payload, dict) else None
            if mode not in MODES:
                self._send(400, {"error": "unknown_mode"})
                return
            type(self).mode = mode
            self._send(200, {"mode": mode})
            return
        if path != "/":
            self._send(404, {"error": "not_found"})
            return
        question = payload.get("question") if isinstance(payload, dict) else None
        try:
            value = safe_evaluate(expression_of(str(question)))
        except UnsafeExpression:
            self._send(400, {"error": "not_arithmetic"})
            return
        if type(self).mode == "faulty":
            value = value + 1
        self._send(200, {"answer": format_number(value)})

    def log_message(self, format: str, *args: object) -> None:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic regression stand-in")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"regression stand-in on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
