"""A2 — retrieval over a fixed document set, answered by the model.

POST / with ``{"question": "..."}`` answers ``{"answer": "...", "context": [..]}``.
The retriever is BM25 in the standard library; the top three passages become the
``context`` and are the only sources the model is allowed to use. A question that
matches nothing is answered "I do not know." with an empty context, before any
model call. ``RAG_MODE=wrong_docs`` retrieves deliberately irrelevant passages
(seeded) so a groundedness check has a wrong version of the same app.

Local test subject only: binds 127.0.0.1 by default, never expose it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import Settings, load_settings
from common.llm import LLMClient, LLMError, ProviderUnavailable
from common.prompts import docs_system_prompt
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

from docs_rag.retrieval import Document, Retriever, load_documents

APP = "docs-rag"
DEFAULT_PORT = 9112
DOCUMENTS = Path(__file__).resolve().parent / "documents"
RAG_MODES = ("normal", "wrong_docs")
DO_NOT_KNOW = "I do not know."


def passages_message(question: str, passages: list[Document]) -> str:
    """The passages, wrapped as data, and the question last."""
    blocks = "\n".join(
        f'<document name="{passage.name}">\n{passage.text.strip()}\n</document>'
        for passage in passages
    )
    return f"Passages:\n{blocks}\n\nQuestion: {question}"


def answer_question(
    client: LLMClient,
    settings: Settings,
    question: str,
    retriever: Retriever,
    rag_mode: str,
) -> tuple[str, list[str]]:
    """Retrieve, then answer; an unrelated question never reaches the model."""
    if not question.strip():
        return "Please ask a question about Acme Demo Shop.", []
    passages = (
        retriever.irrelevant(question)
        if rag_mode == "wrong_docs"
        else retriever.search(question)
    )
    if not passages:
        return DO_NOT_KNOW, []
    answer = client.chat(
        [
            {"role": "system", "content": docs_system_prompt(settings.mode)},
            {"role": "user", "content": passages_message(question, passages)},
        ]
    )
    return answer, [passage.text for passage in passages]


def handler(
    client: LLMClient,
    settings: Settings,
    retriever: Retriever,
    rag_mode: str,
    log_dir: Path | None,
) -> type[QuietHandler]:
    class DocsHandler(QuietHandler):
        def do_POST(self) -> None:
            started = time.monotonic()
            try:
                payload = read_json(self, settings.body_limit)
                question = question_of(payload, settings.question_limit)
                answer, context = answer_question(
                    client, settings, question, retriever, rag_mode
                )
            except BadRequest as exc:
                send_error(self, exc.status, exc.message)
                return
            except ProviderUnavailable as exc:
                self._log("", 0, started, 503)
                send_unavailable(self, exc)
                return
            except LLMError:
                self._log("", 0, started, 502)
                send_error(self, 502, "provider_error")
                return
            self._log(question, len(answer), started, 200)
            send_json(self, 200, {"answer": answer, "context": context})

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

    return DocsHandler


def create_server(
    settings: Settings,
    client: LLMClient | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    rag_mode: str = "normal",
    documents: Path | None = None,
    log_dir: Path | None = None,
) -> AppServer:
    if rag_mode not in RAG_MODES:
        raise ValueError(f"rag_mode must be one of {list(RAG_MODES)}")
    retriever = Retriever(load_documents(documents or DOCUMENTS))
    server = AppServer(
        (host, port),
        handler(client or LLMClient(settings), settings, retriever, rag_mode, log_dir),
    )
    server.settings = settings
    server.app_name = APP
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A2 — Acme Demo Shop document RAG")
    parser.add_argument(
        "--host", default="127.0.0.1", help="bind address (default 127.0.0.1)"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--rag-mode",
        default="normal",
        choices=list(RAG_MODES),
        help="normal, or wrong_docs",
    )
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        server = create_server(
            settings, host=args.host, port=args.port, rag_mode=args.rag_mode
        )
    except Exception as exc:  # noqa: BLE001 - the message never holds a key
        print(f"cannot start {APP}: {exc}", file=sys.stderr)
        return 2
    print(
        f"{APP} listening on http://{args.host}:{server.server_address[1]} "
        f"mode={settings.mode} rag={args.rag_mode}"
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
