"""M6a: repository functions for runs, run items and metric results."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import RunItemState, RunState, User
from app.services.run_repository import (
    RepositoryError,
    add_metric_result,
    create_run,
    create_run_item,
    get_metric_results,
    get_run,
    list_run_items,
    list_runs,
    update_run,
    update_run_item,
)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def owner(db: Session) -> User:
    user = User(email="owner@example.test", name="Owner", password_hash="hash")
    db.add(user)
    db.flush()
    return user


def _other_user(db: Session) -> User:
    user = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.test",
        name="Other",
        password_hash="hash",
    )
    db.add(user)
    db.flush()
    return user


def test_create_run_defaults_to_queued(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Nightly")

    assert run.id is not None
    assert run.state == "queued"
    assert run.verdict is None
    assert run.score is None
    assert run.verdict_reason is None
    assert run.is_partial is False
    assert run.settings_snapshot == {}
    assert run.criteria_profile == "plain_chatbot"
    assert run.started_at is None and run.completed_at is None
    assert run.created_at is not None and run.updated_at is not None


def test_create_run_stores_settings_snapshot(db: Session, owner: User) -> None:
    snapshot = {"target_url": "http://localhost:9000/chat", "timeout_seconds": 60}
    run = create_run(
        db,
        owner_id=owner.id,
        name="Snapshot",
        settings_snapshot=snapshot,
        criteria_profile="rag_chatbot",
    )

    assert run.settings_snapshot == snapshot
    assert run.criteria_profile == "rag_chatbot"
    stored = get_run(db, run.id)
    assert stored is not None
    assert stored.settings_snapshot["target_url"] == "http://localhost:9000/chat"


def test_run_states_match_the_spec() -> None:
    # ``stopped_by_limit`` is the state a run cap ends in (quirk 14): it keeps a
    # verdict for the cases that were measured, but it is not a whole-dataset
    # result, so it is its own state rather than "completed".
    assert {state.value for state in RunState} == {
        "queued",
        "running",
        "cancelling",
        "cancelled",
        "failed",
        "completed",
        "stopped_by_limit",
    }
    assert RunState.QUEUED.value == "queued"
    assert {state.value for state in RunItemState} == {
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    }


def test_get_run_scopes_to_owner(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Mine")
    other = _other_user(db)

    assert get_run(db, run.id, owner_id=owner.id) is run
    assert get_run(db, run.id, owner_id=other.id) is None
    assert get_run(db, uuid.uuid4()) is None


def test_list_runs_filters_by_owner_and_paginates(db: Session, owner: User) -> None:
    other = _other_user(db)
    first = create_run(db, owner_id=owner.id, name="First")
    second = create_run(db, owner_id=owner.id, name="Second")
    create_run(db, owner_id=other.id, name="Theirs")

    base = datetime(2026, 10, 24, tzinfo=UTC)
    first.created_at = base
    second.created_at = base + timedelta(seconds=1)
    db.flush()

    assert [run.name for run in list_runs(db, owner.id)] == ["Second", "First"]
    assert [run.name for run in list_runs(db, owner.id, limit=1)] == ["Second"]
    assert [run.name for run in list_runs(db, owner.id, limit=1, offset=1)] == ["First"]


def test_update_run_records_verdict_and_partial(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Verdict")

    update_run(db, run, state=RunState.RUNNING, started_at=datetime.now(UTC))
    assert run.state == "running"

    update_run(
        db,
        run,
        state=RunState.COMPLETED,
        verdict="NO_GO",
        score=0.42,
        verdict_reason="Weighted score 0.42 is below the REVIEW threshold 0.60.",
        is_partial=True,
        completed_at=datetime.now(UTC),
    )

    stored = get_run(db, run.id)
    assert stored is not None
    assert stored.state == "completed"
    assert stored.verdict == "NO_GO"
    assert stored.score == 0.42
    assert stored.is_partial is True
    assert stored.verdict_reason is not None and "REVIEW threshold 0.60" in stored.verdict_reason
    assert stored.started_at is not None and stored.completed_at is not None


def test_update_run_accepts_plain_string_state(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="String state")

    update_run(db, run, state="running")

    assert run.state == "running"


def test_update_run_rejects_unknown_state(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Bad state")

    with pytest.raises(RepositoryError, match="unknown state"):
        update_run(db, run, state="paused")

    assert run.state == "queued"


def test_update_run_rejects_unknown_field(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Typo")

    with pytest.raises(RepositoryError, match="unknown fields"):
        update_run(db, run, verdikt="GO")


def test_create_and_list_run_items(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Items")
    first = create_run_item(db, run, row_index=1, input_text="What is Merit?")
    second = create_run_item(db, run, row_index=2, input_text="Who qualifies?")

    assert first.state == "queued"
    assert first.run_id == run.id
    assert first.output is None and first.error is None

    items = list_run_items(db, run.id)
    assert [item.row_index for item in items] == [1, 2]
    assert items[1] is second
    assert items[1].input_text == "Who qualifies?"


def test_run_item_row_index_is_unique_per_run(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Unique")
    create_run_item(db, run, row_index=1, input_text="first")

    with pytest.raises(IntegrityError):
        create_run_item(db, run, row_index=1, input_text="duplicate")
    db.rollback()


def test_update_run_item_stores_output_and_failure(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Item update")
    item = create_run_item(db, run, row_index=1, input_text="q")

    update_run_item(
        db,
        item,
        state=RunItemState.FAILED,
        error="request timed out after 30s",
        latency_ms=30000,
    )
    assert item.state == "failed"
    assert item.error == "request timed out after 30s"
    assert item.latency_ms == 30000

    update_run_item(
        db,
        item,
        state=RunItemState.COMPLETED,
        output="The answer",
        retrieved_context=["chunk a"],
        trace={"status_code": 200},
        error=None,
    )
    assert item.state == "completed"
    assert item.output == "The answer"
    assert item.retrieved_context == ["chunk a"]
    assert item.error is None


def test_update_run_item_rejects_run_only_states(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Item state guard")
    item = create_run_item(db, run, row_index=1, input_text="q")

    with pytest.raises(RepositoryError, match="unknown state"):
        update_run_item(db, item, state="cancelling")


def test_add_and_get_metric_results(db: Session, owner: User) -> None:
    run = create_run(db, owner_id=owner.id, name="Metrics")
    item = create_run_item(db, run, row_index=1, input_text="q")

    add_metric_result(
        db,
        run,
        name="error_rate",
        score=1.0,
        passed=True,
        explanation="0 of 12 items failed.",
        weight=0.1,
        threshold=0.95,
    )
    add_metric_result(
        db,
        run,
        name="retrieval_context_recall",
        score=0.0,
        passed=False,
        explanation="No reference context tokens were found in the response.",
        instrumented=False,
        run_item_id=item.id,
        hard_gate=True,
        details={"missing": ["chunk a"]},
    )

    results = {result.name: result for result in get_metric_results(db, run.id)}
    assert set(results) == {"error_rate", "retrieval_context_recall"}

    run_level = results["error_rate"]
    assert run_level.run_item_id is None
    assert run_level.passed is True
    assert run_level.instrumented is True
    assert run_level.weight == 0.1 and run_level.threshold == 0.95

    item_level = results["retrieval_context_recall"]
    assert item_level.run_item_id == item.id
    assert item_level.score == 0.0
    assert item_level.instrumented is False
    assert item_level.hard_gate is True
    assert item_level.details == {"missing": ["chunk a"]}
