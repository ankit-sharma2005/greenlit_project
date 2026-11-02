"""Baselines and regression against them (spec 8.5).

A *baseline* is one completed run per owner and dataset version. When a later run
on the same dataset version finishes, it is compared with the baseline twice:

* **per metric** — the delta of every metric measured in both runs, so a drop of
  0.83 in ``answer_match`` is visible instead of hidden by the weighted score;
* **per case** — a case that passed in the baseline and fails now is a
  regression, which is what pins the failure to the sentence the app answered
  badly.

The comparison is deliberately pure: :func:`compare` takes plain points and
returns plain data, so every status and every boundary is unit-testable without
a database. :func:`store_regression` is the one impure helper the worker calls
when a run completes; it writes the result into the run's settings snapshot, so
the verdict card and the report both read the same stored comparison.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Run, RunBaseline
from app.services.run_repository import get_metric_results, list_run_items

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_BLOCK = "BLOCK"

DEFAULT_METRIC_TOLERANCE = 0.05
DEFAULT_CASE_TOLERANCE = 2
MAX_TOLERANCE = 1.0

# The reason this feature exists: a drop that is nothing to worry about should
# not fail a release, and a drop that matters should not need a human to spot it
# in a table. `metric_tolerance` is the drop allowed before BLOCK; anything
# smaller than that but above zero is a WARN. `case_tolerance` is how many
# individual cases may regress before the comparison escalates to BLOCK.
NO_BASELINE_REASON = "No baseline is set for this dataset version, so there is nothing to compare."
SELF_BASELINE_REASON = "This run is the baseline, so it is not compared with itself."


class RegressionError(Exception):
    """A baseline request that cannot be honoured, with an HTTP status."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class MetricPoint:
    """One metric's outcome in one run."""

    name: str
    score: float
    passed: bool
    instrumented: bool = True
    hard_gate: bool = False


@dataclass(frozen=True)
class CasePoint:
    """One case's outcome in one run; ``passed`` means it answered and passed."""

    row_index: int
    input: str
    passed: bool


@dataclass(frozen=True)
class MetricDelta:
    """A metric's before/after, with the delta the comparison rules read."""

    name: str
    baseline: float | None
    current: float | None
    delta: float | None
    passed_before: bool
    passed_now: bool
    hard_gate: bool

    @property
    def regressed(self) -> bool:
        return self.delta is not None and self.delta < 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "baseline": self.baseline,
            "current": self.current,
            "delta": self.delta,
            "passed_before": self.passed_before,
            "passed_now": self.passed_now,
            "hard_gate": self.hard_gate,
            "regressed": self.regressed,
        }


@dataclass(frozen=True)
class Regression:
    """The stored comparison: a status, why, and the evidence behind it."""

    status: str
    reason: str
    metric_deltas: list[MetricDelta] = field(default_factory=list)
    regressed_cases: list[CasePoint] = field(default_factory=list)
    metric_tolerance: float = DEFAULT_METRIC_TOLERANCE
    case_tolerance: int = DEFAULT_CASE_TOLERANCE
    baseline_run_id: uuid.UUID | None = None
    baseline_run_name: str | None = None

    @property
    def regressed_metrics(self) -> list[str]:
        return [delta.name for delta in self.metric_deltas if delta.regressed]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "baseline_run_id": str(self.baseline_run_id) if self.baseline_run_id else None,
            "baseline_run_name": self.baseline_run_name,
            "metric_tolerance": self.metric_tolerance,
            "case_tolerance": self.case_tolerance,
            "metric_deltas": [delta.as_dict() for delta in self.metric_deltas],
            "regressed_metrics": self.regressed_metrics,
            "regressed_cases": [
                {"row_index": case.row_index, "input": case.input} for case in self.regressed_cases
            ],
        }


def _percent(value: float) -> str:
    return f"{value:.2f}"


