"""A3 — the Acme Demo Shop persona over three streaming formats.

The same answer as A1, delivered four ways:

* ``POST /``      one JSON body ``{"answer": "..."}``
* ``POST /sse``   ``text/event-stream``, one ``data: {"delta": "..."}`` per piece,
                  then ``data: [DONE]`` — the shape GreenLit's connector reads
* ``POST /ndjson`` ``application/x-ndjson``, one ``{"delta": "..."}`` per line,
                  then ``{"done": true}``
* ``POST /text``  ``text/plain``, chunked transfer, no markers

A provider that cannot stream is chunked here, so every path always streams. A
failure before the first byte is a clean 503; a failure after it closes the stream
with an error event instead of leaving the reader waiting. Local test subject:
binds 127.0.0.1 by default and must never be exposed to the internet.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import requests

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

APP = "stream-bot"
DEFAULT_PORT = 9113


def messages(settings: Settings, question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt(settings.mode)},
        {"role": "user", "content": question},
    ]


def stream_pieces(
    client: LLMClient, settings: Settings, question: str
) -> Iterator[str]:
    """The provider's pieces; a provider failure becomes an exception, not silence."""
    return client.stream(messages(settings, question))


def _write_chunk(handler: QuietHandler, text: str) -> None:
    """One HTTP/1.1 chunk, so a plain-text answer really streams."""
    data = text.encode("utf-8")
    handler.wfile.write(f"{len(data):x}\r\n".encode())
    handler.wfile.write(data)
    handler.wfile.write(b"\r\n")
    handler.wfile.flush()


def _end_chunks(handler: QuietHandler) -> None:
    handler.wfile.write(b"0\r\n\r\n")
    handler.wfile.flush()


def handler(
    client: LLMClient, settings: Settings, log_dir: Path | None
) -> type[QuietHandler]:
    class StreamHandler(QuietHandler):
        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            formats = {"/sse": "sse", "/ndjson": "ndjson", "/text": "text", "/": "json"}
            if path not in formats:
                send_error(self, 404, "not_found")
                return
            started = time.monotonic()
            try:
                payload = read_json(self, settings.body_limit)
                question = question_of(payload, settings.question_limit)
            except BadRequest as exc:
                send_error(self, exc.status, exc.message)
                return
            if not question.strip():
                answer = "Please ask a question about Acme Demo Shop."
                self._log("", len(answer), started, 200)
                send_json(self, 200, {"answer": answer})
                return
            mode = formats[path]
            if mode == "json":
                self._json(question, started)
                return
            self._stream(mode, question, started)

        def _json(self, question: str, started: float) -> None:
            try:
                answer = client.chat(messages(settings, question))
            except ProviderUnavailable as exc:
                self._log(question, 0, started, 503)
                send_unavailable(self, exc)
                return
            except LLMError:
                self._log(question, 0, started, 502)
                send_error(self, 502, "provider_error")
                return
            self._log(question, len(answer), started, 200)
            send_json(self, 200, {"answer": answer})

        def _stream(self, mode: str, question: str, started: float) -> None:
            try:
                pieces = stream_pieces(client, settings, question)
                first = next(pieces, "")
            except ProviderUnavailable as exc:
                # Nothing has been written yet, so this is still a clean 503.
                self._log(question, 0, started, 503)
                send_unavailable(self, exc)
                return
            except LLMError:
                self._log(question, 0, started, 502)
                send_error(self, 502, "provider_error")
                return

            length = 0
            if mode == "sse":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
            elif mode == "ndjson":
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

            failed = False

            def emit(piece: str) -> None:
                nonlocal length
                if not piece:
                    return
                length += len(piece)
                if mode == "sse":
                    self.wfile.write(
                        f"data: {json.dumps({'delta': piece})}\n\n".encode()
                    )
                    self.wfile.flush()
                elif mode == "ndjson":
                    self.wfile.write((json.dumps({"delta": piece}) + "\n").encode())
                    self.wfile.flush()
                else:
                    _write_chunk(self, piece)

            try:
                if first:
                    emit(first)
                for piece in pieces:
                    emit(piece)
            except (ProviderUnavailable, LLMError, requests.RequestException):
                failed = True

            if mode == "sse":
                if failed:
                    self.wfile.write(b'data: {"error": "provider_unavailable"}\n\n')
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            elif mode == "ndjson":
                if failed:
                    self.wfile.write(b'{"error": "provider_unavailable"}\n')
                self.wfile.write(b'{"done": true}\n')
                self.wfile.flush()
            else:
                _end_chunks(self)

            self._log(question, length, started, 502 if failed else 200)

        def _log(
            self, question: str, answer_length: int, started: float, status: int
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

    return StreamHandler


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
    parser = argparse.ArgumentParser(description="A3 — Acme Demo Shop streaming bot")
    parser.add_argument(
        "--host", default="127.0.0.1", help="bind address (default 127.0.0.1)"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        server = create_server(settings, host=args.host, port=args.port)
    except Exception as exc:  # noqa: BLE001 - the message never holds a key
        print(f"cannot start {APP}: {exc}", file=sys.stderr)
        return 2
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
