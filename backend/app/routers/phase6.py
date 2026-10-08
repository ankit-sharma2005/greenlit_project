from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_roles
from app.models import (
    AuditLog,
    DatasetItem,
    EvalRun,
    EvalRunItem,
    Project,
    ProjectBaseline,
    User,
)
from app.phase4_schemas import MetricScoreOut
from app.phase6_schemas import (
    BaselineOut,
    BaselineRequest,
    RegressionReportOut,
    RunComparisonOut,
)
from app.services.comparison import (
    ComparisonItem,
    compare_runs,
    regression_report,
)

router = APIRouter(tags=["comparison", "regression"])

Member = Annotated[
    User,
    Depends(require_roles("owner", "admin", "engineer", "reviewer", "viewer")),
]
Admin = Annotated[User, Depends(require_roles("owner", "admin"))]


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/baseline",
    response_model=BaselineOut | None,
)
async def get_project_baseline(
    workspace_id: UUID,
    project_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectBaseline | None:
    await _get_project(db, workspace_id, project_id)
    return await db.get(ProjectBaseline, project_id)


@router.put(
    "/workspaces/{workspace_id}/projects/{project_id}/baseline",
    response_model=BaselineOut,
)
async def promote_baseline(
    workspace_id: UUID,
    project_id: UUID,
    payload: BaselineRequest,
    user: Admin,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectBaseline:
    await _get_project(db, workspace_id, project_id)
    run = await _get_run(db, workspace_id, project_id, payload.run_id)
    if run.status != "completed":
        raise HTTPException(
            status_code=409, detail="Only completed runs can be approved as baseline"
        )
    baseline = await db.get(ProjectBaseline, project_id)
    old_run_id = str(baseline.run_id) if baseline is not None else None
    if baseline is None:
        baseline = ProjectBaseline(
            project_id=project_id,
            workspace_id=workspace_id,
            run_id=run.id,
            approved_by=user.id,
            reason=payload.reason.strip(),
        )
        db.add(baseline)
    else:
        baseline.run_id = run.id
        baseline.approved_by = user.id
        baseline.reason = payload.reason.strip()
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="project_baseline_promoted",
            details={
                "project_id": str(project_id),
                "previous_run_id": old_run_id,
                "run_id": str(run.id),
                "reason": payload.reason.strip(),
            },
        )
    )
    await db.commit()
    await db.refresh(baseline)
    return baseline


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/compare/"
    "{baseline_run_id}/{candidate_run_id}",
    response_model=RunComparisonOut,
)
async def compare_evaluation_runs(
    workspace_id: UUID,
    project_id: UUID,
    baseline_run_id: UUID,
    candidate_run_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RunComparisonOut:
    baseline = await _get_run(db, workspace_id, project_id, baseline_run_id)
    candidate = await _get_run(db, workspace_id, project_id, candidate_run_id)
    _validate_comparable_runs(baseline, candidate)
    baseline_items = await _comparison_items(db, baseline.id)
    candidate_items = await _comparison_items(db, candidate.id)
    return compare_runs(
        baseline.id,
        candidate.id,
        baseline_items,
        candidate_items,
    )


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/regression/{candidate_run_id}",
    response_model=RegressionReportOut,
)
async def check_regression(
    workspace_id: UUID,
    project_id: UUID,
    candidate_run_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RegressionReportOut:
    baseline_record = await db.get(ProjectBaseline, project_id)
    if baseline_record is None or baseline_record.workspace_id != workspace_id:
        raise HTTPException(status_code=409, detail="Project has no approved baseline")
    baseline = await _get_run(db, workspace_id, project_id, baseline_record.run_id)
    candidate = await _get_run(db, workspace_id, project_id, candidate_run_id)
    _validate_comparable_runs(baseline, candidate)
    baseline_items = await _comparison_items(db, baseline.id)
    candidate_items = await _comparison_items(db, candidate.id)
    comparison = compare_runs(
        baseline.id,
        candidate.id,
        baseline_items,
        candidate_items,
    )
    return regression_report(comparison, baseline_items, candidate_items)


async def _get_project(
    db: AsyncSession, workspace_id: UUID, project_id: UUID
) -> Project:
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_run(
    db: AsyncSession, workspace_id: UUID, project_id: UUID, run_id: UUID
) -> EvalRun:
    run = await db.scalar(
        select(EvalRun).where(
            EvalRun.id == run_id,
            EvalRun.workspace_id == workspace_id,
            EvalRun.project_id == project_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return run


def _validate_comparable_runs(baseline: EvalRun, candidate: EvalRun) -> None:
    if baseline.status != "completed" or candidate.status != "completed":
        raise HTTPException(
            status_code=409, detail="Only completed runs can be compared"
        )
    if (
        baseline.dataset_version_id != candidate.dataset_version_id
        or baseline.split != candidate.split
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Runs must use the same dataset version and split for paired comparison"
            ),
        )


async def _comparison_items(db: AsyncSession, run_id: UUID) -> list[ComparisonItem]:
    rows = await db.execute(
        select(EvalRunItem, DatasetItem)
        .join(DatasetItem, DatasetItem.id == EvalRunItem.dataset_item_id)
        .where(EvalRunItem.run_id == run_id)
        .order_by(DatasetItem.position)
    )
    return [
        ComparisonItem(
            id=dataset_item.id,
            position=dataset_item.position,
            regression_critical=dataset_item.regression_critical,
            status=run_item.status,
            scores=[MetricScoreOut.model_validate(score) for score in run_item.scores],
        )
        for run_item, dataset_item in rows
    ]
