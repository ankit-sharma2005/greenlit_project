"""Compare detail, comparability and the plain classification.

The stored PASS/WARN/BLOCK comparison is unchanged and still tested by
``test_regression.py``; here the extra detail and the classification are proven,
including that an unmeasured metric is never treated as zero.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import User, utcnow
from app.services.compare import (
    IMPROVED,
    REGRESSED,
    UNCHANGED,
    comparability,
    compare_detail,
    criteria_version,
    facts_of,
    is_deterministic_target,
)
from app.services.regression import active_baseline, set_baseline
from app.services.run_repository import (
    add_metric_result,
    create_run,
    create_run_item,
    update_run,
    update_run_item,
)

PASSWORD = "correct horse battery staple"
VERSION = uuid.uuid4()


def _register(client: TestClient, email: str = "ada@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Ada", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _user(session_factory: sessionmaker[Session], email: str = "ada@example.com") -> uuid.UUID:
    with session_factory() as session:
        owner = session.scalar(select(User).where(User.email == email))
        assert owner is not None
        return owner.id


def _run(
    session_factory: sessionmaker[Session],
    *,
    owner: uuid.UUID,
    name: str = "Run",
    verdict: str = "GO",
    score: float = 0.9,
    metrics: list[tuple[str, float, bool, bool, bool]] | None = None,
    cases: dict[int, str] | None = None,
    latency: dict[int, int] | None = None,
    profile: str = "plain_chatbot",
    version: uuid.UUID = VERSION,
    snapshot: dict[str, Any] | None = None,
) -> uuid.UUID:
    """A finished run with run-level metrics and cases: pass, fail or error."""
    with session_factory() as session:
        run = create_run(
            session,
            owner_id=owner,
            name=name,
            dataset_version_id=version,
            criteria_profile=profile,
            settings_snapshot=snapshot
            or {"entry_point": "http_endpoint", "test_types": ["quality"]},
        )
        for metric_name, value, passed, instrumented, hard_gate in metrics or [
            ("answer_match", score, True, True, False)
        ]:
            add_metric_result(
                session,
                run,
                name=metric_name,
                score=value,
                passed=passed,
                instrumented=instrumented,
                hard_gate=hard_gate,
            )
        for row_index, state in (cases or {1: "pass", 2: "pass"}).items():
            item = create_run_item(
                session, run, row_index=row_index, input_text=f"case {row_index}"
            )
            update_run_item(session, item, state="completed", output="answer", error=None)
            if state == "fail":
                add_metric_result(
                    session,
                    run,
                    name="answer_match",
                    score=0.0,
                    passed=False,
                    run_item_id=item.id,
                )
            if state == "error":
                update_run_item(session, item, state="error", output=None, error="boom")
            if latency and row_index in latency:
                update_run_item(session, item, latency_ms=latency[row_index])
        update_run(
            session,
            run,
            state="completed",
            verdict=verdict,
            score=score,
            verdict_reason="finished",
            started_at=utcnow(),
            completed_at=utcnow(),
        )
        session.commit()
        return run.id


@pytest.fixture()
def owner(client: TestClient, session_factory: sessionmaker[Session]) -> Iterator[uuid.UUID]:
    _register(client)
    yield _user(session_factory)


def _detail(
    session_factory: sessionmaker[Session],
    baseline: uuid.UUID,
    current: uuid.UUID,
    **kwargs: Any,
) -> dict[str, Any]:
    with session_factory() as session:
        from app.models import Run

        current_run = session.get(Run, current)
        baseline_run = session.get(Run, baseline)
        assert current_run is not None and baseline_run is not None
        return compare_detail(session, current_run, baseline_run, **kwargs)


# ---- classification --------------------------------------------------------


def test_a_worse_verdict_is_regressed(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(session_factory, owner=owner, verdict="GO", score=0.9)
    current = _run(session_factory, owner=owner, name="Second", verdict="REVIEW", score=0.9)
    detail = _detail(session_factory, baseline, current)
    assert detail["classification"] == REGRESSED
    assert "GO → REVIEW" in detail["classification_reason"]
    assert detail["existing_status"] == "PASS"


def test_a_hard_gate_that_newly_fails_is_regressed(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(
        session_factory,
        owner=owner,
        metrics=[
            ("attack_resisted", 1.0, True, True, True),
            ("answer_match", 0.9, True, True, False),
        ],
    )
    current = _run(
        session_factory,
        owner=owner,
        name="Second",
        metrics=[
            ("attack_resisted", 0.4, False, True, True),
            ("answer_match", 0.9, True, True, False),
        ],
    )
    detail = _detail(session_factory, baseline, current)
    assert detail["hard_gates"]["newly_failed"] == ["attack_resisted"]
    assert detail["classification"] == REGRESSED


def test_a_score_drop_beyond_the_tolerance_is_regressed(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(session_factory, owner=owner, score=0.9)
    current = _run(session_factory, owner=owner, name="Second", score=0.80)
    detail = _detail(session_factory, baseline, current, tolerance=0.05)
    assert detail["classification"] == REGRESSED
    assert "0.10" in detail["classification_reason"]


def test_a_score_drop_within_the_tolerance_is_unchanged(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(session_factory, owner=owner, score=0.90)
    current = _run(session_factory, owner=owner, name="Second", score=0.88)
    detail = _detail(session_factory, baseline, current, tolerance=0.05)
    assert detail["classification"] == UNCHANGED
    assert detail["score"]["delta"] == pytest.approx(-0.02)


def test_a_better_verdict_is_improved(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(session_factory, owner=owner, verdict="REVIEW", score=0.7)
    current = _run(session_factory, owner=owner, name="Second", verdict="GO", score=0.9)
    detail = _detail(session_factory, baseline, current)
    assert detail["classification"] == IMPROVED


def test_identical_runs_are_unchanged(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    run = _run(session_factory, owner=owner)
    detail = _detail(session_factory, run, run)
    assert detail["classification"] == UNCHANGED
    assert detail["score"]["delta"] == 0
    assert detail["cases"]["pass_to_fail"] == []


def test_a_metric_unmeasured_on_one_side_is_never_zero(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(
        session_factory,
        owner=owner,
        metrics=[
            ("answer_match", 0.9, True, True, False),
            ("groundedness", 0.8, True, True, False),
        ],
    )
    current = _run(
        session_factory,
        owner=owner,
        name="Second",
        metrics=[
            ("answer_match", 0.9, True, True, False),
            ("groundedness", 0.0, False, False, False),
        ],
        score=0.9,
    )
    detail = _detail(session_factory, baseline, current)
    grounded = next(item for item in detail["metrics"] if item["name"] == "groundedness")
    assert grounded["status"] == "not measured"
    assert grounded["delta"] is None
    assert grounded["baseline"] is None and grounded["current"] is None
    assert detail["classification"] == UNCHANGED
    assert detail["score"]["delta"] == 0


def test_flips_are_matched_by_row_index_and_one_sided_cases_listed(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(session_factory, owner=owner, cases={1: "pass", 2: "pass", 3: "pass"})
    current = _run(
        session_factory, owner=owner, name="Second", cases={1: "fail", 2: "pass", 4: "pass"}
    )
    detail = _detail(session_factory, baseline, current)
    assert [item["row_index"] for item in detail["cases"]["pass_to_fail"]] == [1]
    assert [item["row_index"] for item in detail["cases"]["only_in_baseline"]] == [3]
    assert [item["row_index"] for item in detail["cases"]["only_in_current"]] == [4]


def test_latency_uses_the_chart_percentiles(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(
        session_factory, owner=owner, cases={1: "pass", 2: "pass"}, latency={1: 100, 2: 300}
    )
    current = _run(
        session_factory,
        owner=owner,
        name="Second",
        cases={1: "pass", 2: "pass"},
        latency={1: 200, 2: 400},
    )
    detail = _detail(session_factory, baseline, current)
    assert detail["latency"]["baseline"]["p50"] == pytest.approx(200)
    assert detail["latency"]["baseline"]["p95"] == pytest.approx(290)
    assert detail["latency"]["delta"]["p50"] == pytest.approx(100)


# ---- comparability ---------------------------------------------------------


def test_a_different_dataset_version_is_not_comparable(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(session_factory, owner=owner, version=uuid.uuid4())
    current = _run(session_factory, owner=owner, name="Second", version=uuid.uuid4())
    detail = _detail(session_factory, baseline, current)
    assert detail["comparable"] is False
    assert detail["reasons"] == ["the dataset version is different"]
    assert detail["metrics"] == []
    assert detail["classification"] is None


def test_a_different_criteria_profile_or_rules_is_not_comparable(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(session_factory, owner=owner, profile="plain_chatbot")
    current = _run(session_factory, owner=owner, name="Second", profile="rag_grounded")
    detail = _detail(session_factory, baseline, current)
    assert detail["comparable"] is False
    assert "criteria profile" in detail["reasons"][0]

    # Same profile name but the rules' fingerprint differs: still a reason.
    from dataclasses import replace

    left = facts_of(
        type(
            "R",
            (),
            {
                "dataset_version_id": VERSION,
                "criteria_profile": "plain_chatbot",
                "settings_snapshot": {},
            },
        )()
    )
    assert comparability(left, replace(left, criteria_version="other")) == [
        "the criteria profile's rules changed between the runs"
    ]
    assert criteria_version("plain_chatbot") == criteria_version("plain_chatbot")
    assert criteria_version("plain_chatbot") != criteria_version("rag_grounded")


def test_a_different_safety_version_or_test_types_is_not_comparable(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(
        session_factory,
        owner=owner,
        snapshot={
            "entry_point": "http_endpoint",
            "test_types": ["quality", "safety"],
            "safety_sets": ["core"],
        },
    )
    current = _run(
        session_factory,
        owner=owner,
        name="Second",
        snapshot={
            "entry_point": "http_endpoint",
            "test_types": ["quality"],
            "safety_sets": ["core"],
        },
    )
    detail = _detail(session_factory, baseline, current)
    assert detail["comparable"] is False
    assert any("test types" in reason for reason in detail["reasons"])


def test_the_noise_caution_is_shown_for_a_model_backed_target(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    baseline = _run(session_factory, owner=owner)
    current = _run(session_factory, owner=owner, name="Second")
    detail = _detail(session_factory, baseline, current)
    assert detail["noise_caution"]
    assert "Repeat the run" in detail["noise_caution"]

    with session_factory() as session:
        from app.models import Run

        run = session.get(Run, baseline)
        assert run is not None
        assert is_deterministic_target(run) is False


def test_a_deterministic_target_flips_cases_without_the_caution(
    owner: uuid.UUID, session_factory: sessionmaker[Session]
) -> None:
    snapshot = {
        "entry_point": "http_endpoint",
        "test_types": ["quality"],
        "target": "http://host.docker.internal:9115/",
    }
    baseline = _run(session_factory, owner=owner, snapshot=snapshot, cases={1: "pass", 2: "pass"})
    current = _run(
        session_factory,
        owner=owner,
        name="Second",
        snapshot=snapshot,
        cases={1: "fail", 2: "pass"},
    )
    detail = _detail(session_factory, baseline, current)
    assert detail["deterministic_target"] is True
    assert detail["noise_caution"] is None
    assert detail["classification"] == REGRESSED


# ---- the API ---------------------------------------------------------------


def test_the_endpoint_refuses_a_tolerance_outside_the_range(
    owner: uuid.UUID, client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    run = _run(session_factory, owner=owner)
    response = client.get(f"/api/v1/runs/{run}/compare?against={run}&tolerance=0.9")
    assert response.status_code == 422


def test_comparing_with_a_run_that_is_not_yours_is_a_404(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, "owner-a@example.com")
    owner = _user(session_factory, "owner-a@example.com")
    run = _run(session_factory, owner=owner)
    client.cookies.clear()
    _register(client, "owner-b@example.com")
    assert client.get(f"/api/v1/runs/{run}/compare?against={run}").status_code == 404


def test_the_endpoint_uses_the_pinned_baseline_by_default(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    owner = _user(session_factory)
    baseline = _run(session_factory, owner=owner, verdict="GO", score=0.9)
    current = _run(session_factory, owner=owner, name="Second", verdict="REVIEW", score=0.8)
    with session_factory() as session:
        from app.models import Run

        baseline_run = session.get(Run, baseline)
        assert baseline_run is not None
        set_baseline(session, baseline_run)
        session.commit()
        assert active_baseline(session, owner, VERSION) is not None

    response = client.get(f"/api/v1/runs/{current}/compare")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["classification"] == REGRESSED
    assert body["baseline_run_id"] == str(baseline)
    assert body["verdict"] == {"baseline": "GO", "current": "REVIEW", "direction": "worse"}
    for forbidden in ("password", "api_key", "token", "secret"):
        assert forbidden not in response.text.lower()


def test_no_baseline_is_a_404(
    owner: uuid.UUID, client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    run = _run(session_factory, owner=owner)
    response = client.get(f"/api/v1/runs/{run}/compare")
    assert response.status_code == 404
    assert "No baseline" in response.json()["error"]["message"]
