"""The duplicate-start hash: what makes two starts the same run (quirk 13).

``_idempotency_hash`` decides whether a second POST returns the existing run or
creates a new one, so any setting that changes what the worker sends or spends
has to be in it. These tests work on the hash directly: the API-level window is
covered in ``tests/test_runs_api.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.schemas.runs import RunCreateRequest
from app.services.run_service import _idempotency_hash, build_snapshot

DATASET_VERSION = uuid.uuid4()


def _payload(**overrides: Any) -> RunCreateRequest:
    body: dict[str, Any] = {
        "entry_point": "http_endpoint",
        "target": "http://127.0.0.1:9099/ask",
        "dataset_version_id": DATASET_VERSION,
        "body_template": '{"question": {{input}}}',
        "answer_path": "answer",
        "allow_private_targets": True,
        "max_cases": 5,
    }
    body.update(overrides)
    return RunCreateRequest.model_validate(body)


def _snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot = build_snapshot(
        _payload(), dataset_version_id=DATASET_VERSION, entry_point="http_endpoint"
    )
    snapshot.update(overrides)
    return snapshot


def test_a_different_query_key_is_a_different_run() -> None:
    """A GET run asks a different question when its query key changes."""
    payload = _payload()
    question = _snapshot(query_key="question")
    text = _snapshot(query_key="q")

    assert _idempotency_hash(payload, question) != _idempotency_hash(payload, text)

    # The rest of the settings are identical, so only the key can differ.
    assert {k: v for k, v in question.items() if k != "query_key"} == {
        k: v for k, v in text.items() if k != "query_key"
    }


def test_the_same_query_key_twice_is_one_run() -> None:
    payload = _payload()
    first = _snapshot(query_key="question")
    second = _snapshot(query_key="question")

    assert _idempotency_hash(payload, first) == _idempotency_hash(payload, second)


def test_a_missing_query_key_still_hashes() -> None:
    """A POST run has no query key at all: that is a stable, empty value."""
    payload = _payload()

    assert _idempotency_hash(payload, _snapshot()) == _idempotency_hash(payload, _snapshot())
