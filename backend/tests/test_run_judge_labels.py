"""The judge's per-case label on the per-case read and in the report (N2).

The judge already stores one ``answer_quality`` metric row per case, keyed by
``run_item_id``. These tests pin the three things that go wrong when that row is
joined to a case: the label lands on the wrong row, a case nobody scored invents
a label, or the export grows the columns without them meaning anything.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.runs import get_progress_reader
from app.main import app
from app.models import MetricResultRow, User
from app.services.run_repository import (
    add_metric_result,
    create_run,
    create_run_item,
    update_run,
    update_run_item,
)
from app.services.run_service import get_enqueue

PASSWORD = "correct horse battery staple"
OWNER = "judge-labels@example.com"
CSV_BYTES = b"question,answer\nWhat is GreenLit?,GreenLit tests LLM apps.\n"

# The CSV header as it was before this change, in order. The three judge columns are
# inserted before the permission block, so every existing column keeps its order and the
# three that were last stay last.
EXISTING_HEADER = [
    "row_index",
    "input",
    "expected",
    "actual",
    "state",
    "latency_ms",
    "retry_count",
    "waited_ms",
    "tokens_in",
    "tokens_out",
    "reason",
    "error_kind",
    "http_status",
    "target",
    "error_snippet",
    "verdict",
    "weighted_score",
    "latency_p50_ms",
    "latency_p95_ms",
    "error_rate",
    "timeout_rate",
    "retried_cases",
    "tokens_in_total",
    "tokens_out_total",
    "cost_estimate",
    "permission_confirmed",
    "permission_reference",
    "safety_attacks_confirmed",
]


@pytest.fixture(autouse=True)
def runtime() -> Iterator[SimpleNamespace]:
    """Queue and progress seams so no test needs Redis or a broker."""
    queue: list[uuid.UUID] = []
    app.dependency_overrides[get_enqueue] = lambda: queue.append
    app.dependency_overrides[get_progress_reader] = lambda: None
    yield SimpleNamespace(queue=queue)
    app.dependency_overrides.pop(get_enqueue, None)
    app.dependency_overrides.pop(get_progress_reader, None)


def _register(client: TestClient, email: str = OWNER) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Label Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _dataset(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/datasets",
        data={"name": "Golden"},
        files={"file": ("golden.csv", CSV_BYTES, "text/csv")},
    )
    assert response.status_code == 201, response.text
    dataset = response.json()
    approved = client.post(f"/api/v1/datasets/{dataset['id']}/versions/1/approve")
    assert approved.status_code == 200, approved.text
    return dataset


def _judged_run(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> tuple[uuid.UUID, dict[int, uuid.UUID]]:
    """A completed run of three cases; the judge scored the first and the third.

    The middle case deliberately has no judge row, which is what a case skipped by
    the profile's per-run cap looks like.
    """
    dataset = _dataset(client)
    versions = cast(list[dict[str, Any]], dataset["versions"])
    version_id = uuid.UUID(str(versions[0]["id"]))
    dataset_id = uuid.UUID(str(dataset["id"]))
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == OWNER))
        assert user is not None
        run = create_run(
            session,
            owner_id=user.id,
            name="Judged run",
            settings_snapshot={"entry_point": "http_endpoint", "test_types": ["quality"]},
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            criteria_profile="rag_chatbot",
        )
        items = [
            create_run_item(session, run, row_index=1, input_text="What is GreenLit?"),
            create_run_item(session, run, row_index=2, input_text="Is it fast?"),
            create_run_item(session, run, row_index=3, input_text="Who made it?"),
        ]
        session.commit()
        for item in items:
            update_run_item(session, item, state="completed", output="an answer")
        # Row 1 is a confident pass; row 3 a confident fail with its own reason.
        add_metric_result(
            session,
            run,
            name="answer_quality",
            score=0.93,
            passed=True,
            explanation="the answer matches the reference",
            run_item_id=items[0].id,
            threshold=0.70,
            details={"confidence": 0.9, "attempts": 1},
        )
        add_metric_result(
            session,
            run,
            name="answer_quality",
            score=0.12,
            passed=False,
            explanation="the answer is about a different product",
            run_item_id=items[2].id,
            threshold=0.70,
            details={"confidence": 0.8, "attempts": 1},
        )
        add_metric_result(
            session,
            run,
            name="answer_quality",
            score=0.45,
            passed=False,
            explanation="the judge scored two of three answers (average 0.45)",
            threshold=0.70,
            details={"measured_items": 2, "unavailable_items": 1},
        )
        update_run(session, run, state="completed", verdict="REVIEW", verdict_reason="review")
        session.commit()
        mapping = {item.row_index: item.id for item in items}
        run_id = run.id
    return run_id, mapping


def _items(client: TestClient, run_id: uuid.UUID) -> dict[int, dict[str, object]]:
    response = client.get(f"/api/v1/runs/{run_id}/items")
    assert response.status_code == 200, response.text
    return {item["row_index"]: item for item in response.json()["items"]}


def test_the_judge_label_lands_on_the_case_it_scored(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id, _ = _judged_run(client, session_factory)

    items = _items(client, run_id)

    assert items[1]["judge_label"] == "pass"
    assert items[1]["judge_score"] == pytest.approx(0.93)
    assert items[1]["judge_reason"] == "the answer matches the reference"
    assert items[3]["judge_label"] == "fail"
    assert items[3]["judge_score"] == pytest.approx(0.12)


def test_a_case_without_a_judge_row_gets_nulls_and_no_fabricated_label(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id, _ = _judged_run(client, session_factory)

    skipped = _items(client, run_id)[2]

    assert skipped["judge_label"] is None
    assert skipped["judge_score"] is None
    assert skipped["judge_reason"] is None


def test_two_cases_never_swap_labels(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id, _ = _judged_run(client, session_factory)

    items = _items(client, run_id)

    # Row 1 was words about matching; row 3 was words about another product. If the
    # join lost its key, one of these would move to the other case.
    assert items[1]["judge_reason"] == "the answer matches the reference"
    assert items[3]["judge_reason"] == "the answer is about a different product"
    assert items[2]["judge_reason"] is None


def test_a_low_confidence_score_is_labelled_unsure(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id, mapping = _judged_run(client, session_factory)
    with session_factory() as session:
        row = session.scalar(
            select(MetricResultRow).where(
                MetricResultRow.run_item_id == mapping[1],
                MetricResultRow.name == "answer_quality",
            )
        )
        assert row is not None
        row.details = {"confidence": 0.2, "attempts": 1}
        session.commit()

    unsure = _items(client, run_id)[1]

    assert unsure["judge_label"] == "unsure"
    # The product calls this "the judge was unsure"; the score stays its own.
    assert unsure["judge_score"] == pytest.approx(0.93)


def test_an_uninstrumented_judge_row_exposes_no_label(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id, mapping = _judged_run(client, session_factory)
    with session_factory() as session:
        row = session.scalar(
            select(MetricResultRow).where(
                MetricResultRow.run_item_id == mapping[3],
                MetricResultRow.name == "answer_quality",
            )
        )
        assert row is not None
        row.instrumented = False
        session.commit()

    unavailable = _items(client, run_id)[3]

    assert unavailable["judge_label"] is None
    assert unavailable["judge_score"] is None


def test_the_report_csv_has_the_judge_columns_and_keeps_the_existing_order(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id, _ = _judged_run(client, session_factory)

    response = client.get(f"/api/v1/runs/{run_id}/report?format=csv")
    assert response.status_code == 200, response.text
    rows = list(csv.reader(io.StringIO(response.text)))
    header = rows[0]

    judge_columns = ["judge_label", "judge_score", "judge_reason"]
    assert [name for name in header if name not in judge_columns] == EXISTING_HEADER
    first = header.index("judge_label")
    assert header[first : first + 3] == judge_columns
    # The permission block that was last before this change is still last.
    assert header[first + 3 :] == EXISTING_HEADER[-3:]

    labelled = {int(row[0]): dict(zip(header, row, strict=True)) for row in rows[1:]}
    assert labelled[1]["judge_label"] == "pass"
    assert labelled[1]["judge_score"] == "0.93"
    assert labelled[3]["judge_label"] == "fail"
    assert labelled[2]["judge_label"] == ""
    assert labelled[2]["judge_score"] == ""
    assert labelled[2]["judge_reason"] == ""


def test_the_report_json_carries_the_judge_label_per_case(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id, _ = _judged_run(client, session_factory)

    document = client.get(f"/api/v1/runs/{run_id}/report?format=json").json()
    cases = {case["row_index"]: case for case in document["cases"]}

    assert cases[1]["judge_label"] == "pass"
    assert cases[3]["judge_label"] == "fail"
    assert cases[2]["judge_label"] is None
    # The rubric, the prompt and the raw reply never reach the document.
    assert "rubric" not in cases[1]
    assert document["cases"][0]["judge_reason"] == "the answer matches the reference"


def test_another_account_cannot_read_the_judge_label(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id, _ = _judged_run(client, session_factory)
    client.post("/api/v1/auth/logout")
    _register(client, email="someone-else@example.com")

    assert client.get(f"/api/v1/runs/{run_id}/items").status_code == 404
    assert client.get(f"/api/v1/runs/{run_id}/report?format=csv").status_code == 404
