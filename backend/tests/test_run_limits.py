"""Quirk 14: the per-run caps — cases, duration and tokens.

A cap decides when the run stops asking; it never changes how a case is scored.
Everything measured before the cap keeps its verdict, the cases that were never
sent are "not run" with the reason that named the cap, and the run's state says
``stopped_by_limit`` so no summary reads it as a whole-dataset result.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import Run, RunItemState, User
from app.services.connectors import Trace
from app.services.run_executor import execute_run
from app.services.run_progress import MemoryProgress
from app.services.run_repository import get_metric_results, list_run_items
from tests.test_run_executor import ROWS, FakeSender, echo_answers, seed_run


@pytest.fixture
def owner(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        user = User(
            email=f"limits-{uuid.uuid4().hex[:8]}@example.com",
            name="Limits",
            password_hash="x",
            role="admin",
        )
        session.add(user)
        session.commit()
        return user.id


def run_with_limits(
    run_id: uuid.UUID,
    session_factory: sessionmaker[Session],
    sender: FakeSender | None = None,
    *,
    sender_factory: Callable[[Mapping[str, Any], Callable[[], Session]], Callable[[str], Trace]]
    | None = None,
    parallelism: int = 1,
) -> dict[str, Any]:
    """Execute a run and return its report, without Redis or a broker."""
    progress = MemoryProgress()
    report = execute_run(
        run_id,
        session_factory=session_factory,
        sender_factory=sender_factory or (sender.factory if sender else None),
        progress=progress,
        parallelism=parallelism,
    )
    return report


def token_sender(tokens_in: int | None, tokens_out: int | None) -> Any:
    """A sender whose answers report exactly these token counts (or none)."""

    def factory(
        snapshot: Mapping[str, Any], session_factory: Callable[[], Session]
    ) -> Callable[[str], Trace]:
        answers = echo_answers()
        snapshots = dict(snapshot)

        def send(input_text: str) -> Trace:
            assert snapshots["url"] == "http://fake.test/ask"
            return Trace(
                output=answers.get(input_text, "ok"),
                retrieved_context="not instrumented",
                tool_calls="not instrumented",
                latency_ms=10,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error=None,
                raw={"echo": input_text},
            )

        return send

    return factory


def load_run(session_factory: sessionmaker[Session], run_id: uuid.UUID) -> Run:
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run


def test_max_cases_stops_the_run_and_keeps_what_was_measured(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, settings_extra={"max_cases": 1})
    report = run_with_limits(run_id, session_factory, FakeSender(answers=echo_answers()))

    assert report["status"] == "stopped_by_limit", report
    assert report["items_completed"] == 1
    assert report["items_cancelled"] == 2
    run = load_run(session_factory, run_id)
    assert run.state == "stopped_by_limit"
    assert run.is_partial is True
    # The rules still ran on the one case that was measured; the reason says so.
    assert run.verdict is not None
    assert run.verdict_reason is not None
    assert run.verdict_reason.startswith("Stopped by limit (max_cases)")
    stop = run.settings_snapshot["limit_stop"]
    assert stop["kind"] == "max_cases"

    with session_factory() as session:
        items = list_run_items(session, run_id)
    assert [item.state for item in items] == [
        RunItemState.COMPLETED.value,
        RunItemState.CANCELLED.value,
        RunItemState.CANCELLED.value,
    ]
    not_run = [item for item in items if item.state == RunItemState.CANCELLED.value]
    assert all(item.trace and item.trace["not_run"] is True for item in not_run)
    assert all(
        item.trace and item.trace["reason"] == "stopped by limit: max_cases" for item in not_run
    )


def test_max_duration_stops_a_slow_run_between_cases(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, settings_extra={"max_duration_seconds": 1})
    sender = FakeSender(answers=echo_answers(), delay=0.6)
    report = run_with_limits(run_id, session_factory, sender)

    assert report["status"] == "stopped_by_limit", report
    assert report["items_completed"] >= 1
    assert report["items_cancelled"] >= 1
    # It stopped because the clock ran out, not because a case failed.
    assert report["items_failed"] == 0
    run = load_run(session_factory, run_id)
    assert run.settings_snapshot["limit_stop"]["kind"] == "max_duration_seconds"
    assert len(sender.calls) == report["items_completed"]


def test_max_total_tokens_stops_a_run_that_reports_them(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, settings_extra={"max_total_tokens": 100})
    report = run_with_limits(run_id, session_factory, sender_factory=token_sender(60, 60))

    assert report["status"] == "stopped_by_limit", report
    # 120 tokens after the first case reached the cap of 100.
    assert report["items_completed"] == 1
    assert report["items_cancelled"] == 2
    run = load_run(session_factory, run_id)
    assert run.settings_snapshot["limit_stop"]["kind"] == "max_total_tokens"


def test_a_token_cap_without_reported_tokens_is_not_instrumented(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, settings_extra={"max_total_tokens": 1})
    report = run_with_limits(run_id, session_factory, sender_factory=token_sender(None, None))

    # Unreported tokens are never counted as 0, so the cap cannot fire.
    assert report["status"] == "completed", report
    assert report["items_completed"] == len(ROWS)
    run = load_run(session_factory, run_id)
    assert run.settings_snapshot["tokens_not_instrumented"] is True
    assert "limit_stop" not in run.settings_snapshot


def test_no_caps_still_runs_every_case(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner)
    report = run_with_limits(run_id, session_factory, FakeSender(answers=echo_answers()))

    assert report["status"] == "completed", report
    assert report["items_completed"] == len(ROWS)


@pytest.mark.parametrize("cap", [0, -5, "many", None])
def test_a_missing_or_invalid_cap_is_ignored(
    session_factory: sessionmaker[Session], owner: uuid.UUID, cap: object
) -> None:
    run_id = seed_run(session_factory, owner, settings_extra={"max_cases": cap})
    report = run_with_limits(run_id, session_factory, FakeSender(answers=echo_answers()))

    assert report["status"] == "completed", report
    assert report["items_completed"] == len(ROWS)


# ---- smoke runs (STEP 2) --------------------------------------------------


def test_a_smoke_run_is_a_rehearsal_not_a_verdict(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, settings_extra={"is_smoke": True})
    report = run_with_limits(run_id, session_factory, FakeSender(answers=echo_answers()))

    assert report["status"] == "completed", report
    assert report["verdict"] is None, "a smoke run must not carry a GO/REVIEW/NO-GO"
    run = load_run(session_factory, run_id)
    assert run.verdict is None
    assert run.is_partial is True
    assert run.verdict_reason is not None
    assert run.verdict_reason.startswith("Smoke run, not a verdict.")
    # The evidence is still there; only the verdict word is withheld.
    assert run.score is not None
    with session_factory() as session:
        assert get_metric_results(session, run_id)


def test_a_smoke_run_is_never_a_baseline(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    from app.services.regression import RegressionError, set_baseline

    run_id = seed_run(session_factory, owner, settings_extra={"is_smoke": True})
    run_with_limits(run_id, session_factory, FakeSender(answers=echo_answers()))

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        # The worker stored no comparison for it either.
        assert "regression" not in (run.settings_snapshot or {})
        with pytest.raises(RegressionError) as caught:
            set_baseline(session, run)
        assert "smoke" in caught.value.message.lower()


def test_a_smoke_request_defaults_to_five_cases() -> None:
    from app.schemas.runs import RunCreateRequest
    from app.services.run_service import build_snapshot

    snapshot = build_snapshot(
        RunCreateRequest(
            entry_point="http_endpoint",
            target="http://127.0.0.1:9099/ask",
            allow_private_targets=True,
            is_smoke=True,
        ),
        dataset_version_id=None,
        entry_point="http_endpoint",
    )
    assert snapshot["max_cases"] == 5
    assert snapshot["is_smoke"] is True


def test_an_explicit_case_cap_wins_over_the_smoke_default() -> None:
    from app.schemas.runs import RunCreateRequest
    from app.services.run_service import build_snapshot

    snapshot = build_snapshot(
        RunCreateRequest(
            entry_point="http_endpoint",
            target="http://127.0.0.1:9099/ask",
            allow_private_targets=True,
            is_smoke=True,
            max_cases=10,
        ),
        dataset_version_id=None,
        entry_point="http_endpoint",
    )
    assert snapshot["max_cases"] == 10
