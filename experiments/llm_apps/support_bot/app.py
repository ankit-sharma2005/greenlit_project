"""A1 — the Acme Demo Shop support bot.

POST / with ``{"question": "..."}`` answers ``{"answer": "..."}``. The persona and
its FAQ live in the system prompt; the question is sent as its own user message
and never appended to the system message, so a hostile question cannot rewrite the
instructions. This app is a local test subject: it binds 127.0.0.1 by default and
must never be exposed to the internet.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import Settings, load_settings
from common.llm import LLMClient, LLMError, ProviderUnavailable
from common.prompts import system_prompt
from common.request_log import log_request
from common.web import (
    AppServer,
    BadRequest,
    QuietHandler,
    question_of,
    read_json,
    send_error,
    send_json,
    send_unavailable,
)

APP = "support-bot"
DEFAULT_PORT = 9111


def answer_question(client: LLMClient, settings: Settings, question: str) -> str:
    """One model call with the mode's system prompt and the question alone."""
    if not question.strip():
        return "Please ask a question about Acme Demo Shop."
    return client.chat(
        [
            {"role": "system", "content": system_prompt(settings.mode)},
            {"role": "user", "content": question},
        ]
    )


def handler(
    client: LLMClient, settings: Settings, log_dir: Path | None
) -> type[QuietHandler]:
    class SupportHandler(QuietHandler):
        def do_POST(self) -> None:
            started = time.monotonic()
            try:
                payload = read_json(self, settings.body_limit)
                question = question_of(payload, settings.question_limit)
                answer = answer_question(client, settings, question)
            except BadRequest as exc:
                send_error(self, exc.status, exc.message)
                return
            except ProviderUnavailable as exc:
                self._log(question="", answer_length=0, started=started, status=503)
                send_unavailable(self, exc)
                return
            except LLMError:
                self._log(question="", answer_length=0, started=started, status=502)
                send_error(self, 502, "provider_error")
                return
            self._log(
                question=question,
                answer_length=len(answer),
                started=started,
                status=200,
            )
            send_json(self, 200, {"answer": answer})

        def _log(
            self, *, question: str, answer_length: int, started: float, status: int
        ) -> None:
            log_request(
                APP,
                mode=settings.mode,
                provider=settings.provider,
                model=settings.model,
                question=question,
                answer_length=answer_length,
                latency_ms=int((time.monotonic() - started) * 1000),
                status=status,
                directory=log_dir,
            )

    return SupportHandler


def create_server(
    settings: Settings,
    client: LLMClient | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    log_dir: Path | None = None,
) -> AppServer:
    server = AppServer(
        (host, port), handler(client or LLMClient(settings), settings, log_dir)
    )
    server.settings = settings
    server.app_name = APP
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A1 — Acme Demo Shop support bot")
    parser.add_argument(
        "--host", default="127.0.0.1", help="bind address (default 127.0.0.1)"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except Exception as exc:  # noqa: BLE001 - the message never holds a key
        print(f"cannot start {APP}: {exc}", file=sys.stderr)
        return 2
    server = create_server(settings, host=args.host, port=args.port)
    print(
        f"{APP} listening on http://{args.host}:{server.server_address[1]} mode={settings.mode}"
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
