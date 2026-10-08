from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import require_roles
from app.models import User
from app.phase8_schemas import (
    BlindComparisonOut,
    CalibrationSummaryOut,
    FinalReportOut,
    OverrideDecisionOut,
    ReviewQueueEntry,
)
from app.services.human_review import (
    ReviewItem,
    blind_ab_compare,
    calibration_summary,
    final_report_rescore,
    queue_review_items,
    validate_override,
)

router = APIRouter(tags=["human-review", "calibration"])

Reviewer = Annotated[
    User,
    Depends(require_roles("owner", "admin", "engineer", "reviewer")),
]


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/review-queue",
    response_model=list[ReviewQueueEntry],
)
async def post_review_queue(
    workspace_id: UUID,
    project_id: UUID,
    payload: list[ReviewItem],
    _: Reviewer,
) -> list[ReviewQueueEntry]:
    return queue_review_items(payload)


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/review-calibration",
    response_model=CalibrationSummaryOut,
)
async def post_review_calibration(
    workspace_id: UUID,
    project_id: UUID,
    payload: dict[str, list[float | int]],
    _: Reviewer,
) -> CalibrationSummaryOut:
    actual = payload.get("actual", [])
    predicted = payload.get("predicted", [])
    return calibration_summary(actual, predicted)


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/review-blind-compare",
    response_model=BlindComparisonOut,
)
async def post_blind_compare(
    workspace_id: UUID,
    project_id: UUID,
    payload: dict[str, Any],
    _: Reviewer,
) -> BlindComparisonOut:
    return blind_ab_compare(
        float(payload.get("left_score", 0.0)),
        float(payload.get("right_score", 0.0)),
        left_label=str(payload.get("left_label", "Variant A")),
        right_label=str(payload.get("right_label", "Variant B")),
    )


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/review-override",
    response_model=OverrideDecisionOut,
)
async def post_review_override(
    workspace_id: UUID,
    project_id: UUID,
    payload: dict[str, Any],
    _: Reviewer,
) -> OverrideDecisionOut:
    return validate_override(
        str(payload.get("justification", "")),
        require_justification=bool(payload.get("require_justification", True)),
        audit_logged=bool(payload.get("audit_logged", False)),
    )


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/final-report",
    response_model=FinalReportOut,
)
async def post_final_report(
    workspace_id: UUID,
    project_id: UUID,
    payload: dict[str, Any],
    _: Reviewer,
) -> FinalReportOut:
    traces = payload.get("stored_traces", [])
    return final_report_rescore(
        [dict(item) for item in traces],
        threshold=float(payload.get("threshold", 0.75)),
    )
