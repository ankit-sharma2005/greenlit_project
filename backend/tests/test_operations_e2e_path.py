"""The prompt-app path must record the tokens its provider reports.

Operations can only price a run when the connector kept the provider's usage
numbers. These tests drive the real sender (not a fake Trace) against a local
HTTP server, so the wiring from the provider reply to the stored run item is
covered end to end.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import Provider, Run, User
from app.services.run_executor import build_sender, execute_run
from tests.test_run_executor import MemoryProgress, seed_run


class _UsageHandler(BaseHTTPRequestHandler):
    """Answers every chat completion with a fixed reply and token usage."""

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        body = json.dumps(
            {
                "choices": [{"message": {"content": "GreenLit tests LLM apps."}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Silence the server's stderr logging in tests."""


@pytest.fixture
def owner(session_factory: sessionmaker[Session]) -> uuid.UUID:
    """One saved account, which the run and the provider both point at."""
    with session_factory() as session:
        user = User(
            email=f"ops-{uuid.uuid4().hex[:8]}@example.com",
            name="Operations Owner",
            password_hash="x",
            role="admin",
        )
        session.add(user)
        session.commit()
        return user.id


@pytest.fixture
def provider_server() -> Iterator[int]:
    server = HTTPServer(("127.0.0.1", 0), _UsageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_port)
    finally:
        server.shutdown()
        server.server_close()


def _add_provider(session_factory: sessionmaker[Session], owner_id: uuid.UUID, port: int) -> str:
    with session_factory() as session:
        provider = Provider(
            name=f"usage-{uuid.uuid4().hex[:8]}",
            kind="openai-compatible",
            model_name="fake-model",
            base_url=f"http://127.0.0.1:{port}/v1",
            is_active=True,
            timeout_seconds=5,
            max_retries=0,
            backoff_factor=2.0,
            rate_limit_per_minute=600,
            provider_config={
                "price_per_1k_tokens_in": 0.01,
                "price_per_1k_tokens_out": 0.02,
            },
        )
        session.add(provider)
        session.commit()
        return str(provider.id)


def test_prompt_app_run_stores_tokens_and_a_cost_estimate(
    session_factory: sessionmaker[Session],
    owner: uuid.UUID,
    provider_server: int,
) -> None:
    """The whole chain: provider usage -> run item -> operations block."""
    provider_id = _add_provider(session_factory, owner, provider_server)
    run_id = seed_run(
        session_factory,
        owner,
        entry="prompt_app",
        settings_extra={
            "provider_id": provider_id,
            "model": "fake-model",
            "system_prompt": "Be concise.",
            "body_template": "{{input}}",
        },
    )

    progress = MemoryProgress()
    execute_run(
        run_id,
        session_factory=session_factory,
        sender_factory=build_sender,
        progress=progress,
    )

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        operations = run.operations
        assert operations is not None, "the worker must store the operations block"
        # The seed dataset has three cases, each reporting 120 in / 40 out.
        assert operations["items_total"] == 3
        assert operations["tokens_in_total"] == 360
        assert operations["tokens_out_total"] == 120
        assert operations["cost_configured"] is True
        # 360/1000 * 0.01 + 120/1000 * 0.02 = 0.006
        assert operations["cost_estimate"] == pytest.approx(0.006)
