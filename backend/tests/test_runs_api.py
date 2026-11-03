"""M6c API tests: run start, progress, items, cancel and quick test.

The API must never execute a run itself: these tests assert that starting a run
only stores the settings snapshot, creates the run in ``queued`` and hands the
id to the queue, while cancel flips the state so the executor can stop.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.runs import get_progress_reader
from app.main import app
from app.models import (
    AuditEvent,
    Provider,
    Run,
    RunState,
    User,
    utcnow,
)
from app.schemas.runs import RunCreateRequest
from app.services.generation import get_chat_fn
from app.services.run_progress import RunProgress
from app.services.run_repository import (
    add_metric_result,
    create_run,
    create_run_item,
    update_run,
    update_run_item,
)
from app.services.run_service import build_snapshot, get_enqueue
from app.services.target_check import accept_check, fingerprint, record_check

PASSWORD = "correct horse battery staple"

CSV_BYTES = (
    b"question,answer,context\n"
    b"What is GreenLit?,GreenLit tests LLM apps.,GreenLit tests LLM applications.\n"
    b"Is it fast?,Yes it is fast.,Runs are quick.\n"
)


@pytest.fixture(autouse=True)
def runtime() -> Iterator[SimpleNamespace]:
    """Queue and progress seams so no test needs Redis or a broker."""
    queue: list[uuid.UUID] = []
    progress: dict[uuid.UUID, RunProgress] = {}

    def generate(
        provider: Provider, messages: list[dict[str, str]], temperature: float, limit: int
    ) -> str:
        return json.dumps(
            [
                {
                    "question": "What is GreenLit?",
                    "answer": "GreenLit tests LLM apps.",
                    "context": "GreenLit tests LLM applications.",
                    "category": "factual",
                },
                {
                    "question": "Where do runs execute?",
                    "answer": "In a Celery worker.",
                    "context": None,
                    "category": "factual",
                },
            ]
        )

    app.dependency_overrides[get_enqueue] = lambda: queue.append
    app.dependency_overrides[get_progress_reader] = lambda: progress.get
    app.dependency_overrides[get_chat_fn] = lambda: generate
    yield SimpleNamespace(queue=queue, progress=progress, chat=generate)
    app.dependency_overrides.pop(get_enqueue, None)
    app.dependency_overrides.pop(get_progress_reader, None)
    app.dependency_overrides.pop(get_chat_fn, None)


def _register(client: TestClient, email: str = "runs@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Run Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _upload_and_approve(client: TestClient, name: str = "Golden") -> dict[str, object]:
    response = client.post(
        "/api/v1/datasets",
        data={"name": name},
        files={"file": ("golden.csv", CSV_BYTES, "text/csv")},
    )
    assert response.status_code == 201, response.text
    dataset = response.json()
    approved = client.post(f"/api/v1/datasets/{dataset['id']}/versions/1/approve")
    assert approved.status_code == 200, approved.text
    return dataset


def _user_id(session_factory: sessionmaker[Session], email: str = "runs@example.com") -> uuid.UUID:
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        return user.id


def _accepted_check(session_factory: sessionmaker[Session], body: dict[str, object]) -> str:
    """An accepted check bound to exactly these target settings.

    The check's own request is covered in tests/test_target_check.py; here the
    record is stored directly so no test contacts a third-party host.
    """
    owner = _user_id(session_factory)
    snapshot = build_snapshot(
        RunCreateRequest.model_validate(body),
        dataset_version_id=uuid.UUID(str(body["dataset_version_id"])),
        entry_point="http_endpoint",
    )
    check = record_check(
        owner_id=owner,
        config_hash=fingerprint(snapshot),
        result={"answer": "Hello", "error": None, "request": {}},
    )
    accept_check(check.id, owner)
    return check.id


def _body(dataset: dict[str, object]) -> dict[str, object]:
    return {
        "entry_point": "http_endpoint",
        "target": "http://127.0.0.1:9099/ask",
        "dataset_id": dataset["id"],
        "dataset_version_id": dataset["versions"][0]["id"],  # type: ignore[index]
        "body_template": '{"question": {{input}}}',
        "answer_path": "answer",
        "context_path": "context",
        "allow_private_targets": True,
    }


def test_start_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v1/runs", json={"target": "http://127.0.0.1/x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_start_queues_without_executing(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)

    response = client.post("/api/v1/runs", json=_body(dataset))
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "queued"
    assert body["entry_point"] == "http_endpoint"
    assert body["test_types"] == ["quality", "safety", "operations"]
    assert body["progress"]["items_done"] == 0
    assert body["metrics"] == []

    # The request queued it; nothing ran inside the request.
    assert len(runtime.queue) == 1
    assert str(runtime.queue[0]) == body["id"]

    with session_factory() as session:
        run = session.get(Run, uuid.UUID(body["id"]))
        assert run is not None
        assert run.state == RunState.QUEUED.value
        assert run.settings_snapshot["url"] == "http://127.0.0.1:9099/ask"
        assert run.settings_snapshot["allow_private_targets"] is True
        assert run.settings_snapshot["answer_path"] == "answer"
        # Polite-rate defaults travel with the run and are not read live later.
        assert run.settings_snapshot["max_concurrency"] == 1
        assert run.settings_snapshot["min_delay_ms"] == 500
        assert run.settings_snapshot["max_retries"] == 3
        assert run.settings_snapshot["response_format"] == "json"
        assert run.settings_snapshot["stream_content_path"] is None
        # Automatic profile: context was detected, so the RAG template applies.
        assert run.criteria_profile == "rag_chatbot"
        assert run.dataset_version_id == uuid.UUID(str(dataset["versions"][0]["id"]))  # type: ignore[index]
        # Items belong to the worker, not the route.
        assert run.items == []

        events = session.scalars(select(AuditEvent).where(AuditEvent.action == "run.start")).all()
        assert len(events) == 1


def test_a_retried_start_with_the_same_idempotency_key_returns_the_same_run(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    """A double click (or a retried POST) must not send every case twice."""
    _register(client)
    dataset = _upload_and_approve(client)
    headers = {"Idempotency-Key": "checkout-demo-1"}

    first = client.post("/api/v1/runs", json=_body(dataset), headers=headers)
    second = client.post("/api/v1/runs", json=_body(dataset), headers=headers)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.json()["id"] == first.json()["id"]
    # Queued once, stored once.
    assert len(runtime.queue) == 1
    with session_factory() as session:
        assert len(session.scalars(select(Run)).all()) == 1
        run = session.get(Run, uuid.UUID(first.json()["id"]))
        assert run is not None
        assert run.settings_snapshot["idempotency_key"] == "checkout-demo-1"


def test_two_identical_starts_in_a_row_are_one_run(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    """Without a key, the same target+dataset within the window dedupes too."""
    _register(client)
    dataset = _upload_and_approve(client)

    first = client.post("/api/v1/runs", json=_body(dataset))
    second = client.post("/api/v1/runs", json=_body(dataset))

    assert first.status_code == 202, first.text
    assert second.json()["id"] == first.json()["id"]
    assert len(runtime.queue) == 1
    with session_factory() as session:
        assert len(session.scalars(select(Run)).all()) == 1


def test_the_hash_must_include_target_settings_so_limits_double_runs(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    """A smoke run and a full run on the same target & dataset are two runs."""
    _register(client)
    dataset = _upload_and_approve(client)

    short = {
        "entry_point": "http_endpoint",
        "target": "http://127.0.0.1:9099/ask",
        "dataset_id": dataset["id"],
        "dataset_version_id": dataset["versions"][0]["id"],
        "body_template": '{"question": {{input}}}',
        "answer_path": "answer",
        "context_path": "context",
        "allow_private_targets": True,
        "is_smoke": True,
        "max_cases": 5,
    }
    full = {**short, "is_smoke": False, "max_cases": 12}

    first = client.post("/api/v1/runs", json=short)
    second = client.post("/api/v1/runs", json=full)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.json()["id"] != first.json()["id"]
    assert len(runtime.queue) == 2
    with session_factory() as session:
        assert len(session.scalars(select(Run)).all()) == 2


def test_the_hash_must_separate_requests_that_differ_only_in_a_limit(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    """Two requests that differ only in a cap are not the same run."""
    _register(client)
    dataset = _upload_and_approve(client)

    left = {
        "entry_point": "http_endpoint",
        "target": "http://127.0.0.1:9099/ask",
        "dataset_id": dataset["id"],
        "dataset_version_id": dataset["versions"][0]["id"],
        "body_template": '{"question": {{input}}}',
        "answer_path": "answer",
        "context_path": "context",
        "allow_private_targets": True,
        "is_smoke": True,
        "max_cases": 5,
    }
    right = {**left, "max_cases": 10}

    first = client.post("/api/v1/runs", json=left)
    second = client.post("/api/v1/runs", json=right)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.json()["id"] != first.json()["id"]
    assert len(runtime.queue) == 2
    with session_factory() as session:
        assert len(session.scalars(select(Run)).all()) == 2


def test_the_idempotency_key_wins_when_present(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    """An explicit key decides on its own: a different body, still one run."""
    _register(client)
    dataset = _upload_and_approve(client)
    headers = {"Idempotency-Key": "manual-retry-42"}

    body = {
        "entry_point": "http_endpoint",
        "target": "http://127.0.0.1:9099/ask",
        "dataset_id": dataset["id"],
        "dataset_version_id": dataset["versions"][0]["id"],
        "body_template": '{"question": {{input}}}',
        "answer_path": "answer",
        "context_path": "context",
        "allow_private_targets": True,
        "is_smoke": True,
        "max_cases": 5,
    }
    # Different caps, same key: the key, not the body hash, has to win.
    changed = {**body, "max_cases": 10}

    first = client.post("/api/v1/runs", json=body, headers=headers)
    second = client.post("/api/v1/runs", json=changed, headers=headers)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.json()["id"] == first.json()["id"]
    assert len(runtime.queue) == 1
    with session_factory() as session:
        runs = session.scalars(select(Run)).all()
        assert len(runs) == 1
        assert runs[0].settings_snapshot.get("idempotency_key") == "manual-retry-42"


def test_start_needs_a_dataset(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/api/v1/runs", json={"entry_point": "http_endpoint", "target": "http://127.0.0.1/x"}
    )
    assert response.status_code == 400
    assert "dataset" in response.json()["error"]["message"].lower()


def test_start_rejects_an_unapproved_version(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    uploaded = client.post(
        "/api/v1/datasets",
        data={"name": "Draft"},
        files={"file": ("draft.csv", CSV_BYTES, "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset = uploaded.json()
    response = client.post(
        "/api/v1/runs",
        json={
            "entry_point": "http_endpoint",
            "target": "http://127.0.0.1/x",
            "dataset_version_id": dataset["versions"][0]["id"],
        },
    )
    assert response.status_code == 400
    assert "approved" in response.json()["error"]["message"].lower()


def test_start_validates_the_url_and_profile(client: TestClient) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body["target"] = "not-a-url"
    bad_url = client.post("/api/v1/runs", json=body)
    assert bad_url.status_code == 400
    assert "http" in bad_url.json()["error"]["message"].lower()

    body = _body(dataset)
    body["criteria_profile"] = "made_up"
    bad_profile = client.post("/api/v1/runs", json=body)
    assert bad_profile.status_code == 400
    assert "profile" in bad_profile.json()["error"]["message"].lower()

    body = _body(dataset)
    body["test_types"] = []
    no_types = client.post("/api/v1/runs", json=body)
    assert no_types.status_code == 400
    assert "test type" in no_types.json()["error"]["message"].lower()


def test_plain_profile_without_context(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body.pop("context_path")
    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 202, response.text
    with session_factory() as session:
        run = session.get(Run, uuid.UUID(response.json()["id"]))
        assert run is not None
        assert run.criteria_profile == "plain_chatbot"


def test_progress_uses_live_counters_then_falls_back_to_items(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = uuid.UUID(client.post("/api/v1/runs", json=_body(dataset)).json()["id"])

    runtime.progress[run_id] = RunProgress(
        items_done=2, items_total=5, items_failed=1, stage="running"
    )
    live = client.get(f"/api/v1/runs/{run_id}/progress")
    assert live.status_code == 200
    assert live.json()["items_done"] == 2
    assert live.json()["items_total"] == 5
    assert live.json()["stage"] == "running"

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        first = create_run_item(session, run, row_index=1, input_text="q1")
        second = create_run_item(session, run, row_index=2, input_text="q2")
        session.commit()
        update_run_item(session, first, state="completed", output="a1")
        update_run_item(session, second, state="failed", error="boom")
        session.commit()

    runtime.progress.clear()
    fallback = client.get(f"/api/v1/runs/{run_id}/progress")
    assert fallback.status_code == 200
    body = fallback.json()
    assert body["items_done"] == 2
    assert body["items_total"] == 2
    assert body["items_failed"] == 1
    assert body["stage"] == "queued"


def test_items_and_detail_include_metrics_and_failures(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = uuid.UUID(client.post("/api/v1/runs", json=_body(dataset)).json()["id"])

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        good = create_run_item(session, run, row_index=1, input_text="What is GreenLit?")
        bad = create_run_item(session, run, row_index=2, input_text="Is it fast?")
        session.commit()
        update_run_item(session, good, state="completed", output="GreenLit tests LLM apps.")
        update_run_item(session, bad, state="failed", error="the app returned 500")
        add_metric_result(
            session,
            run,
            name="answer_match",
            score=0.0,
            passed=False,
            explanation="no answer overlapped the expectation",
            weight=0.4,
            threshold=0.6,
            hard_gate=False,
        )
        update_run(
            session,
            run,
            state=RunState.COMPLETED,
            verdict="NO_GO",
            score=0.5,
            verdict_reason="Weighted score 0.50 is below the REVIEW threshold 0.60.",
            started_at=utcnow(),
            completed_at=utcnow(),
        )
        session.commit()

    items = client.get(f"/api/v1/runs/{run_id}/items").json()
    assert items["total"] == 2
    assert items["items"][1]["error"] == "the app returned 500"

    detail = client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["verdict"] == "NO_GO"
    assert body["score"] == 0.5
    assert body["metrics"][0]["name"] == "answer_match"
    assert body["metrics"][0]["weight"] == 0.4
    assert body["failed_cases"][0]["reason"] == "the app returned 500"
    assert body["progress"]["items_total"] == 2
    assert body["progress"]["items_done"] == 2


def test_cancel_queued_run_stops_before_any_case(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = uuid.UUID(client.post("/api/v1/runs", json=_body(dataset)).json()["id"])

    response = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "cancelled"
    assert body["is_partial"] is True
    assert "cancelled before it started" in body["verdict_reason"]

    with session_factory() as session:
        assert session.scalar(select(AuditEvent).where(AuditEvent.action == "run.cancel"))


def test_cancel_running_run_marks_cancelling(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = uuid.UUID(client.post("/api/v1/runs", json=_body(dataset)).json()["id"])
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        update_run(session, run, state=RunState.RUNNING, started_at=utcnow())
        session.commit()

    response = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["state"] == "cancelling"
    assert response.json()["is_partial"] is False


def test_cancel_a_finished_run_is_a_conflict(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = uuid.UUID(client.post("/api/v1/runs", json=_body(dataset)).json()["id"])
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        update_run(session, run, state=RunState.COMPLETED, completed_at=utcnow())
        session.commit()

    response = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.status_code == 409
    assert "already completed" in response.json()["error"]["message"]


def test_runs_are_private_and_paginated(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = client.post("/api/v1/runs", json=_body(dataset)).json()["id"]

    listing = client.get("/api/v1/runs")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["limit"] == 20
    assert listing.json()["items"][0]["id"] == run_id

    # Another account cannot read it.
    client.post("/api/v1/auth/logout")
    _register(client, email="other@example.com")
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 404
    assert client.get("/api/v1/runs").json()["total"] == 0


def test_quick_test_with_csv_creates_and_approves_a_dataset(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    _register(client)
    response = client.post(
        "/api/v1/quick-test",
        json={
            "entry_point": "http_endpoint",
            "target": "http://127.0.0.1:9099/ask",
            "tests": ["quality", "operations"],
            "csv": CSV_BYTES.decode(),
            "allow_private_targets": True,
            "body_template": '{"input": {{input}}}',
            "answer_path": "response.text",
            "context_path": "context",
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["generated"] is False
    assert body["run"]["state"] == "queued"
    assert body["run"]["test_types"] == ["quality", "operations"]
    assert body["run"]["dataset_version_id"] == body["dataset_version_id"]
    assert len(runtime.queue) == 1

    dataset_id = uuid.UUID(body["dataset_id"])
    versions = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()
    assert versions[0]["approved_at"] is not None
    assert versions[0]["row_count"] == 2

    # The detected connector shape travels with the run, not a hard-coded one.
    with session_factory() as session:
        run = session.get(Run, uuid.UUID(body["run"]["id"]))
        assert run is not None
        assert run.settings_snapshot["body_template"] == '{"input": {{input}}}'
        assert run.settings_snapshot["answer_path"] == "response.text"
        assert run.criteria_profile == "rag_chatbot"


def test_quick_test_generates_cases_with_the_model(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    with session_factory() as session:
        session.add(
            Provider(
                name="Local Ollama",
                kind="openai-compatible",
                model_name="llama3",
                base_url="http://host.docker.internal:11434/v1",
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/quick-test",
        json={
            "entry_point": "http_endpoint",
            "target": "http://127.0.0.1:9099/ask",
            "tests": ["quality"],
            "generate": 5,
            "allow_private_targets": True,
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["generated"] is True

    versions = client.get(f"/api/v1/datasets/{body['dataset_id']}/versions").json()
    assert versions[0]["generated"] is True
    assert versions[0]["approved_at"] is not None
    items = client.get(f"/api/v1/datasets/{body['dataset_id']}/versions/1/items").json()
    assert items["total"] == 2
    assert items["items"][0]["data"]["question"] == "What is GreenLit?"


def test_quick_test_without_provider_explains_the_next_action(
    client: TestClient,
) -> None:
    _register(client)
    response = client.post(
        "/api/v1/quick-test",
        json={
            "entry_point": "http_endpoint",
            "target": "http://127.0.0.1:9099/ask",
            "tests": ["quality"],
        },
    )
    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "Settings > Providers" in message
    assert "CSV" in message


def test_quick_test_needs_csv_for_uploaded_outputs(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/api/v1/quick-test",
        json={
            "entry_point": "upload_outputs",
            "target": "uploaded.csv",
            "tests": ["quality"],
        },
    )
    assert response.status_code == 400
    assert "csv" in response.json()["error"]["message"].lower()


def test_quick_test_rejects_coming_soon_entry_points(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/api/v1/quick-test",
        json={"entry_point": "docker_image", "target": "my-image", "tests": ["quality"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_start_prompt_app_requires_a_provider(client: TestClient) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    response = client.post(
        "/api/v1/runs",
        json={
            "entry_point": "prompt_app",
            "target": "You are a helpful assistant.",
            "dataset_id": dataset["id"],
        },
    )
    assert response.status_code == 400
    assert "provider" in response.json()["error"]["message"].lower()


def test_start_prompt_app_snapshots_the_model(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    with session_factory() as session:
        provider = Provider(
            name="Local Ollama",
            kind="openai-compatible",
            model_name="llama3",
            base_url="http://host.docker.internal:11434/v1",
        )
        session.add(provider)
        session.commit()
        provider_id = provider.id

    response = client.post(
        "/api/v1/runs",
        json={
            "entry_point": "prompt_app",
            "target": "You are a helpful assistant.",
            "dataset_id": dataset["id"],
            "provider_id": str(provider_id),
            "model": "llama3:8b",
            "temperature": 0.1,
        },
    )
    assert response.status_code == 202, response.text
    with session_factory() as session:
        run = session.get(Run, uuid.UUID(response.json()["id"]))
        assert run is not None
        assert run.settings_snapshot["provider_id"] == str(provider_id)
        assert run.settings_snapshot["system_prompt"] == "You are a helpful assistant."
        assert run.settings_snapshot["model"] == "llama3:8b"
        assert run.settings_snapshot["entry_point"] == "prompt_app"


def test_a_remote_target_needs_permission(client: TestClient, runtime: SimpleNamespace) -> None:
    """Testing somebody else's app is refused until the box is ticked."""
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body.pop("allow_private_targets")
    body["target"] = "https://chat.example.com/ask"

    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 422, response.text
    message = response.json()["error"]["message"]
    assert "permission" in message.lower()
    assert runtime.queue == []


