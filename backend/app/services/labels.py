"""Human labels, the review queue and calibration (M7, spec 8.5).

The judge can be wrong, unavailable, or unsure. This module is the human side:

* a **label** is one reviewer's pass/fail verdict on one case, with an optional
  note (the edit-the-score case is represented by the same two labels, because
  calibration compares categories, not numbers);
* the **review queue** lists the cases a person should look at — the judge was
  unavailable, was unsure, or a reviewer's label disagrees with the judge; and
* **calibration** compares the judge's bucket with the human labels using the
  existing :func:`app.services.calibration.calibrate`, so the number a user sees
  is Cohen's kappa, not just raw agreement.

Labels are keyed by reviewer, so a second reviewer is a second opinion rather
than a correction; submitting again replaces that reviewer's own label.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HumanLabel, MetricResultRow, Run, RunItem
from app.services.calibration import (
    Calibration,
    calibrate,
    pass_fail,
)
from app.services.judge import (
    ANSWER_QUALITY,
    DEFAULT_ANSWER_QUALITY_THRESHOLD,
    DEFAULT_LOW_CONFIDENCE_THRESHOLD,
)

LABEL_PASS = "pass"
LABEL_FAIL = "fail"
JudgeLabel = Literal["pass", "fail", "unsure"]
# The judge's own reply may also be "unsure"; a human label is always pass/fail.
LABEL_UNSURE: JudgeLabel = "unsure"
LABELS: tuple[str, ...] = (LABEL_PASS, LABEL_FAIL)

REASON_UNAVAILABLE = "the judge could not score this case"
REASON_LOW_CONFIDENCE = "the judge was unsure about this case"
REASON_DISAGREES = "your label disagrees with the judge"
REASON_UNLABELLED = "no human label yet"


class LabelError(Exception):
    """A label request that cannot be honoured, with an HTTP status."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class ReviewCase:
    """One case in the review queue, with everything a reviewer needs to decide."""

    run_item_id: uuid.UUID
    run_id: uuid.UUID
    run_name: str
    row_index: int
    input_text: str
    output: str | None
    judge_score: float | None
    judge_bucket: str | None
    judge_confidence: float | None
    judge_reason: str | None
    reasons: list[str] = field(default_factory=list)
    label: str | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_item_id": str(self.run_item_id),
            "run_id": str(self.run_id),
            "run_name": self.run_name,
            "row_index": self.row_index,
            "input_text": self.input_text,
            "output": self.output,
            "judge_score": self.judge_score,
            "judge_bucket": self.judge_bucket,
            "judge_confidence": self.judge_confidence,
            "judge_reason": self.judge_reason,
            "reasons": self.reasons,
            "label": self.label,
            "note": self.note,
        }


def _judge_rows(session: Session) -> dict[uuid.UUID, MetricResultRow]:
    """The per-item judge rows, keyed by the item they graded."""
    rows = session.scalars(
        select(MetricResultRow).where(
            MetricResultRow.name == ANSWER_QUALITY,
            MetricResultRow.run_item_id.is_not(None),
        )
    )
    return {row.run_item_id: row for row in rows if row.run_item_id is not None}


def _bucket(row: MetricResultRow | None) -> str | None:
    """The judge's own pass/fail for a case, or None when it did not score it."""
    if row is None or not row.instrumented:
        return None
    return pass_fail(row.score, DEFAULT_ANSWER_QUALITY_THRESHOLD)


def _confidence(row: MetricResultRow | None) -> float | None:
    if row is None:
        return None
    details = row.details or {}
    value = details.get("confidence")
    return float(value) if isinstance(value, (int, float)) else None


def judge_rows_for_run(session: Session, run_id: uuid.UUID) -> dict[uuid.UUID, MetricResultRow]:
    """The judge's per-case rows of one run, keyed by the item they graded."""
    rows = session.scalars(
        select(MetricResultRow)
        .join(RunItem, RunItem.id == MetricResultRow.run_item_id)
        .where(
            MetricResultRow.name == ANSWER_QUALITY,
            RunItem.run_id == run_id,
        )
    )
    return {row.run_item_id: row for row in rows if row.run_item_id is not None}


