from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import (
    AppVersion,
    AuditLog,
    ConnectorProfile,
    Dataset,
    DatasetItem,
    DatasetVersion,
    EvalRun,
    EvalRunItem,
    Project,
    ProjectBaseline,
    ProjectVerdictCriteria,
    ProviderConfig,
    User,
    WorkspaceMembership,
)
from app.phase4_schemas import MetricScoreOut
from app.phase5_schemas import (
    DEFAULT_VERDICT_CRITERIA,
    RunReportItem,
    RunReportMetadata,
    RunReportMetric,
    RunReportOut,
    VerdictCriteria,
)
from app.services.comparison import (
    ComparisonItem,
    compare_runs,
    regression_report,
)
from app.services.report_exports import (
    render_case_csv,
    render_html_report,
    render_pdf_report,
    sanitize_report_mapping,
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
    report_format: Annotated[
        Literal["html", "pdf", "json", "csv"], Query(alias="format")
    ] = "json",
) -> RunReportOut | Response:
    run = await db.scalar(
        select(EvalRun).where(
            EvalRun.id == run_id,
            EvalRun.project_id == project_id,
            EvalRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return await _run_report_export(db, run, report_format)


@router.get(
    "/runs/{run_id}/report",
    response_model=RunReportOut,
    summary="Download an evaluation run report",
)
async def get_run_report_by_id(
    run_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    report_format: Annotated[
        Literal["html", "pdf", "json", "csv"], Query(alias="format")
    ] = "json",
) -> RunReportOut | Response:
    run = await db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    membership = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == run.workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Workspace access denied")
    if membership.role not in {"owner", "admin", "engineer", "reviewer", "viewer"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await _run_report_export(db, run, report_format)


async def _run_report_export(
    db: AsyncSession,
    run: EvalRun,
    report_format: Literal["html", "pdf", "json", "csv"],
) -> RunReportOut | Response:
    report = await _build_run_report(db, run)
    if report_format == "json":
        return report
    run_id = report.run_id
    filename = f"greenlit-run-{run_id}.{report_format}"
    if report_format == "html":
        return Response(
            content=render_html_report(report),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
            },
        )
    if report_format == "pdf":
        return Response(
            content=render_pdf_report(report),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
            },
        )
    return Response(
        content=render_case_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


async def _build_run_report(db: AsyncSession, run: EvalRun) -> RunReportOut:
    project = await db.get(Project, run.project_id)
    dataset_version = await db.get(DatasetVersion, run.dataset_version_id)
    app_version = await db.get(AppVersion, run.app_version_id)
    if project is None or dataset_version is None or app_version is None:
        raise HTTPException(status_code=404, detail="Evaluation run metadata not found")
    dataset = await db.get(Dataset, dataset_version.dataset_id)
    if dataset is None or dataset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Evaluation dataset not found")

    config = app_version.config_snapshot
    connector = (
        await db.get(ConnectorProfile, app_version.connector_profile_id)
        if app_version.connector_profile_id is not None
        else None
    )
    connector_type = config.get("entry_point_type")
    if not isinstance(connector_type, str) and connector is not None:
        connector_type = connector.entry_point_type
    if not isinstance(connector_type, str):
        connector_type = None

    provider_id_value = config.get("provider_id")
    if not isinstance(provider_id_value, str) and connector is not None:
        provider_id_value = (
            str(connector.provider_id) if connector.provider_id else None
        )
    provider_id: UUID | None = None
    if isinstance(provider_id_value, str):
        try:
            provider_id = UUID(provider_id_value)
        except ValueError:
            provider_id = None
    provider = (
        await db.scalar(
            select(ProviderConfig).where(
                ProviderConfig.id == provider_id,
                ProviderConfig.workspace_id == run.workspace_id,
            )
        )
        if provider_id is not None
        else None
    )

    settings_value = config.get("settings")
    if not isinstance(settings_value, dict) and connector is not None:
        settings_value = connector.settings
    settings = (
        sanitize_report_mapping(settings_value)
        if isinstance(settings_value, dict)
        else {}
    )
    model_value = config.get("model")
    if not isinstance(model_value, str) and connector is not None:
        model_value = connector.model
    model = model_value if isinstance(model_value, str) else None

    rows = list(
        await db.execute(
            select(EvalRunItem, DatasetItem)
            .join(DatasetItem, DatasetItem.id == EvalRunItem.dataset_item_id)
            .where(EvalRunItem.run_id == run.id)
            .order_by(DatasetItem.position, EvalRunItem.id)
        )
    )
    report_items: list[RunReportItem] = []
    for run_item, dataset_item in rows:
        scores = [
            score.model_copy(update={"details": sanitize_report_mapping(score.details)})
            for score in (
                MetricScoreOut.model_validate(raw_score)
                for raw_score in run_item.scores
            )
        ]
        report_items.append(
            RunReportItem(
                id=str(run_item.id),
                dataset_item_id=str(dataset_item.id),
                position=dataset_item.position,
                status=run_item.status,
                category=dataset_item.category,
                regression_critical=dataset_item.regression_critical,
                input=dataset_item.input_text,
                reference_answer=dataset_item.reference_answer,
                output=run_item.output,
                trace=sanitize_report_mapping(run_item.trace),
                scores=scores,
                error=run_item.error,
            )
        )
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

    metrics = _metric_summaries(report_items, criteria)
    failed_cases = [
        item for item in report_items if _is_failed_report_case(item, criteria)
    ]
    safety_scores = [
        score
        for item in report_items
        for score in item.scores
        if score.category == "safety"
    ]
    safety_numeric_scores = [
        score.score for score in safety_scores if score.score is not None
    ]
    safety_results: dict[str, object] = (
        {
            "available": True,
            "scored_metrics": sorted({score.name for score in safety_scores}),
            "scored_cases": len(safety_numeric_scores),
            "mean_score": (
                sum(safety_numeric_scores) / len(safety_numeric_scores)
                if safety_numeric_scores
                else None
            ),
        }
        if safety_scores
        else {
            "available": False,
            "reason": "No safety-category metric scores were recorded for this run.",
            "scored_metrics": [],
            "scored_cases": 0,
            "mean_score": None,
        }
    )
    regression = await _regression_summary(db, run, report_items)
    calibration: dict[str, object] = {
        "status": "unavailable",
        "n_items": 0,
        "reason": "Human calibration labels are not persisted for this run.",
    }
    return RunReportOut(
        run_id=str(run.id),
        status=run.status,
        metadata=RunReportMetadata(
            project_id=str(project.id),
            project_name=project.name,
            dataset_id=str(dataset.id),
            dataset_name=dataset.name,
            dataset_version=dataset_version.version,
            dataset_hash=dataset_version.content_hash,
            connector_type=connector_type,
            provider_id=str(provider.id) if provider is not None else None,
            provider_name=provider.name if provider is not None else None,
            provider_type=provider.provider_type if provider is not None else None,
            model=model or (provider.test_model if provider is not None else None),
            run_created_at=run.created_at.isoformat(),
            run_started_at=run.started_at.isoformat() if run.started_at else None,
            run_finished_at=run.finished_at.isoformat() if run.finished_at else None,
            app_version_id=str(app_version.id),
            app_version=app_version.version,
            settings=settings,
        ),
        criteria=criteria,
        rules_applied=criteria,
        verdict=verdict,
        metrics=metrics,
        items=report_items,
        failed_cases=failed_cases,
        safety_results=safety_results,
        regression_vs_baseline=regression,
        calibration_summary=calibration,
    )


def _metric_summaries(
    items: list[RunReportItem], criteria: VerdictCriteria
) -> list[RunReportMetric]:
    grouped: dict[str, list[MetricScoreOut]] = defaultdict(list)
    for item in items:
        for score in item.scores:
            grouped[score.name].append(score)
    summaries: list[RunReportMetric] = []
    for name, scores in sorted(grouped.items()):
        threshold = _hard_gate_threshold(name, criteria)
        numeric_scores = [score.score for score in scores if score.score is not None]
        status_counts: dict[str, int] = {}
        for score in scores:
            status_counts[score.status] = status_counts.get(score.status, 0) + 1
        summaries.append(
            RunReportMetric(
                name=name,
                category=scores[0].category,
                method=scores[0].method,
                mean_score=(
                    sum(numeric_scores) / len(numeric_scores)
                    if numeric_scores
                    else None
                ),
                scored_cases=len(numeric_scores),
                status_counts=status_counts,
                hard_gate_threshold=threshold,
                hard_gate_failures=(
                    sum(
                        score.score is not None and score.score < threshold
                        for score in scores
                    )
                    if threshold is not None
                    else 0
                ),
            )
        )
    return summaries


def _hard_gate_threshold(name: str, criteria: VerdictCriteria) -> float | None:
    candidates = [name, name.split(":", maxsplit=1)[0]]
    if candidates[-1] == "answer_match":
        candidates.append("answer_exact_match")
    for candidate in candidates:
        if candidate in criteria.hard_gates:
            return criteria.hard_gates[candidate]
    return None


def _is_failed_report_case(item: RunReportItem, criteria: VerdictCriteria) -> bool:
    if item.status != "completed" or item.error:
        return True
    return any(
        score.status == "error"
        or (
            (threshold := _hard_gate_threshold(score.name, criteria)) is not None
            and score.score is not None
            and score.score < threshold
        )
        for score in item.scores
    )


async def _regression_summary(
    db: AsyncSession, run: EvalRun, report_items: list[RunReportItem]
) -> dict[str, object]:
    baseline_record = await db.get(ProjectBaseline, run.project_id)
    if baseline_record is None or baseline_record.workspace_id != run.workspace_id:
        return {
            "status": "unavailable",
            "reason": "No approved project baseline exists.",
        }
    baseline = await db.get(EvalRun, baseline_record.run_id)
    if baseline is None:
        return {
            "status": "unavailable",
            "reason": "The approved baseline run is missing.",
        }
    if baseline.id == run.id:
        return {"status": "baseline", "baseline_run_id": str(baseline.id)}
    if run.status != "completed" or baseline.status != "completed":
        return {
            "status": "unavailable",
            "baseline_run_id": str(baseline.id),
            "reason": "Regression comparison requires both runs to be completed.",
        }
    if (
        baseline.dataset_version_id != run.dataset_version_id
        or baseline.split != run.split
    ):
        return {
            "status": "not_comparable",
            "baseline_run_id": str(baseline.id),
            "reason": "The baseline uses a different dataset version or split.",
        }
    baseline_items = await _comparison_items(db, baseline.id)
    candidate_items = [
        ComparisonItem(
            id=UUID(item.dataset_item_id),
            position=item.position,
            regression_critical=item.regression_critical,
            status=item.status,
            scores=item.scores,
        )
        for item in report_items
    ]
    comparison = compare_runs(baseline.id, run.id, baseline_items, candidate_items)
    return regression_report(comparison, baseline_items, candidate_items).model_dump(
        mode="json"
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