def test_permission_is_recorded_and_attacks_stay_off(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body.pop("allow_private_targets")
    body["target"] = "https://chat.example.com/ask"
    body["permission_confirmed"] = True
    body["permission_reference"] = "Ops ticket 4711"
    body["target_check_id"] = _accepted_check(session_factory, body)

    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 202, response.text
    run_id = uuid.UUID(response.json()["id"])
    # Safety was asked for, but attack probes need their own confirmation.
    assert response.json()["test_types"] == ["quality", "operations"]
    assert response.json()["permission"] == {
        "confirmed": True,
        "reference": "Ops ticket 4711",
        "safety_attacks_confirmed": False,
    }

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        snapshot = run.settings_snapshot
        assert snapshot["permission_confirmed"] is True
        assert snapshot["permission_reference"] == "Ops ticket 4711"
        assert snapshot["safety_attacks_confirmed"] is False
        assert "safety_sets" not in snapshot
        event = session.scalars(select(AuditEvent).where(AuditEvent.action == "run.start")).one()
        assert event.event_metadata["permission_confirmed"] is True
        assert event.event_metadata["permission_reference"] == "Ops ticket 4711"


def test_safety_only_without_the_attack_confirmation_is_refused(
    client: TestClient, session_factory: sessionmaker[Session], runtime: SimpleNamespace
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body.pop("allow_private_targets")
    body["target"] = "https://chat.example.com/ask"
    body["permission_confirmed"] = True
    body["test_types"] = ["safety"]
    body["target_check_id"] = _accepted_check(session_factory, body)

    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 422, response.text
    message = response.json()["error"]["message"]
    assert "confirmation" in message.lower()
    assert runtime.queue == []


def test_the_second_confirmation_turns_attacks_on(
    client: TestClient,
    session_factory: sessionmaker[Session],
    runtime: SimpleNamespace,
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body.pop("allow_private_targets")
    body["target"] = "https://chat.example.com/ask"
    body["permission_confirmed"] = True
    body["safety_attacks_confirmed"] = True
    body["test_types"] = ["safety", "quality"]
    body["target_check_id"] = _accepted_check(session_factory, body)

    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 202, response.text
    assert response.json()["test_types"] == ["safety", "quality"]

    with session_factory() as session:
        run = session.get(Run, uuid.UUID(response.json()["id"]))
        assert run is not None
        assert run.settings_snapshot["safety_attacks_confirmed"] is True
        assert run.settings_snapshot["safety_sets"]


def test_a_local_target_needs_no_permission(client: TestClient, runtime: SimpleNamespace) -> None:
    """The local app and the built-in demo stay one click."""
    _register(client)
    dataset = _upload_and_approve(client)
    response = client.post("/api/v1/runs", json=_body(dataset))
    assert response.status_code == 202, response.text
    assert response.json()["permission"] is None


def test_run_created_directly_can_be_read(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """A run created by the worker path (no snapshot entry point) still reads."""
    _register(client)
    owner = _user_id(session_factory)
    with session_factory() as session:
        run = create_run(
            session, owner_id=owner, name="Older run", criteria_profile="plain_chatbot"
        )
        update_run(session, run, state=RunState.FAILED, verdict_reason="boom")
        session.commit()
        run_id = run.id

    body = client.get(f"/api/v1/runs/{run_id}").json()
    assert body["name"] == "Older run"
    assert body["state"] == "failed"
    assert body["entry_point"] == "http_endpoint"
    assert body["verdict_reason"] == "boom"


# ---- run caps (quirk 14) --------------------------------------------------


def test_run_caps_are_stored_in_the_snapshot_and_read_back(
    client: TestClient, runtime: SimpleNamespace
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body["max_cases"] = 5
    body["max_duration_seconds"] = 120
    body["max_total_tokens"] = 4000

    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 202, response.text
    limits = response.json()["limits"]
    assert limits["max_cases"] == 5
    assert limits["max_duration_seconds"] == 120
    assert limits["max_total_tokens"] == 4000
    assert limits["stopped_by"] is None
    assert limits["stop_reason"] is None
    assert limits["tokens_not_instrumented"] is False


def test_a_run_without_caps_still_reports_the_duration_default(
    client: TestClient, runtime: SimpleNamespace
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)

    response = client.post("/api/v1/runs", json=_body(dataset))
    assert response.status_code == 202, response.text
    limits = response.json()["limits"]
    assert limits["max_cases"] is None
    assert limits["max_duration_seconds"] == 1800
    assert limits["max_total_tokens"] is None


@pytest.mark.parametrize(
    "caps",
    [
        {"max_cases": 0},
        {"max_cases": 1001},
        {"max_duration_seconds": 29},
        {"max_duration_seconds": 14401},
        {"max_total_tokens": 0},
    ],
)
def test_out_of_range_caps_are_rejected_with_422(
    client: TestClient, runtime: SimpleNamespace, caps: dict[str, int]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body.update(caps)

    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    # Nothing was queued for a request that never validated.
    assert runtime.queue == []


def test_a_quick_test_carries_the_same_caps(client: TestClient, runtime: SimpleNamespace) -> None:
    _register(client)
    response = client.post(
        "/api/v1/quick-test",
        json={
            "entry_point": "http_endpoint",
            "target": "http://127.0.0.1:9099/ask",
            "tests": ["quality"],
            "csv": CSV_BYTES.decode(),
            "allow_private_targets": True,
            "max_cases": 2,
            "max_total_tokens": 900,
        },
    )
    assert response.status_code == 202, response.text
    limits = response.json()["run"]["limits"]
    assert limits["max_cases"] == 2
    assert limits["max_total_tokens"] == 900


def test_a_smoke_run_is_flagged_and_capped(client: TestClient, runtime: SimpleNamespace) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    body = _body(dataset)
    body["is_smoke"] = True

    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["is_smoke"] is True
    assert payload["limits"]["max_cases"] == 5
