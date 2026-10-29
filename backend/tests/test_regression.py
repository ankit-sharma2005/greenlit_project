"""Baseline and regression tests (spec 8.5).

The comparison is pure, so the statuses and their boundaries are exercised
directly; the API tests then cover the parts that need a database: one active
baseline per dataset version, owner scoping, storing the comparison when a run
finishes, exposing it on the run, and carrying it into the report.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.runs import get_progress_reader
from app.main import app
from app.models import Run, User, utcnow
from app.services.regression import (
    STATUS_BLOCK,
    STATUS_PASS,
    STATUS_WARN,
    CasePoint,
    MetricPoint,
    RegressionError,
    active_baseline,
    clear_baseline,
    compare,
    regression_for,
    set_baseline,
    store_regression,
)
from app.services.run_repository import (
    add_metric_result,
    create_run,
    create_run_item,
    update_run,
    update_run_item,
)
from app.services.run_service import get_enqueue

PASSWORD = "correct horse battery staple"
CSV_BYTES = (
    b"question,answer\nWhat is GreenLit?,GreenLit tests LLM apps.\nIs it fast?,Yes it is fast.\n"
)


@pytest.fixture(autouse=True)
def runtime() -> Iterator[SimpleNamespace]:
    queue: list[uuid.UUID] = []
    app.dependency_overrides[get_enqueue] = lambda: queue.append
    # A reader that never finds live progress, so the database is the source.
    app.dependency_overrides[get_progress_reader] = lambda: lambda _run_id: None
    yield SimpleNamespace(queue=queue)
    app.dependency_overrides.pop(get_enqueue, None)
    app.dependency_overrides.pop(get_progress_reader, None)


# ---- the pure comparison ---------------------------------------------------


def _points(score: float, *, passed: bool | None = None, **kwargs: object) -> list[MetricPoint]:
    return [
        MetricPoint(
            name="answer_match",
            score=score,
            passed=(score >= 0.6 if passed is None else passed),
            **kwargs,  # type: ignore[arg-type]
        )
    ]


def _cases(*passed: bool) -> list[CasePoint]:
    return [
        CasePoint(row_index=index, input=f"case {index}", passed=state)
        for index, state in enumerate(passed, start=1)
    ]


def test_identical_runs_are_a_pass() -> None:
    result = compare(_points(0.9), _points(0.9), _cases(True, True), _cases(True, True))

    assert result.status == STATUS_PASS
    assert result.metric_deltas[0].delta == 0.0
    assert "Nothing regressed" in result.reason


def test_a_small_drop_is_a_warning() -> None:
    result = compare(_points(0.9), _points(0.88), _cases(True), _cases(True))

    assert result.status == STATUS_WARN
    assert result.regressed_metrics == ["answer_match"]
    assert "within tolerance" in result.reason


def test_a_drop_beyond_the_tolerance_blocks() -> None:
    result = compare(_points(0.9), _points(0.80), _cases(True), _cases(True))

    assert result.status == STATUS_BLOCK
    assert "beyond the 0.05 tolerance" in result.reason
    assert "answer_match" in result.reason


def test_a_drop_exactly_at_the_tolerance_is_still_a_warning() -> None:
    # The tolerance is the drop allowed, so -0.05 is inside it and -0.06 is not.
    at_limit = compare(_points(0.90), _points(0.85), _cases(True), _cases(True))
    beyond = compare(_points(0.90), _points(0.84), _cases(True), _cases(True))

    assert at_limit.status == STATUS_WARN
    assert beyond.status == STATUS_BLOCK


def test_a_hard_gate_that_stops_passing_blocks() -> None:
    baseline = [MetricPoint("attack_resisted", 1.0, True, hard_gate=True)]
    current = [MetricPoint("attack_resisted", 0.98, False, hard_gate=True)]

    result = compare(baseline, current, [], [])

    assert result.status == STATUS_BLOCK
    assert "hard gate attack_resisted" in result.reason


def test_a_few_regressed_cases_warn_and_more_than_the_tolerance_blocks() -> None:
    baseline = _cases(True, True, True, True)
    few = _cases(True, True, False, True)
    many = _cases(False, False, False, True)

    assert compare(_points(0.9), _points(0.9), baseline, few).status == STATUS_WARN
    blocked = compare(_points(0.9), _points(0.9), baseline, many)
    assert blocked.status == STATUS_BLOCK
    assert len(blocked.regressed_cases) == 3
    assert "more than the 2 allowed" in blocked.reason


def test_a_case_that_failed_before_is_not_a_regression() -> None:
    result = compare(_points(0.9), _points(0.9), _cases(False, True), _cases(False, True))

    assert result.status == STATUS_PASS


def test_metrics_that_are_not_instrumented_in_both_runs_are_not_compared() -> None:
    baseline = [MetricPoint("retrieval_context_recall", 0.8, True)]
    current = [MetricPoint("retrieval_context_recall", 0.0, False, instrumented=False)]

    result = compare(baseline, current, [], [])

    # Saying "it dropped" about a metric nobody measured would be a lie.
    assert result.metric_deltas == []
    assert result.status == STATUS_PASS


def test_tolerances_are_configurable() -> None:
    result = compare(
        _points(0.9),
        _points(0.80),
        _cases(True),
        _cases(True),
        metric_tolerance=0.2,
    )

    assert result.status == STATUS_WARN


# ---- persistence and the API ----------------------------------------------


def _register(client: TestClient, email: str = "baseline@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Baseline Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _user_id(session_factory: sessionmaker[Session], email: str) -> uuid.UUID:
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        return user.id


def _dataset(client: TestClient, name: str = "Baseline golden") -> dict[str, object]:
    created = client.post(
        "/api/v1/datasets",
        data={"name": name},
        files={"file": ("golden.csv", CSV_BYTES, "text/csv")},
    )
    assert created.status_code == 201, created.text
    dataset = created.json()
    approved = client.post(f"/api/v1/datasets/{dataset['id']}/versions/1/approve")
    assert approved.status_code == 200, approved.text
    return dataset


def _run(
    session_factory: sessionmaker[Session],
    *,
    owner: uuid.UUID,
    version_id: uuid.UUID,
    dataset_id: uuid.UUID,
    name: str,
    answer_match: float = 0.9,
    hard_gate_failed: bool = False,
    second_case_passes: bool = True,
) -> uuid.UUID:
    """A finished run with one comparable metric and two cases."""
    with session_factory() as session:
        run = create_run(
            session,
            owner_id=owner,
            name=name,
            settings_snapshot={"entry_point": "http_endpoint"},
            dataset_id=dataset_id,
            dataset_version_id=version_id,
        )
        first = create_run_item(session, run, row_index=1, input_text="What is GreenLit?")
        second = create_run_item(session, run, row_index=2, input_text="Is it fast?")
        session.commit()
        update_run_item(session, first, state="completed", output="GreenLit tests LLM apps.")
        update_run_item(
            session,
            second,
            state="completed" if second_case_passes else "failed",
            output="Yes it is fast." if second_case_passes else "",
            error=None if second_case_passes else "answer mismatch",
        )
        add_metric_result(
            session,
            run,
            name="answer_match",
            score=answer_match,
            passed=answer_match >= 0.6,
            explanation=f"answer match {answer_match:.2f}",
            weight=0.6,
            threshold=0.6,
        )
        add_metric_result(
            session,
            run,
            name="attack_resisted",
            score=0.9 if hard_gate_failed else 1.0,
            passed=not hard_gate_failed,
            explanation="safety probes",
            weight=0.2,
            threshold=0.95,
            hard_gate=True,
        )
        update_run(
            session,
            run,
            state="completed",
            verdict="GO" if answer_match >= 0.6 else "NO_GO",
            score=answer_match,
            verdict_reason="finished",
            started_at=utcnow(),
            completed_at=utcnow(),
        )
        session.commit()
        return run.id


def test_setting_a_baseline_replaces_the_previous_one(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _dataset(client)
    owner = _user_id(session_factory, "baseline@example.com")
    version_id = uuid.UUID(str(dataset["versions"][0]["id"]))  # type: ignore[index]
    first = _run(
        session_factory,
        owner=owner,
        version_id=version_id,
        dataset_id=uuid.UUID(str(dataset["id"])),
        name="First run",
    )
    second = _run(
        session_factory,
        owner=owner,
        version_id=version_id,
        dataset_id=uuid.UUID(str(dataset["id"])),
        name="Second run",
    )

    created = client.post(f"/api/v1/runs/{first}/baseline", json={})
    assert created.status_code == 201, created.text
    assert created.json()["run_id"] == str(first)
    assert created.json()["metric_tolerance"] == pytest.approx(0.05)

    replaced = client.post(
        f"/api/v1/runs/{second}/baseline",
        json={"metric_tolerance": 0.1, "case_tolerance": 5},
    )
    assert replaced.status_code == 201, replaced.text
    assert replaced.json()["run_id"] == str(second)

    current = client.get(f"/api/v1/runs/{first}/baseline")
    assert current.status_code == 200, current.text
    assert current.json()["run_id"] == str(second)
    assert current.json()["case_tolerance"] == 5

    with session_factory() as session:
        baseline = active_baseline(session, owner, version_id)
        assert baseline is not None and baseline.run_id == second
        # One row per dataset version, not one per run.
        assert len(session.scalars(select(Run)).all()) == 2


def test_a_baseline_is_owner_scoped(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, email="owner-a@example.com")
    dataset = _dataset(client)
    owner = _user_id(session_factory, "owner-a@example.com")
    run_id = _run(
        session_factory,
        owner=owner,
        version_id=uuid.UUID(str(dataset["versions"][0]["id"])),  # type: ignore[index]
        dataset_id=uuid.UUID(str(dataset["id"])),
        name="Mine",
    )
    assert client.post(f"/api/v1/runs/{run_id}/baseline", json={}).status_code == 201

    client.cookies.clear()
    _register(client, email="owner-b@example.com")
    assert client.post(f"/api/v1/runs/{run_id}/baseline", json={}).status_code == 404
    assert client.delete(f"/api/v1/runs/{run_id}/baseline").status_code == 404


def test_only_a_completed_run_can_be_a_baseline(
    session_factory: sessionmaker[Session],
) -> None:
    owner_id = uuid.uuid4()
    with session_factory() as session:
        run = create_run(
            session,
            owner_id=owner_id,
            name="Still running",
            settings_snapshot={},
        )
        session.commit()
        with pytest.raises(RegressionError) as caught:
            set_baseline(session, run)
        assert caught.value.status == 409
        assert "completed" in caught.value.message


def test_the_regression_is_stored_when_the_run_finishes(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, email="stored@example.com")
    dataset = _dataset(client)
    owner = _user_id(session_factory, "stored@example.com")
    version_id = uuid.UUID(str(dataset["versions"][0]["id"]))  # type: ignore[index]
    dataset_id = uuid.UUID(str(dataset["id"]))
    baseline_id = _run(
        session_factory,
        owner=owner,
        version_id=version_id,
        dataset_id=dataset_id,
        name="Baseline run",
        answer_match=1.0,
    )
    with session_factory() as session:
        baseline_run = session.get(Run, baseline_id)
        assert baseline_run is not None
        set_baseline(session, baseline_run)
        session.commit()

    worse_id = _run(
        session_factory,
        owner=owner,
        version_id=version_id,
        dataset_id=dataset_id,
        name="Worse run",
        answer_match=0.55,
    )
    with session_factory() as session:
        run = session.get(Run, worse_id)
        assert run is not None
        stored = store_regression(session, run)
        session.commit()
        assert stored is not None
        assert stored["status"] == STATUS_BLOCK
        assert stored["regressed_metrics"] == ["answer_match"]
        assert stored["baseline_run_id"] == str(baseline_id)
        snapshot = dict(run.settings_snapshot or {})
        assert snapshot["regression"]["status"] == STATUS_BLOCK

    payload = client.get(f"/api/v1/runs/{worse_id}").json()
    assert payload["regression"]["status"] == STATUS_BLOCK
    assert "answer_match" in payload["regression"]["reason"]
    assert payload["is_baseline"] is False

    baseline_payload = client.get(f"/api/v1/runs/{baseline_id}").json()
    assert baseline_payload["is_baseline"] is True
    # A baseline is not compared with itself.
    assert baseline_payload["regression"] is None


def test_clearing_the_baseline_removes_the_comparison(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, email="clear@example.com")
    dataset = _dataset(client)
    owner = _user_id(session_factory, "clear@example.com")
    version_id = uuid.UUID(str(dataset["versions"][0]["id"]))  # type: ignore[index]
    run_id = _run(
        session_factory,
        owner=owner,
        version_id=version_id,
        dataset_id=uuid.UUID(str(dataset["id"])),
        name="Baseline",
    )
    assert client.post(f"/api/v1/runs/{run_id}/baseline", json={}).status_code == 201

    cleared = client.delete(f"/api/v1/runs/{run_id}/baseline")
    assert cleared.status_code == 204, cleared.text
    assert client.get(f"/api/v1/runs/{run_id}/baseline").json() is None

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert regression_for(session, run) is None
        assert clear_baseline(session, run) is False


def test_the_report_carries_the_regression(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, email="report@example.com")
    dataset = _dataset(client)
    owner = _user_id(session_factory, "report@example.com")
    version_id = uuid.UUID(str(dataset["versions"][0]["id"]))  # type: ignore[index]
    dataset_id = uuid.UUID(str(dataset["id"]))
    baseline_id = _run(
        session_factory,
        owner=owner,
        version_id=version_id,
        dataset_id=dataset_id,
        name="Baseline",
        answer_match=1.0,
    )
    with session_factory() as session:
        run = session.get(Run, baseline_id)
        assert run is not None
        set_baseline(session, run)
        session.commit()

    worse_id = _run(
        session_factory,
        owner=owner,
        version_id=version_id,
        dataset_id=dataset_id,
        name="Worse",
        answer_match=0.5,
        second_case_passes=False,
    )
    with session_factory() as session:
        run = session.get(Run, worse_id)
        assert run is not None
        store_regression(session, run)
        session.commit()

    report = client.get(f"/api/v1/runs/{worse_id}/report?format=html")
    assert report.status_code == 200, report.text
    body = report.text
    assert "Regression" in body
    assert "BLOCK" in body
    assert "answer match" in body
    assert "passed before and fail now" in body

    full = client.get(f"/api/v1/runs/{worse_id}/report?format=json").json()
    assert full["regression"]["status"] == STATUS_BLOCK
    assert full["regression"]["metric_deltas"][0]["name"] == "answer_match"
