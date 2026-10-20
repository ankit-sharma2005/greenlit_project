from __future__ import annotations

import csv
from collections.abc import AsyncIterator
from typing import Literal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.db import Base, async_session_maker, engine
from app.main import app
from app.models import (
    AppVersion,
    Dataset,
    DatasetItem,
    DatasetVersion,
    EvalRun,
    EvalRunItem,
)
from app.phase4_schemas import MetricScoreOut
from app.phase5_schemas import VerdictCriteria
from app.services.verdicts import (
    VerdictItem,
    evaluate_verdict,
    readiness_issues_for_trace,
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def prepare_phase5_db() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield


def score(
    name: str,
    category: str,
    value: float | None,
    *,
    status: Literal["scored", "not_instrumented", "not_configured", "error"] = "scored",
    reason: str = "fixed fixture",
    method: Literal["rule", "llm_judge"] = "rule",
) -> MetricScoreOut:
    return MetricScoreOut(
        name=name,
        category=category,
        method=method,
        status=status,
        score=value,
        reason=reason,
        rubric_version=1,
    )


def test_judge_error_requires_review_even_when_rule_metrics_pass() -> None:
    report = evaluate_verdict(
        VerdictCriteria(go_threshold=0.8, review_threshold=0.6),
        [
            VerdictItem(
                id="run-item-1",
                position=1,
                status="completed",
                category="quality",
                scores=[
                    score("output_nonempty", "quality", 1.0),
                    score("answer_match", "quality", 1.0),
                    score(
                        "answer_quality:dev",
                        "quality",
                        None,
                        status="error",
                        reason="Judge provider request timed out after 12 seconds",
                        method="llm_judge",
                    ),
                ],
            )
        ],
        run_status="completed",
    )

    assert report.verdict == "REVIEW"
    assert report.reasons == [
        "Judge metric 'answer_quality:dev' failed on item #1: "
        "Judge provider request timed out after 12 seconds"
    ]


def test_hard_gate_failure_forces_no_go_with_exact_reason() -> None:
    criteria = VerdictCriteria(
        go_threshold=0.8,
        review_threshold=0.6,
        hard_gates={"output_nonempty": 0.9},
    )
    report = evaluate_verdict(
        criteria,
        [
            VerdictItem(
                id="run-item-1",
                position=1,
                status="completed",
                category="normal",
                scores=[
                    score("output_nonempty", "quality", 0.4),
                    score("answer_match", "quality", 1.0),
                    score("answer_quality", "quality", 1.0),
                ],
            )
        ],
        run_status="completed",
    )
    assert report.verdict == "NO_GO"
    assert report.reasons == [
        "Hard gate 'output_nonempty' failed on item #1: "
        "score 0.40 is below required 0.90."
    ]
    assert report.score == pytest.approx(0.8)


def test_hard_gate_matches_role_suffixed_judge_metric() -> None:
    report = evaluate_verdict(
        VerdictCriteria(hard_gates={"answer_quality": 0.8}),
        [
            VerdictItem(
                id="run-item-1",
                position=1,
                status="completed",
                category="quality",
                scores=[score("answer_quality:dev", "quality", 0.6)],
            )
        ],
        run_status="completed",
    )
    assert report.verdict == "NO_GO"
    assert report.reasons == [
        "Hard gate 'answer_quality' failed on item #1: "
        "score 0.60 is below required 0.80."
    ]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_or_cancelled_run_cannot_receive_go(status: str) -> None:
    report = evaluate_verdict(
        VerdictCriteria(go_threshold=0.8),
        [
            VerdictItem(
                id="run-item-1",
                position=1,
                status="completed",
                category="quality",
                scores=[score("answer_quality", "quality", 1.0)],
            )
        ],
        run_status=status,
    )
    assert report.verdict == "NO_GO"
    assert report.reasons == [f"Run status is '{status}'."]


@pytest.mark.parametrize(
    ("value", "expected", "reason_fragment"),
    [
        (0.8, "GO", ">= GO threshold 0.80"),
        (0.6, "REVIEW", "between REVIEW threshold 0.60"),
        (0.59, "NO_GO", "< REVIEW threshold 0.60"),
    ],
)
def test_weighted_score_threshold_edges(
    value: float, expected: str, reason_fragment: str
) -> None:
    report = evaluate_verdict(
        VerdictCriteria(go_threshold=0.8, review_threshold=0.6),
        [
            VerdictItem(
                id="run-item-1",
                position=1,
                status="completed",
                category="normal",
                scores=[score("output_nonempty", "quality", value)],
            )
        ],
        run_status="completed",
    )
    assert report.verdict == expected
    assert report.score == pytest.approx(value)
    assert reason_fragment in report.reasons[0]


def test_category_weights_control_the_weighted_run_score() -> None:
    report = evaluate_verdict(
        VerdictCriteria(
            go_threshold=0.8,
            review_threshold=0.6,
            category_weights={"quality": 1, "rag": 3},
        ),
        [
            VerdictItem(
                id="run-item-1",
                position=1,
                status="completed",
                category="normal",
                scores=[
                    score("answer_quality", "quality", 0.5),
                    score("retrieval_context_recall", "rag", 0.9),
                ],
            )
        ],
        run_status="completed",
    )
    assert report.score == pytest.approx(0.8)
    assert report.verdict == "GO"
    assert [category.category for category in report.categories] == ["quality", "rag"]


def test_readiness_report_names_unavailable_metric_and_failed_component() -> None:
    report = evaluate_verdict(
        VerdictCriteria(),
        [
            VerdictItem(
                id="run-item-1",
                position=1,
                status="failed",
                category="normal",
                scores=[
                    score(
                        "retrieval_context_recall",
                        "rag",
                        None,
                        status="not_instrumented",
                        reason="Required field is missing: steps.retrieved_chunks",
                    )
                ],
                error="TimeoutError: connector execution failed",
            )
        ],
        run_status="completed",
    )
    assert report.readiness.status == "needs_attention"
    assert {issue.component for issue in report.readiness.issues} == {
        "application execution",
        "retrieval_context_recall",
    }
    assert report.verdict == "NO_GO"


def test_readiness_detects_missing_application_instrumentation_fields() -> None:
    issues = readiness_issues_for_trace(
        {
            "output": "answer",
            "steps": {},
            "usage": {"tokens_in": None, "tokens_out": None},
        }
    )
    assert {issue.component for issue in issues} == {
        "model_used",
        "usage.tokens_in",
        "usage.tokens_out",
        "steps.retrieved_chunks",
        "steps.tool_calls",
    }


def test_verdict_criteria_reject_invalid_threshold_order_and_unknown_metric() -> None:
    with pytest.raises(ValidationError, match="review_threshold"):
        VerdictCriteria(go_threshold=0.5, review_threshold=0.8)
    with pytest.raises(ValidationError, match="Unknown hard-gate metrics"):
        VerdictCriteria(hard_gates={"not_a_metric": 0.5})


async def signed_in_client() -> tuple[AsyncClient, UUID, UUID, str]:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"phase5-{uuid4()}@example.com",
            "password": "StrongPass1!",
            "workspace_name": "Phase 5 Workspace",
        },
    )
    assert signup.status_code == 200, signup.text
    user_id = UUID(signup.json()["user"]["id"])
    workspace_id = UUID(signup.json()["workspace"]["id"])
    return client, user_id, workspace_id, signup.json()["access_token"]


