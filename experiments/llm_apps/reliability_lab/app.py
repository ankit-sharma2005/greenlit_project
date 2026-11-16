"""A6 — the reliability lab: a deterministic simulator, not a language model.

``POST /`` with ``{"question": "..."}`` answers ``{"answer": "..."}`` from a fixed
template. Four modes exist so GreenLit's operations metrics can be exercised on
purpose, reproducibly:

- ``ok`` — every request is answered.
- ``flaky_20`` — a seeded 20 % of questions get HTTP 500, the same questions on
  every start for the same seed (chosen by a hash, so order never matters).
- ``slow`` — every answer waits a seeded delay (default 3 s, configurable).
- ``rate_limited`` — after N requests inside a window (default 10 per 60 s) the
  app answers HTTP 429 with ``Retry-After``; the clock is injectable so tests do
  not sleep.

``POST /_control/mode`` flips the mode, but only with ``DEMO_CONTROL=1``, only
from loopback, and only to one of :data:`MODES`.

This app calls no model and contains no secrets. Local test subject only: it
binds 127.0.0.1 by default (``--host 0.0.0.0`` only for the Docker case) and must
never be exposed to the internet.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.control import serve_control
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

APP = "reliability-lab"
DEFAULT_PORT = 9116
DEFAULT_SEED = 20260101
FLAKY_PERCENT = 20
DEFAULT_DELAY_SECONDS = 3.0
DEFAULT_RATE_N = 10
DEFAULT_RATE_WINDOW_SECONDS = 60.0
MODES = ("ok", "flaky_20", "slow", "rate_limited")
_MAX_QUESTION = 300


def is_flaky(question: str, seed: int = DEFAULT_SEED) -> bool:
    """True for the seeded share of questions; a hash of the question, not a counter."""
    key = f"{seed}\x1f{question.strip().lower()}".encode()
    return hashlib.sha256(key).digest()[0] % 100 < FLAKY_PERCENT


def answer_for(question: str) -> str:
    """A fixed, deterministic answer: the app echoes what it received."""
    text = " ".join(question.split())
    return f"Reliability lab received: {text}"


def seeded_delay(question: str, maximum: float, seed: int = DEFAULT_SEED) -> float:
    """A delay of 0.25 s up to ``maximum``, fixed per question and seed."""
    if maximum <= 0:
        return 0.0
    key = f"{seed}\x1fdelay\x1f{question.strip().lower()}".encode()
    share = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") / 0xFFFFFFFF
    return (
        round(0.25 + share * max(0.0, maximum - 0.25), 3) if maximum > 0.25 else maximum
    )


def create_server(
    mode: str = "ok",
    *,
    control_enabled: bool | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    log_dir: Path | None = None,
    seed: int = DEFAULT_SEED,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    rate_limit: int = DEFAULT_RATE_N,
    rate_window_seconds: float = DEFAULT_RATE_WINDOW_SECONDS,
    clock: Any = None,
) -> AppServer:
    if control_enabled is None:
        control_enabled = os.environ.get("DEMO_CONTROL") == "1"
    if mode not in MODES:
        raise ValueError(f"mode must be one of {list(MODES)}")
    server = AppServer((host, port), handler(control_enabled, log_dir))
    server.app_name = APP
    server.lab_mode = mode
    server.lab_seed = seed
    server.lab_delay = delay_seconds
    server.lab_rate_limit = max(1, rate_limit)
    server.lab_rate_window = max(0.0, rate_window_seconds)
    server.lab_clock = clock or time.monotonic
    server.lab_hits = deque()
    server.control_enabled = control_enabled
    return server


def _rate_answer(server: AppServer) -> tuple[bool, str | None]:
    """(allowed, Retry-After seconds as text) for one request."""
    now = float(server.lab_clock())
    hits: deque[float] = server.lab_hits
    window = float(server.lab_rate_window)
    while hits and now - hits[0] >= window:
        hits.popleft()
    if len(hits) >= int(server.lab_rate_limit):
        wait = max(1, int(window - (now - hits[0]) + 0.999))
        return False, str(wait)
    hits.append(now)
    return True, None


def handler(control_enabled: bool, log_dir: Path | None) -> type[QuietHandler]:
    class LabHandler(QuietHandler):
        @property
        def mode(self) -> str:
            return getattr(self.server, "lab_mode", "ok")

        def do_GET(self) -> None:
            if self.path.split("?")[0] == "/health":
                send_json(self, 200, {"status": "ok", "app": APP, "mode": self.mode})
                return

        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            if path == "/_control/mode":

                def apply(value: str) -> None:
                    self.server.lab_mode = value
                    self.server.lab_hits.clear()

                serve_control(self, enabled=control_enabled, modes=MODES, apply=apply)
                return
            if path != "/":
                send_error(self, 404, "not_found")
                return
            started = time.monotonic()
            try:
                payload = read_json(self, 64_000)
                question = question_of(payload, _MAX_QUESTION)
            except BadRequest as exc:
                send_error(self, exc.status, exc.message)
                return

            mode = self.mode
            status = 200
            answer = ""
            if mode == "flaky_20" and is_flaky(question, self.server.lab_seed):
                status = 500
                send_error(self, 500, "seeded_failure")
            elif mode == "rate_limited":
                allowed, retry_after = _rate_answer(self.server)
                if not allowed:
                    status = 429
                    send_error(self, 429, "rate_limited", retry_after=retry_after)
                else:
                    answer = answer_for(question)
                    send_json(self, 200, {"answer": answer})
            else:
                if mode == "slow":
                    time.sleep(
                        seeded_delay(
                            question, self.server.lab_delay, self.server.lab_seed
                        )
                    )
                answer = answer_for(question)
                send_json(self, 200, {"answer": answer})

            log_request(
                APP,
                mode=mode,
                provider="none",
                model="none",
                question=question,
                answer_length=len(answer),
                latency_ms=int((time.monotonic() - started) * 1000),
                status=status,
                directory=log_dir,
            )

    return LabHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A6 — deterministic reliability lab")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--mode", choices=MODES, default="ok")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    args = parser.parse_args(argv)
    server = create_server(
        args.mode, host=args.host, port=args.port, delay_seconds=args.delay_seconds
    )
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
