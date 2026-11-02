"""STEP 2: the first-contact check before a full run.

The check sends exactly one harmless request with the run's own settings, shows
what GreenLit reads back with every secret masked, and remembers that a person
accepted that reading. A remote run then needs that accepted check, bound to the
same configuration — anything else is refused with a message that says why.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.services import target_check
from app.services.connectors import ConnectorError, Trace
from app.services.target_check import (
    HARMLESS_INPUT,
    CheckOutcome,
    TargetCheckError,
    accept_check,
    fingerprint,
    record_check,
    require_accepted_check,
    run_check,
)
from tests.support.quirk_server import start_quirk

PASSWORD = "correct horse battery staple"

SECRET_TOKEN = "sk-live-SECRET-1234567890"

SNAPSHOT: dict[str, Any] = {
    "url": "https://app.example.com/chat?token=abc123&lang=en",
    "method": "post",
    "body_template": '{"question": {{input}}}',
    "headers": {"Authorization": f"Bearer {SECRET_TOKEN}", "X-Trace": "on"},
    "answer_path": "answer",
    "context_path": None,
    "timeout_seconds": 5,
    "response_format": "json",
    "stream_content_path": None,
    "allow_private_targets": True,
    "max_retries": 3,
}


def hello_trace(output: str = "Hi there", status: int | None = 200) -> Trace:
    return Trace(
        output=output,
        retrieved_context="not instrumented",
        tool_calls="not instrumented",
        latency_ms=12,
        tokens_in=None,
        tokens_out=None,
        error=None,
        raw={"answer": output},
        status_code=status,
    )


# ---- one request, redacted ------------------------------------------------


def test_a_check_sends_exactly_one_request_and_reads_the_answer() -> None:
    server = start_quirk("json")
    try:
        snapshot = dict(SNAPSHOT, url=server.url, max_retries=3)
        outcome = run_check(snapshot, input_text=HARMLESS_INPUT)
    finally:
        server.close()

    assert outcome.answer == "Hello from the quirk server"
    assert outcome.status == 200
    assert outcome.error is None
    assert outcome.hint is None
    # One request by definition: the polite retry setting does not apply.
    assert server.calls == 1


def test_the_request_is_shown_with_every_secret_masked() -> None:
    outcome = run_check(SNAPSHOT, input_text="What is GreenLit?", sender=lambda _: hello_trace())

    assert outcome.request["method"] == "POST"
    assert "token=XXXX" in outcome.request["url"]
    assert "abc123" not in json.dumps(outcome.request)
    assert outcome.request["headers"] == {"Authorization": "XXXX", "X-Trace": "XXXX"}
    assert SECRET_TOKEN not in json.dumps(outcome.request)
    assert '"What is GreenLit?"' in outcome.request["body"]
    assert outcome.mapping_path == "answer"


def test_an_empty_extraction_hints_at_the_path_and_the_cookie() -> None:
    outcome = run_check(SNAPSHOT, input_text=HARMLESS_INPUT, sender=lambda _: hello_trace(""))

    assert outcome.answer == ""
    assert outcome.hint is not None
    assert "answer path" in outcome.hint
    assert "cookie" in outcome.hint


def test_an_html_answer_hints_at_a_login_page() -> None:
    page = "<!doctype html><html><body>Please sign in</body></html>"
    outcome = run_check(SNAPSHOT, input_text=HARMLESS_INPUT, sender=lambda _: hello_trace(page))

    assert outcome.hint is not None
    assert "HTML" in outcome.hint
    assert "login" in outcome.hint


def test_a_long_answer_is_capped_not_stored_whole() -> None:
    outcome = run_check(
        SNAPSHOT, input_text=HARMLESS_INPUT, sender=lambda _: hello_trace("x" * 900)
    )

    assert outcome.answer_truncated is True
    assert len(outcome.answer) <= target_check.MAX_ANSWER_CHARS + 1
    assert outcome.hint is None


def test_a_failed_check_keeps_its_structured_error() -> None:
    def fail(_: str) -> Trace:
        raise ConnectorError(
            "Target returned HTTP 500 at app.example.com/chat",
            code="http_error",
            details={
                "status_code": 500,
                "target": "app.example.com/chat",
                "snippet": "boom sk-live-SECRET-9999999999",
            },
        )

    outcome = run_check(SNAPSHOT, input_text=HARMLESS_INPUT, sender=fail)

    assert outcome.status == 500
    assert outcome.error is not None
    assert outcome.error["kind"] == "http_error"
    assert outcome.error["target"] == "app.example.com/chat"
    # The snippet is redacted before it is stored or shown.
    assert "SECRET-9999999999" not in json.dumps(outcome.error)
    assert outcome.hint is None


# ---- the accepted check is a gate -----------------------------------------


def stored_check(owner: uuid.UUID, snapshot: dict[str, Any]) -> target_check.TargetCheck:
    return record_check(
        owner_id=owner,
        config_hash=fingerprint(snapshot),
        result={"answer": "Hi there", "extraction_ok": True, "error": None, "request": {}},
    )


def test_an_accepted_check_unlocks_the_same_configuration() -> None:
    owner = uuid.uuid4()
    check = stored_check(owner, SNAPSHOT)
    accept_check(check.id, owner)

    unlocked = require_accepted_check(owner_id=owner, check_id=check.id, snapshot=SNAPSHOT)
    assert unlocked.accepted is True


def test_a_changed_setting_needs_a_new_check() -> None:
    owner = uuid.uuid4()
    check = stored_check(owner, SNAPSHOT)
    accept_check(check.id, owner)
    changed = dict(SNAPSHOT, answer_path="data.answer")

    with pytest.raises(TargetCheckError) as caught:
        require_accepted_check(owner_id=owner, check_id=check.id, snapshot=changed)
    assert caught.value.code == "target_check_stale"
    assert (
        caught.value.message == "The target settings changed after the check, run the check again."
    )


def test_an_unaccepted_check_does_not_unlock_a_run() -> None:
    owner = uuid.uuid4()
    check = stored_check(owner, SNAPSHOT)

    with pytest.raises(TargetCheckError) as caught:
        require_accepted_check(owner_id=owner, check_id=check.id, snapshot=SNAPSHOT)
    assert caught.value.code == "target_check_not_accepted"


def test_a_missing_check_is_refused_with_what_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TargetCheckError) as caught:
        require_accepted_check(owner_id=uuid.uuid4(), check_id=None, snapshot=SNAPSHOT)
    assert caught.value.code == "target_check_required"
    assert "Check the target first" in caught.value.message


def test_an_expired_check_must_be_run_again(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = uuid.uuid4()
    check = stored_check(owner, SNAPSHOT)
    accept_check(check.id, owner)
    later = target_check._now() + target_check.CHECK_TTL_SECONDS + 1
    monkeypatch.setattr(target_check, "_now", lambda: later)

    with pytest.raises(TargetCheckError) as caught:
        require_accepted_check(owner_id=owner, check_id=check.id, snapshot=SNAPSHOT)
    assert caught.value.code == "target_check_expired"


def test_another_owners_check_is_never_found() -> None:
    owner = uuid.uuid4()
    check = stored_check(owner, SNAPSHOT)
    accept_check(check.id, owner)

    with pytest.raises(TargetCheckError) as caught:
        require_accepted_check(owner_id=uuid.uuid4(), check_id=check.id, snapshot=SNAPSHOT)
    assert caught.value.code == "target_check_required"


def test_a_failed_check_cannot_be_accepted() -> None:
    owner = uuid.uuid4()
    check = record_check(
        owner_id=owner,
        config_hash=fingerprint(SNAPSHOT),
        result={
            "answer": "",
            "extraction_ok": False,
            "error": {"kind": "connection"},
            "request": {},
        },
    )

    with pytest.raises(TargetCheckError) as caught:
        accept_check(check.id, owner)
    assert caught.value.code == "target_check_failed"


# ---- through the API ------------------------------------------------------

REMOTE_BODY: dict[str, Any] = {
    "target": "https://app.example.com/chat?token=abc123",
    "method": "POST",
    "body_template": '{"question": {{input}}}',
    "headers": {"Authorization": f"Bearer {SECRET_TOKEN}"},
    "answer_path": "answer",
    "permission_confirmed": True,
    "permission_reference": "Ops ticket 4711",
}


def register(client: TestClient, email: str = "check@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Checker", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def approve_dataset(client: TestClient) -> dict[str, Any]:
    uploaded = client.post(
        "/api/v1/datasets",
        data={"name": "Check set"},
        files={
            "file": (
                "check.csv",
                b"question,answer\nWhat is GreenLit?,GreenLit tests LLM apps.\n",
                "text/csv",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset = uploaded.json()
    approved = client.post(f"/api/v1/datasets/{dataset['id']}/versions/1/approve")
    assert approved.status_code == 200, approved.text
    return dataset


@pytest.fixture(autouse=True)
def empty_checks() -> Any:
    target_check.clear_checks()
    yield
    target_check.clear_checks()


def fake_check(monkeypatch: pytest.MonkeyPatch, answer: str = "Hi there") -> None:
    """The check's own request, without contacting anything."""

    def run(snapshot: Any, *, input_text: str, sender: Any = None) -> CheckOutcome:
        return run_check(
            dict(snapshot), input_text=input_text, sender=lambda _: hello_trace(answer)
        )

    monkeypatch.setattr(target_check, "run_check", run)


