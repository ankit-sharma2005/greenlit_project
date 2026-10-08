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
    ProjectVerdictCriteria,
    User,
)
from app.phase5_schemas import (
    DEFAULT_VERDICT_CRITERIA,
    RunReportItem,
    RunReportOut,
    VerdictCriteria,
)
from app.services.verdicts import (
    VerdictItem,
    criteria_snapshot,
    evaluate_verdict,
    readiness_issues_for_trace,
)

router = APIRouter(tags=["verdicts", "results"])

Member = Annotated[
    User,
    Depends(require_roles("owner", "admin", "engineer", "reviewer", "viewer")),
]
Engineer = Annotated[User, Depends(require_roles("owner", "admin", "engineer"))]


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/verdict-criteria",
    response_model=VerdictCriteria,
)
async def get_verdict_criteria(
    workspace_id: UUID,
    project_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VerdictCriteria:
    await _get_project(db, workspace_id, project_id)
    saved = await db.get(ProjectVerdictCriteria, project_id)
    return criteria_snapshot(saved.criteria if saved else DEFAULT_VERDICT_CRITERIA)


@router.put(
    "/workspaces/{workspace_id}/projects/{project_id}/verdict-criteria",
    response_model=VerdictCriteria,
)
async def save_verdict_criteria(
    workspace_id: UUID,
    project_id: UUID,
    payload: VerdictCriteria,
    user: Engineer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VerdictCriteria:
    project = await _get_project(db, workspace_id, project_id)
    saved = await db.get(ProjectVerdictCriteria, project_id)
    serialized = payload.model_dump(mode="json")
    if saved is None:
        saved = ProjectVerdictCriteria(project_id=project_id, criteria=serialized)
        db.add(saved)
    else:
        saved.criteria = serialized
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="verdict_criteria_updated",
            details={"project_id": str(project.id), "criteria": serialized},
        )
    )
    await db.commit()
    return payload


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/runs/{run_id}/report",
    response_model=RunReportOut,
)
async def get_run_report(
    workspace_id: UUID,
    project_id: UUID,
    run_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RunReportOut:
    run = await db.scalar(
        select(EvalRun).where(
            EvalRun.id == run_id,
            EvalRun.project_id == project_id,
            EvalRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")

    rows = list(
        await db.execute(
            select(EvalRunItem, DatasetItem)
            .join(DatasetItem, DatasetItem.id == EvalRunItem.dataset_item_id)
            .where(EvalRunItem.run_id == run.id)
            .order_by(DatasetItem.position, EvalRunItem.id)
        )
    )
    report_items = [
        RunReportItem(
            id=str(run_item.id),
            position=dataset_item.position,
            status=run_item.status,
            category=dataset_item.category,
            output=run_item.output,
            trace=run_item.trace,
            scores=run_item.scores,
            error=run_item.error,
        )
        for run_item, dataset_item in rows
    ]
    trace_issues = [
        issue.model_copy(update={"run_item_id": item.id})
        for item in report_items
        if item.status == "completed"
        for issue in readiness_issues_for_trace(item.trace)
    ]
    criteria = criteria_snapshot(run.criteria_snapshot)
    verdict = evaluate_verdict(
        criteria,
        [
            VerdictItem(
                id=item.id,
                position=item.position,
                status=item.status,
                category=item.category,
                scores=item.scores,
                error=item.error,
            )
            for item in report_items
        ],
        run_status=run.status,
    )
    if trace_issues:
        verdict.readiness.issues.extend(trace_issues)
        verdict.readiness.status = "needs_attention"
    return RunReportOut(
        run_id=str(run.id),
        status=run.status,
        criteria=criteria,
        verdict=verdict,
        items=report_items,
    )


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
