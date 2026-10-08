from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import Base, async_session_maker, engine
from app.main import app
from app.models import (
    AppVersion,
    AuditLog,
    Dataset,
    DatasetItem,
    DatasetVersion,
    EvalRun,
    EvalRunItem,
    WorkspaceMembership,
)
from app.phase4_schemas import MetricScoreOut
from app.services.comparison import ComparisonItem, compare_runs, regression_report
from app.services.statistics import (
    holm_adjust,
    mcnemar_exact_p_value,
    paired_bootstrap_interval,
    paired_permutation_p_value,
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def prepare_phase6_db() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield


def test_paired_bootstrap_interval_is_exact_for_constant_differences() -> None:
    assert paired_bootstrap_interval(
        [0.1, 0.2, 0.3], [0.2, 0.3, 0.4], iterations=100
    ) == pytest.approx((0.1, 0.1))


def test_paired_permutation_uses_exact_two_sided_sign_flips() -> None:
    assert paired_permutation_p_value([0, 0, 0], [1, 1, 1]) == pytest.approx(0.25)


def test_mcnemar_exact_matches_known_discordant_pair_probability() -> None:
    assert mcnemar_exact_p_value([True] * 10, [False] * 10) == pytest.approx(2 / 2**10)


def test_holm_adjustment_controls_familywise_error() -> None:
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def score(value: float) -> MetricScoreOut:
    return MetricScoreOut(
        name="answer_quality",
        category="quality",
        method="rule",
        status="scored",
        score=value,
        reason="seeded regression fixture",
        rubric_version=1,
    )


def comparison_item(
    position: int, value: float, *, critical: bool = False
) -> ComparisonItem:
    return ComparisonItem(
        id=UUID(int=position),
        position=position,
        regression_critical=critical,
        status="completed",
        scores=[score(value)],
    )


def test_compare_runs_reports_no_significant_difference_for_equal_scores() -> None:
    baseline_id = uuid4()
    candidate_id = uuid4()
    baseline = [comparison_item(index, 0.8) for index in range(1, 6)]
    candidate = [comparison_item(index, 0.8) for index in range(1, 6)]
    report = compare_runs(baseline_id, candidate_id, baseline, candidate)
    assert report.outcome == "no_significant_difference"
    assert report.metrics[0].classification == "no_significant_change"
    assert report.metrics[0].delta == 0
    assert report.metrics[0].paired_permutation_p_value == 1
    assert report.metrics[0].mcnemar_p_value == 1


def test_seeded_regressing_version_returns_block_with_new_failure() -> None:
    baseline_id = uuid4()
    candidate_id = uuid4()
    baseline = [comparison_item(index, 0.9) for index in range(1, 6)]
    candidate = [
        comparison_item(index, 0.2, critical=index == 2) for index in range(1, 6)
    ]
    comparison = compare_runs(baseline_id, candidate_id, baseline, candidate)
    report = regression_report(comparison, baseline, candidate)
    assert report.status == "BLOCK"
    assert report.new_failures
    assert report.new_failures[1].position == 2
    assert report.new_failures[1].regression_critical
    assert "Regression-critical item #2" in report.reasons[0]


def test_new_noncritical_failure_returns_warn() -> None:
    baseline_id = uuid4()
    candidate_id = uuid4()
    baseline = [comparison_item(index, 0.9) for index in range(1, 6)]
    candidate = [
        comparison_item(index, 0.2 if index == 1 else 0.9) for index in range(1, 6)
    ]
    comparison = compare_runs(baseline_id, candidate_id, baseline, candidate)
    report = regression_report(comparison, baseline, candidate)
    assert report.status == "WARN"
    assert report.new_failures[0].position == 1


async def create_phase6_project(
    client: AsyncClient, workspace_id: UUID, access_token: str
) -> UUID:
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "Phase 6 project"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


@pytest.mark.asyncio
async def test_baseline_approval_and_regression_api_are_scoped_and_audited() -> None:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"phase6-{uuid4()}@example.com",
            "password": "StrongPass1!",
            "workspace_name": "Phase 6 Workspace",
        },
    )
    assert signup.status_code == 200, signup.text
    user_id = UUID(signup.json()["user"]["id"])
    workspace_id = UUID(signup.json()["workspace"]["id"])
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    project_id = await create_phase6_project(
        client, workspace_id, signup.json()["access_token"]
    )
    base = f"/api/v1/workspaces/{workspace_id}/projects/{project_id}"

    try:
        async with async_session_maker() as db:
            dataset = Dataset(
                project_id=project_id,
                name=f"phase6-dataset-{uuid4()}",
                task_type="chatbot",
                created_by=user_id,
            )
            db.add(dataset)
            await db.flush()
            version = DatasetVersion(
                dataset_id=dataset.id,
                version=1,
                content_hash="b" * 64,
                split_strategy="random",
            )
            app_version = AppVersion(
                project_id=project_id,
                version=1,
                connector_profile_id=None,
                content_hash=None,
                config_snapshot={},
                access_level=None,
            )
            db.add_all([version, app_version])
            await db.flush()
            items = [
                DatasetItem(
                    dataset_version_id=version.id,
                    position=position,
                    input_text=f"question {position}",
                    reference_answer=f"answer {position}",
                    reference_context=None,
                    category="normal",
                    provenance="uploaded",
                    review_status="approved",
                    regression_critical=position == 2,
                    split="dev",
                    data={},
                )
                for position in range(1, 6)
            ]
            db.add_all(items)
            await db.flush()
            runs = [
                EvalRun(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    app_version_id=app_version.id,
                    dataset_version_id=version.id,
                    split="all",
                    criteria_snapshot={},
                    created_by=user_id,
                    status="completed",
                    total_items=5,
                    completed_items=5,
                )
                for _ in range(2)
            ]
            db.add_all(runs)
            await db.flush()
            for run_index, run in enumerate(runs):
                db.add_all(
                    [
                        EvalRunItem(
                            run_id=run.id,
                            dataset_item_id=dataset_item.id,
                            status="completed",
                            output="answer",
                            trace={},
                            scores=[
                                {
                                    "name": "answer_quality",
                                    "category": "quality",
                                    "method": "rule",
                                    "status": "scored",
                                    "score": 0.9 if run_index == 0 else 0.2,
                                    "reason": "seeded API test",
                                    "details": {},
                                    "judge_role": None,
                                    "rubric_version": 1,
                                    "cache_hit": False,
                                }
                            ],
                            attempts=1,
                        )
                        for dataset_item in items
                    ]
                )
            await db.commit()
            baseline_run_id, candidate_run_id = (run.id for run in runs)
            dataset_id = dataset.id
            item_ids = [item.id for item in items]

        critical_response = await client.post(
            f"{base}/datasets/{dataset_id}/versions/1/review",
            headers=headers,
            json={"item_ids": [str(item_ids[0])], "regression_critical": True},
        )
        assert critical_response.status_code == 200, critical_response.text
        assert critical_response.json()["items"][0]["regression_critical"] is True

        async with async_session_maker() as db:
            membership = await db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == user_id,
                )
            )
            assert membership is not None
            original_role = membership.role
            membership.role = "engineer"
            await db.commit()
        denied_promotion = await client.put(
            f"{base}/baseline",
            headers=headers,
            json={"run_id": str(baseline_run_id), "reason": "Not approved"},
        )
        assert denied_promotion.status_code == 403
        async with async_session_maker() as db:
            membership = await db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == user_id,
                )
            )
            assert membership is not None
            membership.role = original_role
            await db.commit()

        promoted = await client.put(
            f"{base}/baseline",
            headers=headers,
            json={"run_id": str(baseline_run_id), "reason": "Approved release"},
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["run_id"] == str(baseline_run_id)
        assert (await client.get(f"{base}/baseline", headers=headers)).json()[
            "run_id"
        ] == str(baseline_run_id)

        compared = await client.get(
            f"{base}/compare/{baseline_run_id}/{candidate_run_id}",
            headers=headers,
        )
        assert compared.status_code == 200, compared.text
        assert compared.json()["outcome"] == "no_significant_difference"
        regression = await client.get(
            f"{base}/regression/{candidate_run_id}",
            headers=headers,
        )
        assert regression.status_code == 200, regression.text
        assert regression.json()["status"] == "BLOCK"
        assert regression.json()["new_failures"]

        replaced = await client.put(
            f"{base}/baseline",
            headers=headers,
            json={"run_id": str(candidate_run_id), "reason": "Promoted candidate"},
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["run_id"] == str(candidate_run_id)
        assert (await client.get(f"{base}/baseline", headers=headers)).json()[
            "run_id"
        ] == str(candidate_run_id)

        async with async_session_maker() as db:
            audits = list(
                await db.scalars(
                    select(AuditLog).where(
                        AuditLog.workspace_id == workspace_id,
                        AuditLog.action == "project_baseline_promoted",
                    )
                )
            )
            assert len(audits) == 2
            assert {audit.details["run_id"] for audit in audits} == {
                str(baseline_run_id),
                str(candidate_run_id),
            }
    finally:
        await client.aclose()
