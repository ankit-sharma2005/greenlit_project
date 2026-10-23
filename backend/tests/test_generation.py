"""M4b service tests: test-case generation and generated draft versions."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session, sessionmaker
from tests.test_datasets_service import CSV_BYTES, _make_user

from app.models import DatasetItem, Provider
from app.services.datasets import DatasetError, create_dataset
from app.services.generation import (
    GenerationError,
    create_generated_version,
    generate_test_cases,
    parse_cases,
)

VALID_CASES = [
    {"question": "q1", "answer": "a1", "context": None, "category": "factual"},
    {"question": "q2", "answer": "a2", "context": "ctx", "category": "edge_case"},
]


def test_parse_cases_plain_array() -> None:
    cases = parse_cases(json.dumps(VALID_CASES), count=10)
    assert cases == VALID_CASES


def test_parse_cases_strips_code_fences() -> None:
    fenced = "```json\n" + json.dumps(VALID_CASES) + "\n```"
    assert parse_cases(fenced, count=10) == VALID_CASES


def test_parse_cases_rejects_garbage() -> None:
    with pytest.raises(GenerationError) as excinfo:
        parse_cases("I cannot help with that.", count=5)
    assert excinfo.value.code == "invalid_response"

    with pytest.raises(GenerationError) as not_array:
        parse_cases('{"question": "q"}', count=5)
    assert not_array.value.code == "invalid_response"


def test_parse_cases_skips_incomplete_and_caps_count() -> None:
    payload = [
        {"question": "", "answer": "skipped"},
        {"question": "q1", "answer": "a1"},
        {"question": "q2", "answer": ""},
        {"question": "q3", "answer": "a3"},
        {"question": "q4", "answer": "a4"},
    ]
    cases = parse_cases(json.dumps(payload), count=2)
    assert [case["question"] for case in cases] == ["q1", "q3"]


def _fake_provider() -> Provider:
    return Provider(
        name="gen-test",
        kind="openai-compatible",
        model_name="test-model",
        base_url="http://localhost:9/v1",
        timeout_seconds=5,
    )


def test_generate_test_cases_retries_once() -> None:
    calls: list[str] = []

    def flaky_chat(provider: Provider, messages: list[dict[str, str]], t: float, m: int) -> str:
        calls.append(messages[-1]["content"])
        if len(calls) == 1:
            return "not json"
        return json.dumps(VALID_CASES)

    cases = generate_test_cases(_fake_provider(), count=5, chat=flaky_chat)
    assert len(cases) == 2
    assert len(calls) == 2


def test_generate_test_cases_fails_after_two_bad_replies() -> None:
    def broken_chat(provider: Provider, messages: list[dict[str, str]], t: float, m: int) -> str:
        return "still not json"

    with pytest.raises(GenerationError) as excinfo:
        generate_test_cases(_fake_provider(), count=5, chat=broken_chat)
    assert excinfo.value.code == "invalid_response"


def test_generate_test_cases_includes_source_text() -> None:
    seen: list[str] = []

    def chat(provider: Provider, messages: list[dict[str, str]], t: float, m: int) -> str:
        seen.append(messages[-1]["content"])
        return json.dumps(VALID_CASES)

    generate_test_cases(
        _fake_provider(), count=3, source_text="The Merit Scholarship covers tuition.", chat=chat
    )
    assert "Merit Scholarship" in seen[0]
    assert "exactly 3 test cases" in seen[0]


def test_create_generated_version(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)
    dataset = create_dataset(
        session,
        owner_id=user.id,
        name="With generated",
        source_filename="seed.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()

    version = create_generated_version(session, dataset, VALID_CASES)
    session.commit()

    assert version.generated is True
    assert version.approved_at is None
    assert version.version_no == 2
    assert version.row_count == 2
    assert version.columns_snapshot == {"columns": ["question", "answer", "context", "category"]}
    items = session.query(DatasetItem).filter_by(dataset_version_id=version.id).all()
    assert [item.data["question"] for item in items] == ["q1", "q2"]

    # Same cases produce the same hash (reproducible preview/approval pairing).
    again = create_generated_version(session, dataset, VALID_CASES)
    assert again.content_hash == version.content_hash
    assert again.version_no == 3

    with pytest.raises(GenerationError):
        create_generated_version(session, dataset, [])


def test_create_generated_version_needs_existing_dataset(
    session_factory: sessionmaker[Session],
) -> None:
    session = session_factory()
    user = _make_user(session)
    dataset = create_dataset(
        session,
        owner_id=user.id,
        name="Plain",
        source_filename="seed.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()

    # A generated version can be approved like any other version.
    from app.services.datasets import approve_dataset_version

    version = create_generated_version(session, dataset, VALID_CASES)
    approved = approve_dataset_version(session, dataset, version.version_no, approver_id=user.id)
    session.commit()
    assert approved.approved_at is not None

    # An uploaded version cannot be approved if its number is unknown.
    with pytest.raises(DatasetError):
        approve_dataset_version(session, dataset, 99, approver_id=user.id)