def test_the_api_check_then_accept_unlocks_a_remote_run(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register(client)
    dataset = approve_dataset(client)
    fake_check(monkeypatch)

    response = client.post("/api/v1/targets/check", json=REMOTE_BODY)
    assert response.status_code == 200, response.text
    check = response.json()
    assert check["accepted"] is False
    assert check["answer"] == "Hi there"
    assert check["request"]["headers"] == {"Authorization": "XXXX"}
    assert "token=XXXX" in check["request"]["url"]
    # The secret is nowhere in the reply, not even in the redacted request.
    assert SECRET_TOKEN not in response.text
    assert "abc123" not in response.text

    # A full run is refused until the extraction is accepted.
    body = dict(
        REMOTE_BODY,
        dataset_id=dataset["id"],
        test_types=["quality"],
        target_check_id=check["check_id"],
    )
    refused = client.post("/api/v1/runs", json=body)
    assert refused.status_code == 422, refused.text
    assert "Confirm that the extracted answer looks right" in refused.text

    accepted = client.post(f"/api/v1/targets/check/{check['check_id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted"] is True

    started = client.post("/api/v1/runs", json=body)
    assert started.status_code == 202, started.text
    assert started.json()["permission"]["reference"] == "Ops ticket 4711"


def test_a_remote_run_without_a_check_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    dataset = approve_dataset(client)

    body = dict(REMOTE_BODY, dataset_id=dataset["id"], test_types=["quality"])
    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 422, response.text
    assert "Check the target first" in response.text


def test_a_local_run_needs_no_check(client: TestClient) -> None:
    register(client)
    dataset = approve_dataset(client)
    body = {
        "entry_point": "http_endpoint",
        "target": "http://127.0.0.1:9099/ask",
        "dataset_id": dataset["id"],
        "dataset_version_id": dataset["versions"][0]["id"],
        "test_types": ["quality"],
        "allow_private_targets": True,
    }

    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 202, response.text


def test_accept_after_the_check_expired_is_a_clear_conflict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    fake_check(monkeypatch)
    check = client.post("/api/v1/targets/check", json=REMOTE_BODY).json()

    later = target_check._now() + target_check.CHECK_TTL_SECONDS + 1
    monkeypatch.setattr(target_check, "_now", lambda: later)
    response = client.post(f"/api/v1/targets/check/{check['check_id']}/accept")

    assert response.status_code == 409, response.text
    assert "expired" in response.text
