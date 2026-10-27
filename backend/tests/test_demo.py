"""Built-in demo (spec section 10): data, service, loader and the two verdicts.

The right-reason assertions matter here: the broken demo run must be NO_GO
*and* its explanation must spell out the weighted score, the REVIEW threshold
and the weak metrics, because that text is what the user reads.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.demo_server import app as demo_app
from app.models import User
from app.services.demo import (
    DEMO_CASES,
    DEMO_DATASET_NAME,
    chat,
    golden_csv,
    load_demo_dataset,
)
from app.services.run_executor import execute_run
from app.services.run_progress import MemoryProgress
from app.services.run_repository import create_run, get_run

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---- shipped data ----------------------------------------------------------


def test_demo_data_shipped_and_in_sync() -> None:
    """The 12 golden cases ship in demo/ and match what the API seeds."""
    golden = REPO_ROOT / "demo" / "helpdesk_golden.csv"
    assert golden.exists(), "demo/helpdesk_golden.csv must ship with the repo"
    assert golden.read_bytes() == golden_csv()
    assert len(DEMO_CASES) == 12
    for name in ("outputs_good.csv", "outputs_broken.csv", "helpdesk_info.pdf"):
        assert (REPO_ROOT / "demo" / name).exists(), f"demo/{name} must ship"


def test_chat_returns_golden_answers_or_a_broken_one() -> None:
    """Good mode is exactly right; broken mode shares no answer word with it."""
    for case in DEMO_CASES:
        good = chat(case["question"], mode="good")
        assert good["answer"] == case["answer"]
        assert good["context"] == case["context"]

        broken = chat(case["question"], mode="broken")
        assert broken["answer"] != case["answer"]
        # Content words only: short words and punctuation carry no signal.
        expected_words = {word for word in case["answer"].lower().split() if len(word) > 3}
        broken_words = {word for word in broken["answer"].lower().split() if len(word) > 3}
        assert not expected_words & broken_words, case["question"]


# ---- the demo service ------------------------------------------------------


class _DemoHandler(BaseHTTPRequestHandler):
    """The same behaviour the container serves; only MODE differs."""

    mode = "good"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            payload = {}
        question = str(payload.get("question") or payload.get("input") or "")
        body = chat(question, mode=self.mode)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def demo_server():
    """Start a local demo app in the given mode; yield its base URL."""
    servers: list[HTTPServer] = []

    def start(mode: str) -> str:
        handler = type("Handler", (_DemoHandler,), {"mode": mode})
        server = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/chat"

    try:
        yield start
    finally:
        for server in servers:
            server.shutdown()


def test_demo_server_answers_both_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /healthz reports MODE and POST /chat accepts question or input."""
    from fastapi.testclient import TestClient

    client = TestClient(demo_app)
    question = DEMO_CASES[0]["question"]

    monkeypatch.setenv("MODE", "good")
    assert client.get("/healthz").json()["mode"] == "good"
    good = client.post("/chat", json={"question": question})
    assert good.status_code == 200
    assert good.json()["answer"] == DEMO_CASES[0]["answer"]

    # {"input": ...} is accepted too, so the one-box flow can target it.
    alt = client.post("/chat", json={"input": question})
    assert alt.status_code == 200
    assert alt.json()["answer"] == DEMO_CASES[0]["answer"]

    monkeypatch.setenv("MODE", "broken")
    broken = client.post("/chat", json={"question": question})
    assert broken.status_code == 200
    assert broken.json()["answer"] != DEMO_CASES[0]["answer"]

    missing = client.post("/chat", json={"wrong": "shape"})
    assert missing.status_code == 400


# ---- POST /api/v1/demo/load ------------------------------------------------


def test_demo_load_requires_auth(client: TestClient) -> None:
    assert client.post("/api/v1/demo/load").status_code == 401


def test_demo_load_seeds_an_approved_dataset_and_is_idempotent(client: TestClient) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={"name": "Demo User", "email": "demo@example.com", "password": "password123456"},
    )
    assert registered.status_code == 201, registered.text

    first = client.post("/api/v1/demo/load")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["name"] == DEMO_DATASET_NAME
    settings = get_settings()
    assert payload["good_url"] == settings.demo_app_url
    assert payload["broken_url"] == settings.demo_app_broken_url

    # The dataset is usable by a run: it is approved.
    versions = client.get(f"/api/v1/datasets/{payload['dataset_id']}/versions").json()
    version = next(row for row in versions if row["version_no"] == 1)
    assert version["approved_at"] is not None
    assert version["row_count"] == 12

    # Pressing the button again must not fail on a duplicate name.
    second = client.post("/api/v1/demo/load")
    assert second.status_code == 200, second.text
    assert second.json()["dataset_id"] == payload["dataset_id"]
    assert second.json()["dataset_version_id"] == payload["dataset_version_id"]


# ---- the two runs ----------------------------------------------------------


def _seed_demo_run(
    session_factory: sessionmaker[Session],
    owner: uuid.UUID,
    url: str,
) -> uuid.UUID:
    """A queued HTTP run over the demo dataset, pointed at the demo app."""
    with session_factory() as session:
        user = session.get(User, owner)
        assert user is not None
        dataset, version = load_demo_dataset(session, user)
        run = create_run(
            session,
            owner_id=owner,
            name="Demo run",
            settings_snapshot={
                "entry_point": "http_endpoint",
                "url": url,
                "method": "POST",
                "body_template": '{"question": {{input}}}',
                "answer_path": "answer",
                "context_path": "context",
                "timeout_seconds": 7,
                "allow_private_targets": True,
                "test_types": ["quality", "safety", "operations"],
            },
            dataset_id=dataset.id,
            dataset_version_id=version.id,
            criteria_profile="rag_chatbot",
        )
        session.commit()
        return run.id


@pytest.fixture
def owner(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        user = User(
            email=f"demo-{uuid.uuid4().hex[:8]}@example.com",
            name="Demo Runner",
            password_hash="x",
            role="admin",
        )
        session.add(user)
        session.commit()
        return user.id


def test_good_demo_run_is_a_go(
    session_factory: sessionmaker[Session], owner: uuid.UUID, demo_server
) -> None:
    url = demo_server("good")
    run_id = _seed_demo_run(session_factory, owner, url)

    report = execute_run(
        run_id,
        session_factory=session_factory,
        progress=MemoryProgress(),
        parallelism=2,
    )

    assert report["status"] == "completed", report
    assert report["verdict"] == "GO", report
    assert report["score"] is not None and report["score"] >= 0.8, report

    with session_factory() as session:
        run = get_run(session, run_id)
        assert run is not None
        assert run.state == "completed"
        assert run.verdict == "GO"


def test_broken_demo_run_is_no_go_and_the_reason_explains_it(
    session_factory: sessionmaker[Session], owner: uuid.UUID, demo_server
) -> None:
    """Right reason: score, REVIEW threshold and the weak metrics by name."""
    url = demo_server("broken")
    run_id = _seed_demo_run(session_factory, owner, url)

    report = execute_run(
        run_id,
        session_factory=session_factory,
        progress=MemoryProgress(),
        parallelism=2,
    )
    assert report["status"] == "completed", report
    assert report["verdict"] == "NO_GO", report

    with session_factory() as session:
        run = get_run(session, run_id)
        assert run is not None
        reason = run.verdict_reason or ""

        assert re.search(r"Weighted score 0\.\d\d", reason), reason
        assert "below the REVIEW threshold 0.60" in reason
        assert "Weakest metrics:" in reason
        assert "answer_match 0.00" in reason
        # The score is far below the threshold, not a near miss.
        assert run.score is not None
        assert run.score < 0.60