def compare(
    baseline_metrics: Sequence[MetricPoint],
    current_metrics: Sequence[MetricPoint],
    baseline_cases: Sequence[CasePoint],
    current_cases: Sequence[CasePoint],
    *,
    metric_tolerance: float = DEFAULT_METRIC_TOLERANCE,
    case_tolerance: int = DEFAULT_CASE_TOLERANCE,
) -> Regression:
    """Compare one run with its baseline; pure, so every rule is testable.

    Only metrics measured in *both* runs are compared: a metric that became not
    instrumented cannot be said to have dropped, and saying so would be worse
    than staying quiet. A BLOCK needs a hard gate that stopped passing, a metric
    drop beyond the tolerance, or more regressed cases than the tolerance
    allows; a smaller drop or a few cases is a WARN; nothing is a PASS.
    """
    current_by_name = {point.name: point for point in current_metrics}
    deltas: list[MetricDelta] = []
    for baseline in baseline_metrics:
        current = current_by_name.get(baseline.name)
        if (
            current is None
            or not baseline.instrumented
            or not current.instrumented
            or baseline.score is None
            or current.score is None
        ):
            continue
        deltas.append(
            MetricDelta(
                name=baseline.name,
                baseline=baseline.score,
                current=current.score,
                delta=round(current.score - baseline.score, 4),
                passed_before=baseline.passed,
                passed_now=current.passed,
                hard_gate=baseline.hard_gate or current.hard_gate,
            )
        )

    baseline_by_row = {case.row_index: case for case in baseline_cases}
    regressed_cases = [
        case
        for case in current_cases
        if not case.passed
        and (before := baseline_by_row.get(case.row_index)) is not None
        and before.passed
    ]

    hard_gate_failures = [
        delta.name
        for delta in deltas
        if delta.hard_gate and delta.passed_before and not delta.passed_now
    ]
    beyond = [
        delta for delta in deltas if delta.delta is not None and delta.delta < -metric_tolerance
    ]
    within = [
        delta
        for delta in deltas
        if delta.delta is not None and -metric_tolerance <= delta.delta < 0
    ]

    if hard_gate_failures or beyond or len(regressed_cases) > case_tolerance:
        status = STATUS_BLOCK
    elif within or regressed_cases:
        status = STATUS_WARN
    else:
        status = STATUS_PASS

    return Regression(
        status=status,
        reason=_reason(
            status=status,
            hard_gate_failures=hard_gate_failures,
            beyond=beyond,
            within=within,
            regressed_cases=regressed_cases,
            metric_tolerance=metric_tolerance,
            case_tolerance=case_tolerance,
        ),
        metric_deltas=deltas,
        regressed_cases=regressed_cases,
        metric_tolerance=metric_tolerance,
        case_tolerance=case_tolerance,
    )


def _reason(
    *,
    status: str,
    hard_gate_failures: list[str],
    beyond: list[MetricDelta],
    within: list[MetricDelta],
    regressed_cases: list[CasePoint],
    metric_tolerance: float,
    case_tolerance: int,
) -> str:
    """A sentence a person can act on, naming what moved."""
    parts: list[str] = []
    if hard_gate_failures:
        names = ", ".join(sorted(hard_gate_failures))
        parts.append(f"hard gate {names} stopped passing")
    if beyond:
        named = "; ".join(
            f"{delta.name} dropped {_percent(abs(delta.delta or 0.0))} "
            f"({_percent(delta.baseline or 0.0)} → {_percent(delta.current or 0.0)})"
            for delta in sorted(beyond, key=lambda item: item.delta or 0.0)
        )
        parts.append(f"{named}, beyond the {_percent(metric_tolerance)} tolerance")
    if within:
        named = ", ".join(f"{delta.name} {_percent(delta.delta or 0.0)}" for delta in within)
        parts.append(f"smaller drops within tolerance: {named}")
    if regressed_cases:
        count = len(regressed_cases)
        parts.append(
            f"{count} case{'s' if count != 1 else ''} passed before and "
            f"{'fail' if count != 1 else 'fails'} now"
        )
        if count > case_tolerance:
            parts.append(f"more than the {case_tolerance} allowed")
    if status == STATUS_PASS:
        return "Nothing regressed against the baseline: every comparable metric held."
    if status == STATUS_WARN:
        return "Change worth a look against the baseline: " + "; ".join(parts) + "."
    return "Regression against the baseline: " + "; ".join(parts) + "."


# ---- persistence -----------------------------------------------------------


def _points(session: Session, run: Run) -> tuple[list[MetricPoint], list[CasePoint]]:
    """A run's metrics and cases as comparison points."""
    metrics = [
        MetricPoint(
            name=row.name,
            score=row.score,
            passed=bool(row.passed),
            instrumented=bool(row.instrumented),
            hard_gate=bool(row.hard_gate),
        )
        for row in get_metric_results(session, run.id)
        if row.run_item_id is None
    ]
    items = list_run_items(session, run.id)
    per_item: dict[uuid.UUID, bool] = {}
    for row in get_metric_results(session, run.id):
        if row.run_item_id is None or not row.instrumented:
            continue
        # One failed per-item metric makes the case fail; judge rows are the
        # usual source, and an unavailable judge says nothing either way.
        per_item[row.run_item_id] = per_item.get(row.run_item_id, True) and bool(row.passed)
    cases = [
        CasePoint(
            row_index=item.row_index,
            input=item.input_text,
            passed=(
                item.state == "completed"
                and item.output is not None
                and per_item.get(item.id, True)
            ),
        )
        for item in items
    ]
    return metrics, cases


