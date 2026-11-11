"""The plain-words block reaches both surfaces, and the CSV keeps its columns (L1).

One finished run, read three ways: the run API's ``summary``, the report
document's ``summary`` and the HTML export that prints it. The test also pins the
per-case CSV header, because the summary was added to the report without adding
a column to the case table.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.runs import get_progress_reader
from app.main import app
from app.models import User, utcnow
from app.services.run_repository import (
    add_metric_result,
    create_run,
    create_run_item,
    update_run,
    update_run_item,
)
from app.services.run_service import get_enqueue

PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def runtime() -> Iterator[SimpleNamespace]:
    queue: list[uuid.UUID] = []
    app.dependency_overrides[get_enqueue] = lambda: queue.append
    app.dependency_overrides[get_progress_reader] = lambda: lambda _run_id: None
    yield SimpleNamespace(queue=queue)
    app.dependency_overrides.pop(get_enqueue, None)
    app.dependency_overrides.pop(get_progress_reader, None)


def _register(client: TestClient) -> None:
    """Register on the shared client so its cookie jar carries the session."""
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "summary@example.com", "name": "Summary Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _finished_run(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        owner = session.query(User).filter(User.email == "summary@example.com").one()
        snapshot = {
            "entry_point": "http_endpoint",
            "test_types": ["quality"],
            "url": "http://127.0.0.1:9099/ask",
            "method": "POST",
            "answer_path": "answer",
            "decision": {
                "verdict": "NO_GO",
                "score": 0.54,
                "rule": 2,
                "reason": "Weighted score 0.54 is below the REVIEW threshold 0.60.",
                "review_threshold": 0.6,
                "go_threshold": 0.8,
                "weak_metrics": [{"metric": "answer_match", "score": 0.5}],
                "suggested_fixes": ["tighten the prompt"],
                "hard_gate_failures": [],
            },
        }
        run = create_run(
            session,
            owner_id=owner.id,
            name="Summary run",
            settings_snapshot=snapshot,
            criteria_profile="plain_chatbot",
        )
        item = create_run_item(session, run, row_index=1, input_text="What is GreenLit?")
        session.commit()
        update_run_item(session, item, state="completed", output="A wrong answer")
        add_metric_result(
            session,
            run,
            name="answer_match",
            score=0.5,
            passed=False,
            explanation="the answer did not match",
            weight=0.5,
            threshold=0.6,
        )
        # Nothing the app said carried token counts: named, never scored as 0.
        add_metric_result(
            session,
            run,
            name="token_usage_present",
            score=0.0,
            passed=False,
            explanation="the app did not report token usage",
            instrumented=False,
            weight=0.2,
            threshold=0.9,
        )
        update_run(
            session,
            run,
            state="completed",
            verdict="NO_GO",
            score=0.54,
            verdict_reason="Weighted score 0.54 is below the REVIEW threshold 0.60.",
            completed_at=utcnow(),
        )
        session.commit()
        return run.id


def test_the_api_summary_and_the_report_agree(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id = _finished_run(session_factory)

    detail = client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    summary = detail.json()["summary"]
    assert summary["headline"] == (
        "GreenLit says NO-GO: the weighted score was 0.54, below the 0.60 review threshold."
    )
    assert summary["weakest_sentence"] == "Weakest measured metrics: answer match 0.50."
    assert summary["not_measured"] == ["token usage present"]
    assert "not counted as zero" in summary["not_measured_sentence"]
    assert summary["next_steps"] == ["tighten the prompt"]

    report = client.get(f"/api/v1/runs/{run_id}/report?format=json")
    assert report.status_code == 200, report.text
    assert report.json()["summary"] == summary

    html = client.get(f"/api/v1/runs/{run_id}/report?format=html")
    assert html.status_code == 200, html.text
    assert "<h2>In plain words</h2>" in html.text
    assert "GreenLit says NO-GO: the weighted score was 0.54" in html.text


def test_the_per_case_csv_columns_are_unchanged(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    run_id = _finished_run(session_factory)

    response = client.get(f"/api/v1/runs/{run_id}/report?format=csv")
    assert response.status_code == 200, response.text
    header = next(csv.reader(io.StringIO(response.text)))
    for required in (
        "row_index",
        "input",
        "actual",
        "state",
        "latency_ms",
        "judge_label",
        "judge_score",
        "judge_reason",
    ):
        assert required in header, f"{required} missing from {header}"
    # Nothing about the summary was added to the case table.
    assert not any("summary" in column for column in header)
