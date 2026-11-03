"""M9: interrupted runs — the heartbeat sweep (quirk 13).

Every test uses an explicit ``now`` (a fake clock) instead of sleeping, so the
window is exercised exactly at its boundary. No worker, Redis or queue is
involved: the sweep only reads and writes rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import Run, RunState, User, utcnow
from app.services.run_repository import create_run, create_run_item, list_run_items, update_run
from app.services.run_sweep import (
    DEFAULT_STALE_MINUTES,
    sweep_interrupted_runs,
    sweep_with_settings,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def owner(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        user = User(
            email=f"sweep-{uuid.uuid4().hex[:8]}@example.com",
            name="Sweep Owner",
            password_hash="x",
            role="admin",
        )
        session.add(user)
        session.commit()
        return user.id


def _seed(
    session_factory: sessionmaker[Session],
    owner_id: uuid.UUID,
    *,
    state: str = RunState.RUNNING.value,
    heartbeat_at: datetime | None = None,
    started_at: datetime | None = NOW - timedelta(minutes=40),
    item_states: tuple[str, ...] = ("completed", "running", "queued"),
) -> uuid.UUID:
    with session_factory() as session:
        run = create_run(session, owner_id=owner_id, name="Sweep run", settings_snapshot={})
        update_run(
            session,
            run,
            state=state,
            started_at=started_at,
            last_heartbeat_at=heartbeat_at,
        )
        for index, item_state in enumerate(item_states):
            create_run_item(
                session,
                run,
                row_index=index,
                input_text=f"question {index}",
                state=item_state,
            )
        session.commit()
        return run.id


def test_a_run_whose_worker_went_quiet_is_interrupted_and_keeps_answers(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """The stale run stops looking hung: answers kept, the rest marked not run."""
    run_id = _seed(session_factory, owner, heartbeat_at=NOW - timedelta(minutes=11))

    with session_factory() as session:
        marked = sweep_interrupted_runs(session, now=NOW, stale_after_minutes=10)

    assert [run.id for run in marked] == [run_id]
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == RunState.INTERRUPTED.value
        assert run.is_partial is True
        assert run.completed_at is not None
        assert run.verdict_reason is not None
        assert "interrupted" in run.verdict_reason
        assert "1 of 3 cases finished" in run.verdict_reason
        assert "2 were not run" in run.verdict_reason
        items = list_run_items(session, run_id)
        assert [item.state for item in items] == ["completed", "cancelled", "cancelled"]
        assert items[0].trace is None  # the answered case is untouched
        assert items[1].trace == {
            "not_run": True,
            "reason": "interrupted: the worker stopped responding",
        }


def test_a_run_with_a_recent_heartbeat_is_left_alone(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """A slow but alive worker is not mistaken for a dead one."""
    run_id = _seed(session_factory, owner, heartbeat_at=NOW - timedelta(minutes=9))

    with session_factory() as session:
        assert sweep_interrupted_runs(session, now=NOW, stale_after_minutes=10) == []

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == RunState.RUNNING.value
        assert [item.state for item in list_run_items(session, run_id)] == [
            "completed",
            "running",
            "queued",
        ]


def test_a_run_from_before_the_migration_falls_back_to_its_start_time(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """A row written before the column existed (NULL heartbeat) still loads."""
    stale_id = _seed(
        session_factory,
        owner,
        heartbeat_at=None,
        started_at=NOW - timedelta(minutes=30),
    )
    fresh_id = _seed(
        session_factory,
        owner,
        heartbeat_at=None,
        started_at=NOW - timedelta(minutes=2),
    )

    with session_factory() as session:
        marked = sweep_interrupted_runs(session, now=NOW, stale_after_minutes=10)

    assert [run.id for run in marked] == [stale_id]
    with session_factory() as session:
        fresh = session.get(Run, fresh_id)
        assert fresh is not None
        assert fresh.state == RunState.RUNNING.value


def test_cancelling_runs_are_swept_and_finished_runs_are_never_touched(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    stalled_cancel = _seed(session_factory, owner, state=RunState.CANCELLING.value)
    done_id = _seed(session_factory, owner, state=RunState.COMPLETED.value)
    queued_id = _seed(session_factory, owner, state=RunState.QUEUED.value)

    with session_factory() as session:
        marked = sweep_interrupted_runs(session, now=NOW, stale_after_minutes=10)

    assert [run.id for run in marked] == [stalled_cancel]
    with session_factory() as session:
        done = session.get(Run, done_id)
        parked = session.get(Run, queued_id)
        assert done is not None and done.state == RunState.COMPLETED.value
        assert parked is not None and parked.state == RunState.QUEUED.value


def test_a_second_sweep_does_not_resume_or_recount_the_run(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """There is no automatic resume: the next sweep returns nothing."""
    run_id = _seed(session_factory, owner, heartbeat_at=NOW - timedelta(minutes=20))

    with session_factory() as session:
        first = sweep_interrupted_runs(session, now=NOW, stale_after_minutes=10)
    with session_factory() as session:
        second = sweep_interrupted_runs(
            session, now=NOW + timedelta(hours=1), stale_after_minutes=10
        )

    assert first and not second
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == RunState.INTERRUPTED.value
        assert run.completed_at is not None
        assert [item.state for item in list_run_items(session, run_id)] == [
            "completed",
            "cancelled",
            "cancelled",
        ]


def test_the_worker_entry_point_uses_the_configured_window(
    session_factory: sessionmaker[Session], owner: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sweep_with_settings`` reads ``interrupted_after_minutes`` and counts."""
    # No ``now`` here: this entry point uses the real clock, so seed around it.
    real_now = utcnow()
    _seed(
        session_factory,
        owner,
        heartbeat_at=real_now - timedelta(minutes=3),
        started_at=real_now - timedelta(minutes=30),
    )
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(interrupted_after_minutes=2),
    )

    result = sweep_with_settings(session_factory)

    assert result["interrupted"] == 1
    assert len(result["run_ids"]) == 1


def test_the_default_window_is_ten_minutes() -> None:
    assert DEFAULT_STALE_MINUTES == 10
