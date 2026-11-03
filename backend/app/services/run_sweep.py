"""Interrupted runs: what to do with a run whose worker stopped (quirk 13).

A worker that dies mid-run leaves the run in ``running`` forever, which reads as
a hung test. The sweep uses the heartbeat the worker writes at every case
boundary: a run with no heartbeat for more than N minutes is marked
``interrupted``, its unanswered cases become "not run" with that reason, and the
answers that already finished are kept. Nothing is resumed here — the executor
loads a run's whole case list, so there is no supported subset to re-send.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Run, RunItem, RunItemState, RunState, utcnow
from app.services.run_repository import update_run, update_run_item

DEFAULT_STALE_MINUTES = 10


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat those as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def sweep_interrupted_runs(
    session: Session,
    *,
    now: datetime | None = None,
    stale_after_minutes: int = DEFAULT_STALE_MINUTES,
) -> list[Run]:
    """Mark every run whose worker went quiet; return the ones just marked.

    ``now`` is a parameter so a test can use a fake clock without sleeping.
    """
    moment = _aware(now) if now is not None else utcnow()
    cutoff = moment - timedelta(minutes=stale_after_minutes)
    candidates = (
        session.scalars(
            select(Run).where(Run.state.in_((RunState.RUNNING.value, RunState.CANCELLING.value)))
        )
        .unique()
        .all()
    )
    interrupted: list[Run] = []
    for run in candidates:
        beat = run.last_heartbeat_at or run.started_at or run.updated_at
        if _aware(beat) > cutoff:
            continue
        items = session.scalars(select(RunItem).where(RunItem.run_id == run.id)).unique().all()
        not_run = 0
        for item in items:
            if item.state in (RunItemState.QUEUED.value, RunItemState.RUNNING.value):
                not_run += 1
                update_run_item(
                    session,
                    item,
                    state=RunItemState.CANCELLED,
                    trace={
                        "not_run": True,
                        "reason": "interrupted: the worker stopped responding",
                    },
                )
        kept = sum(
            1
            for item in items
            if item.state in (RunItemState.COMPLETED.value, RunItemState.FAILED.value)
        )
        update_run(
            session,
            run,
            state=RunState.INTERRUPTED,
            is_partial=True,
            completed_at=moment,
            verdict_reason=(
                f"This run was interrupted: the worker stopped reporting for more than "
                f"{stale_after_minutes} minutes. {kept} of {len(items)} cases finished and are "
                f"kept; {not_run} were not run. Run the test again to cover them."
            ),
        )
        interrupted.append(run)
    if interrupted:
        session.commit()
    return interrupted


def sweep_with_settings(session_factory: Any) -> dict[str, Any]:
    """Run the sweep with the configured window; safe to call from a worker."""
    from app.config import get_settings

    with session_factory() as session:
        runs = sweep_interrupted_runs(
            session,
            stale_after_minutes=get_settings().interrupted_after_minutes,
        )
    return {"interrupted": len(runs), "run_ids": [str(run.id) for run in runs]}