async def create_project(
    client: AsyncClient, workspace_id: UUID, access_token: str
) -> UUID:
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "Phase 5 project"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


@pytest.mark.asyncio
async def test_criteria_api_is_project_scoped_and_reports_saved_run_snapshot() -> None:
    client, user_id, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    project_id = await create_project(client, workspace_id, access_token)
    base = f"/api/v1/workspaces/{workspace_id}/projects/{project_id}"
    try:
        initial = await client.get(f"{base}/verdict-criteria", headers=headers)
        assert initial.status_code == 200, initial.text
        assert initial.json()["go_threshold"] == 0.8

        saved = await client.put(
            f"{base}/verdict-criteria",
            headers=headers,
            json={
                "go_threshold": 0.9,
                "review_threshold": 0.6,
                "category_weights": {"quality": 2},
                "hard_gates": {"output_nonempty": 0.9},
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["category_weights"] == {"quality": 2.0}

        async with async_session_maker() as db:
            dataset = Dataset(
                project_id=project_id,
                name=f"phase5-dataset-{uuid4()}",
                task_type="chatbot",
                created_by=user_id,
            )
            db.add(dataset)
            await db.flush()
            version = DatasetVersion(
                dataset_id=dataset.id,
                version=1,
                content_hash="a" * 64,
                split_strategy="random",
            )
            app_version = AppVersion(
                project_id=project_id,
                version=1,
                connector_profile_id=None,
                content_hash=None,
                config_snapshot={
                    "entry_point_type": "UPLOAD_OUTPUTS",
                    "model": "test-model",
                    "settings": {
                        "mapping": {"input_field": "question"},
                        "api_key": "must-not-appear",
                    },
                },
                access_level=None,
            )
            db.add_all([version, app_version])
            await db.flush()
            dataset_item = DatasetItem(
                dataset_version_id=version.id,
                position=1,
                input_text="=1+1",
                reference_answer="42",
                reference_context=None,
                category="normal",
                provenance="uploaded",
                review_status="approved",
                split="dev",
                data={},
            )
            db.add(dataset_item)
            await db.flush()
            run = EvalRun(
                workspace_id=workspace_id,
                project_id=project_id,
                app_version_id=app_version.id,
                dataset_version_id=version.id,
                split="all",
                criteria_snapshot=saved.json(),
                created_by=user_id,
                status="completed",
                total_items=1,
                completed_items=1,
            )
            db.add(run)
            await db.flush()
            run_item = EvalRunItem(
                run_id=run.id,
                dataset_item_id=dataset_item.id,
                status="completed",
                output="An answer",
                trace={
                    "output": "An answer",
                    "steps": {"retrieved_chunks": [{"text": "A supporting chunk"}]},
                    "usage": {"tokens_in": 10, "tokens_out": 5},
                    "model_used": "test-model",
                    "authorization": "Bearer must-not-appear",
                },
                scores=[
                    {
                        "name": "output_nonempty",
                        "category": "quality",
                        "method": "rule",
                        "status": "scored",
                        "score": 0.5,
                        "reason": "Output is present",
                        "details": {},
                        "judge_role": None,
                        "rubric_version": 1,
                        "cache_hit": False,
                    }
                ],
                attempts=1,
            )
            db.add(run_item)
            await db.commit()
            run_id = run.id

        response = await client.get(f"/api/v1/runs/{run_id}/report", headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["criteria"]["go_threshold"] == 0.9
        assert report["verdict"]["verdict"] == "NO_GO"
        assert report["verdict"]["reasons"] == [
            "Hard gate 'output_nonempty' failed on item #1: "
            "score 0.50 is below required 0.90."
        ]
        assert report["items"][0]["trace"]["steps"]["retrieved_chunks"][0]["text"] == (
            "A supporting chunk"
        )
        assert report["verdict"]["readiness"]["status"] == "needs_attention"
        assert report["metadata"]["project_name"] == "Phase 5 project"
        assert report["metadata"]["dataset_version"] == 1
        assert report["metadata"]["dataset_hash"] == "a" * 64
        assert report["metadata"]["connector_type"] == "UPLOAD_OUTPUTS"
        assert report["metrics"][0]["hard_gate_threshold"] == 0.9
        assert report["metrics"][0]["hard_gate_failures"] == 1
        assert report["failed_cases"][0]["position"] == 1
        assert report["safety_results"]["available"] is False
        assert report["calibration_summary"]["status"] == "unavailable"
        assert "api_key" not in report["metadata"]["settings"]
        assert "authorization" not in report["items"][0]["trace"]
        assert "must-not-appear" not in response.text
        assert any(
            issue["component"] == "steps.tool_calls"
            for issue in report["verdict"]["readiness"]["issues"]
        )

        invalid_format = await client.get(
            f"{base}/runs/{run_id}/report",
            params={"format": "docx"},
            headers=headers,
        )
        assert invalid_format.status_code == 422

        for export_format, media_type in (
            ("html", "text/html"),
            ("pdf", "application/pdf"),
            ("csv", "text/csv"),
        ):
            exported = await client.get(
                f"{base}/runs/{run_id}/report",
                params={"format": export_format},
                headers=headers,
            )
            assert exported.status_code == 200, exported.text
            assert exported.headers["content-type"].startswith(media_type)
            assert "attachment; filename=" in exported.headers["content-disposition"]
            assert "must-not-appear" not in exported.text
            if export_format == "html":
                assert "<!doctype html>" in exported.text
                assert "Regression vs baseline" in exported.text
            elif export_format == "pdf":
                assert exported.content.startswith(b"%PDF-1.4")
                assert exported.content.rstrip().endswith(b"%%EOF")
            else:
                rows = list(csv.DictReader(exported.text.splitlines()))
                assert rows[0]["metric"] == "output_nonempty"
                assert rows[0]["hard_gate_threshold"] == "0.9"
                assert rows[0]["input"] == "'=1+1"
                assert rows[0]["failed_case"] == "True"
                assert rows[0]["calibration_summary"]
                assert rows[0]["regression_vs_baseline"]

        unauthenticated = await client.get(f"/api/v1/runs/{run_id}/report")
        assert unauthenticated.status_code == 401

        other_client, _, _, other_token = await signed_in_client()
        try:
            forbidden = await other_client.get(
                f"/api/v1/runs/{run_id}/report",
                headers={"Authorization": f"Bearer {other_token}"},
            )
            assert forbidden.status_code == 403
        finally:
            await other_client.aclose()
    finally:
        await client.aclose()
