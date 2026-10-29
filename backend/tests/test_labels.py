"""Human labels, the review queue and calibration (M7).

Three things are worth testing here: the queue contains exactly the cases a
person can act on, a label belongs to its reviewer (re-submitting replaces it and
never creates a second opinion from the same person), and calibration reports
Cohen's kappa rather than the flattering raw agreement. The RBAC test is the one
that matters most: a plain member must not be able to label anything.
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
from app.models import User, utcnow
from app.services.judge import ANSWER_QUALITY
from app.services.labels import (
    REASON_DISAGREES,
    REASON_LOW_CONFIDENCE,
    REASON_UNAVAILABLE,
    review_queue,
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
JUDGE_MODEL = "judge-model"


@pytest.fixture(autouse=True)
def runtime() -> Iterator[SimpleNamespace]:
    queue: list[uuid.UUID] = []
    app.dependency_overrides[get_enqueue] = lambda: queue.append
    app.dependency_overrides[get_progress_reader] = lambda: lambda _run_id: None
    yield SimpleNamespace(queue=queue)
    app.dependency_overrides.pop(get_enqueue, None)
    app.dependency_overrides.pop(get_progress_reader, None)


def _register(client: TestClient, email: str, name: str = "Person") -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(client: TestClient, email: str) -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def _user(session_factory: sessionmaker[Session], email: str) -> User:
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        return user


def _seed_judged_run(
    session_factory: sessionmaker[Session],
    owner_id: uuid.UUID,
) -> dict[str, uuid.UUID]:
    """Four judged cases: unavailable, unsure, confident-pass and confident-fail."""
    with session_factory() as session:
        run = create_run(
            session,
            owner_id=owner_id,
            name="Judged run",
            settings_snapshot={"entry_point": "http_endpoint"},
        )
        items = {
            name: create_run_item(session, run, row_index=index, input_text=f"{name}?")
            for index, name in enumerate(("unavailable", "unsure", "good", "bad"), start=1)
        }
        session.commit()
        for name, item in items.items():
            update_run_item(session, item, state="completed", output=f"{name} answer")
        add_metric_result(
            session,
            run,
            name=ANSWER_QUALITY,
            score=0.0,
            passed=False,
            explanation="the judge was unavailable",
            instrumented=False,
            run_item_id=items["unavailable"].id,
            details={"confidence": None},
        )
        add_metric_result(
            session,
            run,
            name=ANSWER_QUALITY,
            score=0.9,
            passed=True,
            explanation="probably right",
            run_item_id=items["unsure"].id,
            details={"confidence": 0.2},
        )
        add_metric_result(
            session,
            run,
            name=ANSWER_QUALITY,
            score=0.95,
            passed=True,
            explanation="matches the expected answer",
            run_item_id=items["good"].id,
            details={"confidence": 0.95},
        )
        add_metric_result(
            session,
            run,
            name=ANSWER_QUALITY,
            score=0.1,
            passed=False,
            explanation="wrong answer",
            run_item_id=items["bad"].id,
            details={"confidence": 0.9},
        )
        update_run(
            session,
            run,
            state="completed",
            verdict="REVIEW",
            score=0.5,
            verdict_reason="the judge was unsure",
            started_at=utcnow(),
            completed_at=utcnow(),
        )
        session.commit()
        return {name: item.id for name, item in items.items()}


# ---- the queue -------------------------------------------------------------


def test_the_queue_holds_only_the_cases_a_person_can_act_on(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, "reviewer@example.com")
    owner = _user(session_factory, "reviewer@example.com")
    items = _seed_judged_run(session_factory, owner.id)

    with session_factory() as session:
        cases = review_queue(session, owner.id)

    by_item = {case.run_item_id: case for case in cases}
    assert set(by_item) == {items["unavailable"], items["unsure"]}
    assert by_item[items["unavailable"]].reasons == [REASON_UNAVAILABLE]
    assert by_item[items["unavailable"]].judge_bucket is None
    assert by_item[items["unsure"]].reasons == [REASON_LOW_CONFIDENCE]
    assert by_item[items["unsure"]].judge_confidence == pytest.approx(0.2)
    assert by_item[items["unsure"]].output == "unsure answer"


def test_the_queue_lists_a_case_whose_label_disagrees_with_the_judge(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, "disagree@example.com")
    owner = _user(session_factory, "disagree@example.com")
    items = _seed_judged_run(session_factory, owner.id)

    labelled = client.post(
        f"/api/v1/review/items/{items['good']}/label",
        json={"label": "fail", "note": "The date in the answer is wrong."},
    )
    assert labelled.status_code == 201, labelled.text

    queue = client.get("/api/v1/review/queue").json()
    case = next(item for item in queue["items"] if item["run_item_id"] == str(items["good"]))
    assert REASON_DISAGREES in case["reasons"]
    assert case["label"] == "fail"
    assert case["note"] == "The date in the answer is wrong."


def test_a_second_label_from_the_same_reviewer_replaces_the_first(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, "relabel@example.com")
    owner = _user(session_factory, "relabel@example.com")
    items = _seed_judged_run(session_factory, owner.id)

    first = client.post(f"/api/v1/review/items/{items['unsure']}/label", json={"label": "pass"})
    second = client.post(
        f"/api/v1/review/items/{items['unsure']}/label",
        json={"label": "fail", "note": "Second look: the fact is wrong."},
    )
    assert first.status_code == 201 and second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["label"] == "fail"

    queue = client.get("/api/v1/review/queue").json()
    case = next(item for item in queue["items"] if item["run_item_id"] == str(items["unsure"]))
    assert case["label"] == "fail"


def test_an_unknown_case_is_a_404(client: TestClient) -> None:
    _register(client, "missing@example.com")

    response = client.post(f"/api/v1/review/items/{uuid.uuid4()}/label", json={"label": "pass"})

    assert response.status_code == 404


def test_an_invalid_label_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, "invalid@example.com")
    owner = _user(session_factory, "invalid@example.com")
    items = _seed_judged_run(session_factory, owner.id)

    response = client.post(
        f"/api/v1/review/items/{items['unsure']}/label",
        json={"label": "maybe"},
    )

    assert response.status_code == 422


# ---- calibration -----------------------------------------------------------


def test_calibration_reports_kappa_over_agreeing_and_disagreeing_labels(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, "kappa@example.com")
    owner = _user(session_factory, "kappa@example.com")
    items = _seed_judged_run(session_factory, owner.id)

    # Judge said pass/pass/fail (good, unsure, bad); the reviewer agrees twice.
    for name, label in (("good", "pass"), ("unsure", "fail"), ("bad", "fail")):
        response = client.post(f"/api/v1/review/items/{items[name]}/label", json={"label": label})
        assert response.status_code == 201, response.text

    summary = client.get("/api/v1/review/calibration").json()

    assert summary["labelled"] == 3
    assert summary["agreed"] == 2
    assert summary["raw_agreement"] == pytest.approx(2 / 3, abs=1e-3)
    # po = 2/3, pe = 4/9, so kappa = (2/3 - 4/9) / (1 - 4/9) = 0.4.
    assert summary["kappa"] == pytest.approx(0.4, abs=0.01)
    assert "kappa" in summary["reading"]


def test_calibration_is_empty_before_any_label(client: TestClient) -> None:
    _register(client, "empty@example.com")

    summary = client.get("/api/v1/review/calibration").json()

    assert summary["labelled"] == 0
    assert summary["kappa"] is None
    assert "Not enough labels" in summary["reading"]


# ---- who may label ---------------------------------------------------------


def test_a_plain_member_cannot_label_or_read_the_queue(client: TestClient) -> None:
    _register(client, "admin@example.com", name="Admin")
    client.cookies.clear()
    _register(client, "member@example.com", name="Member")

    assert client.get("/api/v1/review/queue").status_code == 403
    assert client.get("/api/v1/review/calibration").status_code == 403
    unknown = f"/api/v1/review/items/{uuid.uuid4()}/label"
    assert client.post(unknown, json={"label": "pass"}).status_code == 403


def test_a_reviewer_may_label(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    admin = _register(client, "admin2@example.com", name="Admin")
    member = _register(client, "reviewer2@example.com", name="Reviewer")

    # Registering the member replaced the session cookie, so sign back in as the
    # admin to change the role; only an admin may do that.
    _login(client, "admin2@example.com")
    promoted = client.patch(
        f"/api/v1/users/{member['user']['id']}/role",  # type: ignore[index]
        json={"role": "reviewer"},
    )
    assert promoted.status_code == 200, promoted.text
    assert admin["user"]["role"] == "admin"  # type: ignore[index]

    _login(client, "reviewer2@example.com")
    owner = _user(session_factory, "reviewer2@example.com")
    items = _seed_judged_run(session_factory, owner.id)

    labelled = client.post(f"/api/v1/review/items/{items['unsure']}/label", json={"label": "pass"})

    assert labelled.status_code == 201, labelled.text
    assert client.get("/api/v1/review/queue").status_code == 200


def test_signing_out_locks_the_review_endpoints(client: TestClient) -> None:
    client.cookies.clear()

    assert client.get("/api/v1/review/queue").status_code == 401
