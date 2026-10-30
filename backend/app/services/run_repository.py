"""Create, read and update runs, run items and metric results (M6a).

Repository functions take an open session and only flush: the caller owns the
transaction, matching the dataset and audit services (DECISIONS D4.2). Run and
item states are validated against the enums in :mod:`app.models`; the legality
of a *transition* (queued -> running -> completed) is the worker's business in
M6b, not the repository's.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MetricResultRow, Run, RunItem, RunItemState, RunState


class RepositoryError(ValueError):
    """Invalid repository call, for example an unknown field or state."""


_RUN_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "state",
        "verdict",
        "score",
        "verdict_reason",
        "is_partial",
        "settings_snapshot",
        "criteria_profile",
        "operations",
        "started_at",
        "completed_at",
    }
)

_RUN_ITEM_FIELDS: frozenset[str] = frozenset(
    {
        "state",
        "output",
        "retrieved_context",
        "trace",
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "error",
    }
)

_RUN_STATES: tuple[str, ...] = tuple(state.value for state in RunState)
_RUN_ITEM_STATES: tuple[str, ...] = tuple(state.value for state in RunItemState)


def create_run(
    session: Session,
    *,
    owner_id: uuid.UUID,
    name: str,
    settings_snapshot: Mapping[str, Any] | None = None,
    dataset_id: uuid.UUID | None = None,
    dataset_version_id: uuid.UUID | None = None,
    criteria_profile: str = "plain_chatbot",
) -> Run:
    """Create a run in the ``queued`` state with its settings snapshot."""
    run = Run(
        owner_id=owner_id,
        name=name,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        criteria_profile=criteria_profile,
        settings_snapshot=dict(settings_snapshot or {}),
        state=RunState.QUEUED.value,
    )
    session.add(run)
    session.flush()
    return run


def get_run(
    session: Session, run_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> Run | None:
    """Fetch one run; with ``owner_id`` a foreign run is reported as missing."""
    run = session.get(Run, run_id)
    if run is None:
        return None
    if owner_id is not None and run.owner_id != owner_id:
        return None
    return run


def list_runs(
    session: Session, owner_id: uuid.UUID, *, limit: int = 20, offset: int = 0
) -> list[Run]:
    """Newest first, paginated, only the owner's runs."""
    rows = (
        session.execute(
            select(Run)
            .where(Run.owner_id == owner_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return list(rows)


def update_run(session: Session, run: Run, **changes: object) -> Run:
    """Apply whitelisted field changes; ``state`` must be a known run state."""
    _apply(run, changes, _RUN_FIELDS, _RUN_STATES)
    session.add(run)
    session.flush()
    return run


def create_run_item(
    session: Session,
    run: Run,
    *,
    row_index: int,
    input_text: str = "",
    state: RunItemState | str = RunItemState.QUEUED,
) -> RunItem:
    """Create one queued item; ``row_index`` is unique per run."""
    item = RunItem(
        run=run,
        row_index=row_index,
        input_text=input_text,
        state=_coerce_state(state, _RUN_ITEM_STATES),
    )
    session.add(item)
    session.flush()
    return item


def list_run_items(session: Session, run_id: uuid.UUID) -> list[RunItem]:
    """All items of a run in row order."""
    rows = (
        session.execute(select(RunItem).where(RunItem.run_id == run_id).order_by(RunItem.row_index))
        .scalars()
        .all()
    )
    return list(rows)


def update_run_item(session: Session, item: RunItem, **changes: object) -> RunItem:
    """Apply whitelisted field changes to one item."""
    _apply(item, changes, _RUN_ITEM_FIELDS, _RUN_ITEM_STATES)
    session.add(item)
    session.flush()
    return item


def add_metric_result(
    session: Session,
    run: Run,
    *,
    name: str,
    score: float,
    passed: bool,
    explanation: str = "",
    instrumented: bool = True,
    run_item_id: uuid.UUID | None = None,
    weight: float = 0.0,
    threshold: float = 0.0,
    hard_gate: bool = False,
    details: Mapping[str, Any] | None = None,
) -> MetricResultRow:
    """Store one metric score for the run (``run_item_id`` None) or an item."""
    result = MetricResultRow(
        run_id=run.id,
        run_item_id=run_item_id,
        name=name,
        score=score,
        passed=passed,
        explanation=explanation,
        instrumented=instrumented,
        weight=weight,
        threshold=threshold,
        hard_gate=hard_gate,
        details=dict(details) if details is not None else None,
    )
    session.add(result)
    session.flush()
    return result


def get_metric_results(session: Session, run_id: uuid.UUID) -> list[MetricResultRow]:
    """Every stored metric result of a run, oldest first."""
    rows = (
        session.execute(
            select(MetricResultRow)
            .where(MetricResultRow.run_id == run_id)
            .order_by(MetricResultRow.created_at)
        )
        .scalars()
        .all()
    )
    return list(rows)


def _apply(
    target: object,
    changes: Mapping[str, object],
    fields: frozenset[str],
    states: tuple[str, ...],
) -> None:
    unknown = set(changes) - fields
    if unknown:
        raise RepositoryError(f"unknown fields: {', '.join(sorted(unknown))}")
    for field, value in changes.items():
        setattr(target, field, _coerce_state(value, states) if field == "state" else value)


def _coerce_state(value: object, allowed: tuple[str, ...]) -> str:
    plain = value.value if isinstance(value, enum.Enum) else value
    text = str(plain)
    if text not in allowed:
        raise RepositoryError(f"unknown state: {text!r} (expected one of {', '.join(allowed)})")
    return text