def active_baseline(
    session: Session, owner_id: uuid.UUID, dataset_version_id: uuid.UUID | None
) -> RunBaseline | None:
    """The active baseline for one dataset version, if there is one."""
    if dataset_version_id is None:
        return None
    return session.scalar(
        select(RunBaseline).where(
            RunBaseline.owner_id == owner_id,
            RunBaseline.dataset_version_id == dataset_version_id,
            RunBaseline.is_active.is_(True),
        )
    )


def set_baseline(
    session: Session,
    run: Run,
    *,
    metric_tolerance: float = DEFAULT_METRIC_TOLERANCE,
    case_tolerance: int = DEFAULT_CASE_TOLERANCE,
) -> RunBaseline:
    """Make ``run`` the baseline for its dataset version, replacing any earlier one."""
    if run.state != "completed":
        raise RegressionError("Only a completed run can be a baseline.", status=409)
    if (run.settings_snapshot or {}).get("is_smoke"):
        raise RegressionError(
            "A smoke run is a rehearsal, not a baseline. Run the full test and set that "
            "as the baseline.",
            status=409,
        )
    if run.dataset_version_id is None:
        raise RegressionError(
            "This run has no dataset version, so it cannot be compared with later runs.",
            status=409,
        )
    if metric_tolerance < 0 or metric_tolerance > MAX_TOLERANCE:
        raise RegressionError("The metric tolerance must be between 0 and 1.", status=422)
    if case_tolerance < 0:
        raise RegressionError("The case tolerance cannot be negative.", status=422)

    baseline = session.scalar(
        select(RunBaseline).where(
            RunBaseline.owner_id == run.owner_id,
            RunBaseline.dataset_version_id == run.dataset_version_id,
        )
    )
    if baseline is None:
        baseline = RunBaseline(owner_id=run.owner_id, dataset_version_id=run.dataset_version_id)
        session.add(baseline)
    baseline.run_id = run.id
    baseline.dataset_id = run.dataset_id
    baseline.metric_tolerance = metric_tolerance
    baseline.case_tolerance = case_tolerance
    baseline.is_active = True
    session.flush()
    return baseline


def clear_baseline(session: Session, run: Run) -> bool:
    """Deactivate the baseline for this run's dataset version; returns whether one existed."""
    baseline = session.scalar(
        select(RunBaseline).where(
            RunBaseline.owner_id == run.owner_id,
            RunBaseline.dataset_version_id == run.dataset_version_id,
            RunBaseline.is_active.is_(True),
        )
    )
    if baseline is None:
        return False
    baseline.is_active = False
    session.flush()
    return True


def baseline_for_run(session: Session, run: Run) -> RunBaseline | None:
    return active_baseline(session, run.owner_id, run.dataset_version_id)


def regression_for(session: Session, run: Run) -> Regression | None:
    """Compare ``run`` with the active baseline, or None when there is none."""
    baseline = baseline_for_run(session, run)
    if baseline is None or baseline.run_id == run.id:
        return None
    baseline_run = session.get(Run, baseline.run_id)
    if baseline_run is None:
        return None
    baseline_metrics, baseline_cases = _points(session, baseline_run)
    current_metrics, current_cases = _points(session, run)
    result = compare(
        baseline_metrics,
        current_metrics,
        baseline_cases,
        current_cases,
        metric_tolerance=baseline.metric_tolerance,
        case_tolerance=baseline.case_tolerance,
    )
    return Regression(
        status=result.status,
        reason=result.reason,
        metric_deltas=result.metric_deltas,
        regressed_cases=result.regressed_cases,
        metric_tolerance=result.metric_tolerance,
        case_tolerance=result.case_tolerance,
        baseline_run_id=baseline_run.id,
        baseline_run_name=baseline_run.name,
    )


def store_regression(session: Session, run: Run) -> dict[str, Any] | None:
    """Store the comparison on the finished run; called by the worker.

    Replacing the dict (rather than mutating it) is what makes SQLAlchemy notice
    a JSON column changed, and doing it in the worker means the verdict card and
    the report read the same numbers as the moment the run finished.
    """
    if run.state != "completed":
        return None
    result = regression_for(session, run)
    if result is None:
        return None
    payload = result.as_dict()
    snapshot = dict(run.settings_snapshot or {})
    snapshot["regression"] = payload
    run.settings_snapshot = snapshot
    session.flush()
    return payload
