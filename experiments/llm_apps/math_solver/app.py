"""A5 — the arithmetic solver: deterministic, no model, two modes.

``POST /`` with ``{"question": "What is 12 * 3?"}`` answers ``{"answer": "36"}``.
The expression is parsed by the shared safe AST evaluator
(:mod:`common.arithmetic`), so there is no ``eval``, no name and no call: a hostile
question is a 400, never code.

``mode`` is ``correct`` (default) or ``faulty_30``: a seeded 30 % of the questions
are answered with a wrong number, and the same question is faulty on every start
for the same seed. ``POST /_control/mode`` flips the mode, but only when the
server was started with ``DEMO_CONTROL=1`` and only from loopback.

Local test subject only: binds 127.0.0.1 by default, no authentication, must never
be exposed to the internet.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.arithmetic import UnsafeExpression, format_number, safe_evaluate
from common.request_log import log_request
from common.web import (
    AppServer,
    BadRequest,
    QuietHandler,
    question_of,
    read_json,
    send_error,
    send_json,
)

APP = "math-solver"
DEFAULT_PORT = 9115
DEFAULT_SEED = 20260101
FAULTY_PERCENT = 30
MODES = ("correct", "faulty_30")
_MAX_QUESTION = 300
_PREFIXES = ("what is ", "what's ", "whats ", "calculate ", "compute ", "how much is ")


def expression_of(question: str) -> str:
    """The arithmetic inside a plain question; the rest is a 400."""
    text = (question or "").strip()
    lowered = text.lower()
    for prefix in _PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.strip().rstrip("?").strip()


def is_faulty(question: str, seed: int = DEFAULT_SEED) -> bool:
    """True for the seeded share of questions; a hash, so order never matters."""
    key = f"{seed}\x1f{question.strip().lower()}".encode()
    return hashlib.sha256(key).digest()[0] % 100 < FAULTY_PERCENT


def answer_for(question: str, mode: str = "correct", seed: int = DEFAULT_SEED) -> str:
    """The app's answer: the evaluated expression, or a wrong number when seeded."""
    value = safe_evaluate(expression_of(question))
    if mode == "faulty_30" and is_faulty(question, seed):
        value = value + 1
    return format_number(value)


def _is_loopback(host: str | None) -> bool:
    return host in {"127.0.0.1", "::1"} or bool(host and host.startswith("127."))


def _health(mode: str) -> dict[str, str]:
    return {
        "status": "ok",
        "app": APP,
        "mode": mode,
        "provider": "none",
        "model": "none",
    }


def handler(control_enabled: bool, log_dir: Path | None) -> type[QuietHandler]:
    class SolverHandler(QuietHandler):
        @property
        def mode(self) -> str:
            return getattr(self.server, "solver_mode", "correct")

        def do_GET(self) -> None:
            if self.path.split("?")[0] == "/health":
                send_json(self, 200, _health(self.mode))
                return
            send_error(self, 404, "not_found")

        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            if path == "/_control/mode":
                self._control()
                return
            if path != "/":
                send_error(self, 404, "not_found")
                return
            started = time.monotonic()
            try:
                payload = read_json(self, 64_000)
                question = question_of(payload, _MAX_QUESTION)
                answer = answer_for(question, self.mode)
            except BadRequest as exc:
                send_error(self, exc.status, exc.message)
                return
            except UnsafeExpression as exc:
                send_error(self, 400, str(exc))
                return
            log_request(
                APP,
                mode=self.mode,
                provider="none",
                model="none",
                question=question,
                answer_length=len(answer),
                latency_ms=int((time.monotonic() - started) * 1000),
                status=200,
                directory=log_dir,
            )
            send_json(self, 200, {"answer": answer})

        def _control(self) -> None:
            if not control_enabled:
                send_error(self, 404, "not_found")
                return
            if not _is_loopback(self.client_address[0]):
                send_error(self, 403, "loopback_only")
                return
            try:
                payload: dict[str, Any] = read_json(self, 10_000)
            except BadRequest as exc:
                send_error(self, exc.status, exc.message)
                return
            mode = payload.get("mode")
            if mode not in MODES:
                send_error(self, 400, f"mode must be one of {list(MODES)}")
                return
            self.server.solver_mode = mode
            send_json(self, 200, {"mode": mode})

    return SolverHandler


def create_server(
    mode: str = "correct",
    *,
    control_enabled: bool | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    log_dir: Path | None = None,
) -> AppServer:
    if control_enabled is None:
        control_enabled = os.environ.get("DEMO_CONTROL") == "1"
    if mode not in MODES:
        raise ValueError(f"mode must be one of {list(MODES)}")
    server = AppServer((host, port), handler(control_enabled, log_dir))
    server.app_name = APP
    server.solver_mode = mode
    server.control_enabled = control_enabled
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A5 — deterministic math solver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--mode", choices=MODES, default="correct")
    args = parser.parse_args(argv)
    server = create_server(args.mode, host=args.host, port=args.port)
    control = "on" if server.control_enabled else "off"
    print(
        f"{APP} listening on http://{args.host}:{server.server_address[1]} "
        f"mode={args.mode} control={control}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
