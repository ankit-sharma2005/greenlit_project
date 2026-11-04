"""STEP 2: the first-contact check before a full run.

The check sends exactly one harmless request with the run's own settings, shows
what GreenLit reads back with every secret masked, and remembers that a person
accepted that reading. A remote run then needs that accepted check, bound to the
same configuration — anything else is refused with a message that says why.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.schemas.runs import RunCreateRequest
from app.services import target_check
from app.services.connectors import ConnectorError, Trace
from app.services.run_service import get_enqueue
from app.services.target_check import (
    _CANDIDATE_DEPTH,
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


def hello_trace_with_raw(
    raw_body: dict[str, Any] | str,
    text_output: str = "Hello from the quirk server",
    status: int | None = 200,
) -> Trace:
    return Trace(
        output=text_output,
        retrieved_context="not instrumented",
        tool_calls="not instrumented",
        latency_ms=12,
        tokens_in=None,
        tokens_out=None,
        error=None,
        raw=raw_body,
        status_code=status,
    )


PASSWORD = "correct horse battery staple"

SECRET_TOKEN = "sk-live-SECRET-1234567890"


@pytest.fixture(autouse=True)
def runtime() -> Iterator[SimpleNamespace]:
    """Use an in-memory queue so run-start tests do not need Redis or a broker."""
    queue: list[uuid.UUID] = []
    app.dependency_overrides[get_enqueue] = lambda: queue.append
    yield SimpleNamespace(queue=queue)
    app.dependency_overrides.pop(get_enqueue, None)


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


def test_answer_candidates_are_collected_from_a_json_response() -> None:
    response_body = {
        "choices": [
            {"message": {"content": "NewRelic says the site is up."}},
            {"message": {"content": "Second choice."}},
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }
    outcome = run_check(
        SNAPSHOT,
        input_text=HARMLESS_INPUT,
        sender=lambda _request_text: hello_trace_with_raw(
            response_body,
            text_output=response_body["choices"][0]["message"]["content"],
        ),
    )

    assert outcome.hint is None
    assert outcome.answer == response_body["choices"][0]["message"]["content"]
    assert outcome.raw_response == response_body
    candidates = target_check.answer_candidates(outcome.raw_response)
    assert len(candidates) >= 2
    paths = [c.path for c in candidates]
    assert "choices[0].message.content" in paths
    assert "choices[1].message.content" in paths


def test_answer_candidates_is_empty_for_non_json() -> None:
    # answer_candidates is empty when the stored raw is not a JSON object.
    candidates = target_check.answer_candidates("this is plain text, not json")
    assert candidates == []


def test_answer_candidates_are_empty_for_html() -> None:
    html = "<!doctype html><html><body>Please sign in</body></html>"
    assert target_check.answer_candidates(html) == []


def test_answer_candidates_walk_nested_custom_response() -> None:
    response_body = {
        "result": {
            "payload": {
                "responses": [
                    {"text": "First custom answer"},
                    {"text": "Second custom answer"},
                ]
            }
        }
    }

    candidates = target_check.answer_candidates(response_body)

    assert [(item.path, item.preview) for item in candidates] == [
        ("result.payload.responses[0].text", "First custom answer"),
        ("result.payload.responses[1].text", "Second custom answer"),
    ]


def test_answer_candidates_redact_a_secret_in_the_response() -> None:
    candidates = target_check.answer_candidates(
        {"choices": [{"message": {"content": f"Call me at {SECRET_TOKEN}"}}]}
    )
    assert len(candidates) == 1
    assert "SECRET-1234567890" not in candidates[0].preview
    assert "sk-live-" not in candidates[0].preview


def test_answer_candidates_are_limited_by_count_preview_and_depth() -> None:
    response_body: dict[str, Any] = {
        "token": "sk-live-SECRET-1234567890",
        **{f"answer_{index}": "x" * 200 for index in range(12)},
    }
    deeply_nested: dict[str, Any] = {"answer": "too deep"}
    for _ in range(_CANDIDATE_DEPTH):
        deeply_nested = {"nested": deeply_nested}

    candidates = target_check.answer_candidates(response_body)

    assert len(candidates) == target_check.MAX_CANDIDATES
    assert all(
        len(candidate.preview) <= target_check.MAX_CANDIDATE_PREVIEW for candidate in candidates
    )
    assert all("SECRET-1234567890" not in candidate.preview for candidate in candidates)
    assert target_check.answer_candidates(deeply_nested) == []


def test_question_path_found_for_an_exact_body_match() -> None:
    request_body = {"messages": [{"role": "user", "content": "Hello"}]}
    paths = target_check.find_question_paths(request_body, "Hello")
    assert paths == ["messages[0].content"]


def test_question_path_returns_none_when_no_field_matches() -> None:
    request_body = {"messages": [{"role": "user", "content": "Hello"}]}
    assert target_check.find_question_path(request_body, "not sent") is None


def test_question_path_returns_none_when_more_than_one_field_matches() -> None:
    request_body = {
        "question": "Hello",
        "input": "Hello",
    }
    assert target_check.find_question_path(request_body, "Hello") is None


def test_question_paths_are_depth_limited_and_preview_truncated() -> None:
    body: dict[str, Any] = {"nested": {}}
    current = body["nested"]
    for _i in range(_CANDIDATE_DEPTH + 1):
        current = {"k": current}
    body["nested"] = current

    candidates = target_check.answer_candidates(body)
    # The deepest leaf is beyond the depth limit, so only the intermediate
    # container path shows up as a candidate when it has no printable preview.
    assert all(c.path.count(".") <= _CANDIDATE_DEPTH for c in candidates)


def test_run_create_request_rejects_sample_question() -> None:
    with pytest.raises(ValidationError) as caught:
        RunCreateRequest(sample_question="This field belongs on target checks")
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


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


@pytest.mark.parametrize(
    ("body_template", "expected_path", "expected_reason"),
    [
        (
            '{"messages":[{"role":"user","content": {{input}}}]}',
            "messages[0].content",
            None,
        ),
        (
            '{"question": {{input}}, "input": {{input}}}',
            None,
            "More than one request body field matched the sample question; no path was selected.",
        ),
        (
            '{"question": "different"}',
            None,
            "No request body field matched the sample question; no path was selected.",
        ),
    ],
)
def test_api_check_returns_candidates_and_question_path_result(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    body_template: str,
    expected_path: str | None,
    expected_reason: str | None,
) -> None:
    register(client, email="question-path@example.com")
    response_body = {
        "choices": [{"message": {"content": "Answer preview"}}],
        "result": {"reply": "Nested custom answer"},
    }
    real_run_check = target_check.run_check

    def run_with_json_response(
        snapshot: Any, *, input_text: str, sender: Any = None
    ) -> CheckOutcome:
        return real_run_check(
            snapshot,
            input_text=input_text,
            sender=lambda _: hello_trace_with_raw(response_body, text_output="Answer preview"),
        )

    monkeypatch.setattr(target_check, "run_check", run_with_json_response)
    payload = dict(
        REMOTE_BODY,
        body_template=body_template,
        sample_question="The exact sample question",
    )

    response = client.post("/api/v1/targets/check", json=payload)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["question_path"] == expected_path
    assert result["question_path_reason"] == expected_reason
    candidate_paths = [candidate["path"] for candidate in result["answer_candidates"]]
    assert "choices[0].message.content" in candidate_paths
    assert "result.reply" in candidate_paths


def test_api_check_returns_no_candidates_for_html(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client, email="html-response@example.com")
    real_run_check = target_check.run_check

    def run_with_html_response(
        snapshot: Any, *, input_text: str, sender: Any = None
    ) -> CheckOutcome:
        return real_run_check(
            snapshot,
            input_text=input_text,
            sender=lambda _: hello_trace_with_raw(
                "<!doctype html><html><body>Login</body></html>",
                text_output="<!doctype html><html><body>Login</body></html>",
            ),
        )

    monkeypatch.setattr(target_check, "run_check", run_with_html_response)

    response = client.post("/api/v1/targets/check", json=REMOTE_BODY)

    assert response.status_code == 200, response.text
    assert response.json()["answer_candidates"] == []


def test_the_api_check_then_accept_unlocks_a_remote_run(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    runtime: SimpleNamespace,
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
    assert len(runtime.queue) == 1
    assert str(runtime.queue[0]) == started.json()["id"]


def test_a_remote_run_without_a_check_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    dataset = approve_dataset(client)

    body = dict(REMOTE_BODY, dataset_id=dataset["id"], test_types=["quality"])
    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 422, response.text
    assert "Check the target first" in response.text


def test_a_local_run_needs_no_check(client: TestClient, runtime: SimpleNamespace) -> None:
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
    assert len(runtime.queue) == 1
    assert str(runtime.queue[0]) == response.json()["id"]


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
