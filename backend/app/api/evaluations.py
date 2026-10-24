"""Metrics and decision endpoints (M5).

The preview endpoint scores a set of outputs without persisting anything; runs
with stored results arrive with the worker in M6.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_current_user
from app.schemas.evaluation import (
    CaseIn,
    FailedCaseOut,
    MetricOut,
    PreviewRequest,
    PreviewResponse,
    TemplateOut,
    TemplatesResponse,
)
from app.services.criteria import list_templates
from app.services.decision import JudgeStatus
from app.services.evaluation import (
    CaseData,
    EvaluationError,
    cases_from_csv,
    evaluate_preview,
)

router = APIRouter(prefix="/api/v1/evaluations", tags=["evaluations"])


@router.get("/templates", response_model=TemplatesResponse)
def templates(user: Any = Depends(get_current_user)) -> TemplatesResponse:
    return TemplatesResponse(
        templates=[
            TemplateOut(
                key=profile.key,
                name=profile.name,
                description=profile.description,
                review_threshold=profile.review_threshold,
                go_threshold=profile.go_threshold,
                criteria=[criterion.to_dict() for criterion in profile.criteria],
            )
            for profile in list_templates()
        ],
        default="plain_chatbot",
    )


@router.post("/preview", response_model=PreviewResponse)
def preview(payload: PreviewRequest, user: Any = Depends(get_current_user)) -> PreviewResponse:
    try:
        cases = _cases(payload)
        result = evaluate_preview(
            profile_key=payload.profile,
            cases=cases,
            judge=JudgeStatus(
                unavailable_items=payload.judge.unavailable_items,
                low_confidence_items=payload.judge.low_confidence_items,
                disagreements=payload.judge.disagreements,
                tolerance=payload.judge.tolerance,
            ),
            latency_limit_ms=payload.latency_limit_ms,
        )
    except EvaluationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    weights = {criterion.metric: criterion for criterion in result.profile.criteria}
    return PreviewResponse(
        profile=result.profile.key,
        profile_name=result.profile.name,
        verdict=result.decision.verdict,
        score=result.decision.score,
        rule=result.decision.rule,
        reason=result.decision.reason,
        review_threshold=result.decision.review_threshold,
        go_threshold=result.decision.go_threshold,
        suggested_fixes=list(result.decision.suggested_fixes),
        metrics=[
            MetricOut(
                name=metric.name,
                score=metric.score,
                passed=metric.passed,
                explanation=metric.explanation,
                instrumented=metric.instrumented,
                weight=weights[metric.name].weight if metric.name in weights else 0.0,
                threshold=weights[metric.name].threshold if metric.name in weights else 0.0,
                hard_gate=weights[metric.name].hard_gate if metric.name in weights else False,
                details=metric.details,
            )
            for metric in result.metrics
        ],
        failed_cases=[
            FailedCaseOut(
                input=failure["input"],
                expected=failure["expected"],
                actual=failure["actual"],
                reason=failure["reason"],
            )
            for failure in result.failures
        ],
        item_count=result.item_count,
        valid_items=result.valid_items,
    )


def _cases(payload: PreviewRequest) -> list[CaseData]:
    if payload.csv:
        return cases_from_csv(payload.csv, payload.file_format)
    if not payload.cases:
        _reject("Add cases or paste a CSV with input and output columns.")
    return [_case_from_schema(case) for case in payload.cases]


def _case_from_schema(case: CaseIn) -> CaseData:
    return CaseData(
        input=case.input,
        expected_answer=case.expected_answer,
        output=case.output,
        retrieved_context=case.retrieved_context,
        reference_context=case.reference_context,
        tool_calls=case.tool_calls,
        expected_tool_calls=case.expected_tool_calls,
        latency_ms=case.latency_ms,
        tokens_in=case.tokens_in,
        tokens_out=case.tokens_out,
        error=case.error,
        timed_out=case.timed_out,
        output_schema=case.output_schema,
    )


def _reject(message: str) -> NoReturn:
    raise HTTPException(status_code=400, detail=message)