def judge_case_label(row: MetricResultRow | None) -> JudgeLabel | None:
    """The judge's own label for one case, or None when it did not score it.

    This is the product's existing rule, per case and nothing more: a case the
    judge did not score has no label; a score it was not sure of is the
    ``unsure`` the review queue already names (:data:`REASON_LOW_CONFIDENCE`);
    a confident score is bucketed with :func:`pass_fail` at the answer-quality
    threshold.
    """
    if row is None or not row.instrumented:
        return None
    confidence = _confidence(row)
    if confidence is not None and confidence < DEFAULT_LOW_CONFIDENCE_THRESHOLD:
        return LABEL_UNSURE
    return cast(JudgeLabel, pass_fail(row.score, DEFAULT_ANSWER_QUALITY_THRESHOLD))


def review_queue(
    session: Session,
    reviewer_id: uuid.UUID,
    *,
    limit: int = 100,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> list[ReviewCase]:
    """Cases worth a human look, newest run first.

    Everything in the queue has a reason a reviewer can act on: the judge did
    not score it, the judge was unsure, or the reviewer's own label says the
    judge got it wrong. A confident, agreed case stays out of the queue.
    """
    judge_rows = _judge_rows(session)
    labels = {
        label.run_item_id: label
        for label in session.scalars(
            select(HumanLabel).where(HumanLabel.reviewer_id == reviewer_id)
        )
    }
    items = session.scalars(
        select(RunItem).join(Run, Run.id == RunItem.run_id).order_by(Run.created_at.desc())
    )
    cases: list[ReviewCase] = []
    for item in items:
        if item.id not in judge_rows:
            # Only judged cases are in scope: a run without a judge has no
            # provenance to calibrate, and no answer to disagree with.
            continue
        row = judge_rows[item.id]
        bucket = _bucket(row)
        confidence = _confidence(row)
        label = labels.get(item.id)
        reasons: list[str] = []
        if bucket is None:
            reasons.append(REASON_UNAVAILABLE)
        elif confidence is not None and confidence < low_confidence_threshold:
            reasons.append(REASON_LOW_CONFIDENCE)
        if label is not None and bucket is not None and label.label != bucket:
            reasons.append(REASON_DISAGREES)
        if not reasons:
            continue
        run = session.get(Run, item.run_id)
        cases.append(
            ReviewCase(
                run_item_id=item.id,
                run_id=item.run_id,
                run_name=run.name if run is not None else "Run",
                row_index=item.row_index,
                input_text=item.input_text,
                output=item.output,
                judge_score=row.score if row.instrumented else None,
                judge_bucket=bucket,
                judge_confidence=confidence,
                judge_reason=row.explanation,
                reasons=reasons,
                label=label.label if label is not None else None,
                note=label.note if label is not None else None,
            )
        )
        if len(cases) >= limit:
            break
    return cases


def submit_label(
    session: Session,
    item: RunItem,
    reviewer_id: uuid.UUID,
    label: str,
    note: str | None = None,
) -> HumanLabel:
    """Save one reviewer's label for one case, replacing their earlier one."""
    if label not in LABELS:
        raise LabelError(f"Label must be one of: {', '.join(LABELS)}.", status=422)
    existing = session.scalar(
        select(HumanLabel).where(
            HumanLabel.reviewer_id == reviewer_id,
            HumanLabel.run_item_id == item.id,
        )
    )
    if existing is None:
        existing = HumanLabel(run_id=item.run_id, run_item_id=item.id, reviewer_id=reviewer_id)
        session.add(existing)
    existing.label = label
    existing.note = note
    session.flush()
    return existing


def calibration(session: Session) -> Calibration:
    """Judge-versus-human agreement over every label in the project."""
    judge_rows = _judge_rows(session)
    judge_labels: list[str | None] = []
    human_labels: list[str | None] = []
    for label in session.scalars(select(HumanLabel)):
        row = judge_rows.get(label.run_item_id)
        bucket = _bucket(row)
        if bucket is None:
            # An unavailable judge has no opinion; counting it would score the
            # judge 0 for a case it never saw.
            continue
        judge_labels.append(bucket)
        human_labels.append(label.label)
    pairs = [
        (judge_label, human_label)
        for judge_label, human_label in zip(judge_labels, human_labels, strict=False)
        if judge_label is not None and human_label is not None
    ]
    return calibrate(pairs)
