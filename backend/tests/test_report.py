"""Report export tests (spec 8.5).

A report is the run result leaving the product, so these tests assert the three
things that can go wrong when that happens: a secret leaking into the file, a
case's text being interpreted as HTML, and a case's text being executed as a
spreadsheet formula. They also check each format carries what the spec lists —
the dataset, the connector, the metrics with "not instrumented", the failed
cases, the Safety section and the judge provenance.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.runs import get_progress_reader
from app.main import app
from app.models import Provider, User, utcnow
from app.services.run_repository import (
    add_metric_result,
    create_run,
    create_run_item,
    list_run_items,
    update_run,
    update_run_item,
)
from app.services.run_service import get_enqueue

PASSWORD = "correct horse battery staple"
SECRET_HEADER = "Bearer super-secret-token-7f3a"
SECRET_KEY = "sk-live-should-never-be-exported"

CSV_BYTES = (
    b"question,answer,context\n"
    b"What is GreenLit?,GreenLit tests LLM apps.,GreenLit tests LLM applications.\n"
    b"Is it fast?,Yes it is fast.,Runs are quick.\n"
)


@pytest.fixture(autouse=True)
def runtime() -> Iterator[SimpleNamespace]:
    """Queue and progress seams so no test needs Redis or a broker."""
    queue: list[uuid.UUID] = []
    app.dependency_overrides[get_enqueue] = lambda: queue.append
    app.dependency_overrides[get_progress_reader] = lambda: None
    yield SimpleNamespace(queue=queue)
    app.dependency_overrides.pop(get_enqueue, None)
    app.dependency_overrides.pop(get_progress_reader, None)


def _register(client: TestClient, email: str = "report@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Report Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _user_id(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == "report@example.com"))
        assert user is not None
        return user.id


def _upload_and_approve(client: TestClient, name: str = "Golden") -> dict[str, object]:
    response = client.post(
        "/api/v1/datasets",
        data={"name": name},
        files={"file": ("golden.csv", CSV_BYTES, "text/csv")},
    )
    assert response.status_code == 201, response.text
    dataset = response.json()
    approved = client.post(f"/api/v1/datasets/{dataset['id']}/versions/1/approve")
    assert approved.status_code == 200, approved.text
    return dataset


def _finished_run(
    session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    *,
    provider_id: uuid.UUID | None = None,
    bad_output: str = "A wrong answer",
) -> uuid.UUID:
    """A completed run with two cases, metrics, safety, judge and a secret header."""
    owner = _user_id(session_factory)
    snapshot: dict[str, object] = {
        "entry_point": "http_endpoint",
        "test_types": ["quality", "safety"],
        "dataset_version_id": str(dataset["versions"][0]["id"]),  # type: ignore[index]
        "timeout_seconds": 30,
        "url": "http://127.0.0.1:9099/ask",
        "method": "POST",
        "headers": {"Authorization": SECRET_HEADER, "X-Trace": "1"},
        "body_template": '{"question": {{input}}}',
        "answer_path": "answer",
        "allow_private_targets": True,
        "judge": {
            "judge_model": "gpt-4o-mini",
            "judge_provider_name": "OpenAI",
            "judge_profile_name": "Default judge",
            "judge_rubric_version": "1.0",
            "judge_prompt_hash": "abc123",
            "judge_temperature": 0.0,
            "judge_max_tokens": 512,
            "judge_graded_items": 2,
            "judge_unavailable_items": 0,
            "judge_low_confidence_items": 0,
        },
    }
    if provider_id is not None:
        snapshot["entry_point"] = "prompt_app"
        snapshot["provider_id"] = str(provider_id)
        snapshot["model"] = "llama3:8b"

    with session_factory() as session:
        run = create_run(
            session,
            owner_id=owner,
            name="Report run",
            settings_snapshot=snapshot,
            dataset_id=uuid.UUID(str(dataset["id"])),
            dataset_version_id=uuid.UUID(str(dataset["versions"][0]["id"])),  # type: ignore[index]
            criteria_profile="rag_chatbot",
        )
        good = create_run_item(session, run, row_index=1, input_text="What is GreenLit?")
        bad = create_run_item(session, run, row_index=2, input_text="Is it fast?")
        session.commit()
        update_run_item(session, good, state="completed", output="GreenLit tests LLM apps.")
        update_run_item(session, bad, state="failed", output=bad_output, error="answer mismatch")
        add_metric_result(
            session,
            run,
            name="answer_match",
            score=0.5,
            passed=False,
            explanation="one of two answers matched",
            weight=0.30,
            threshold=0.60,
        )
        add_metric_result(
            session,
            run,
            name="retrieval_context_recall",
            score=0.0,
            passed=False,
            explanation="no retrieved context was reported",
            instrumented=False,
            weight=0.25,
            threshold=0.60,
        )
        add_metric_result(
            session,
            run,
            name="attack_resisted",
            score=0.98,
            passed=False,
            explanation="42 of 43 probes were resisted",
            weight=0.20,
            threshold=0.95,
            hard_gate=True,
            details={
                "attacks": 44,
                "resisted": 42,
                "probed": 43,
                "set_version": "1.0",
                "critical_failures": ["sl-01"],
                "leaked_marker_cases": ["sl-01"],
            },
        )
        add_metric_result(
            session,
            run,
            name="over_refusal",
            score=1.0,
            passed=True,
            explanation="no harmless request was refused",
            weight=0.05,
            threshold=0.90,
            details={"prompts": 26, "refused": 0, "over_refusal_share": 0.0, "set_version": "1.0"},
        )
        update_run(
            session,
            run,
            state="completed",
            verdict="NO_GO",
            score=0.42,
            verdict_reason="Hard gate failed: attack_resisted. Weighted score 0.42.",
            started_at=utcnow(),
            completed_at=utcnow(),
        )
        session.commit()
        return run.id


def test_html_report_is_self_contained_and_names_the_verdict(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = _finished_run(session_factory, dataset)

    response = client.get(f"/api/v1/runs/{run_id}/report?format=html")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"]

    body = response.text
    # Self-contained: inline CSS, no external requests at all.
    assert "<style>" in body
    assert "<link" not in body
    assert 'src="http' not in body
    assert "@import" not in body

    # Everything the spec lists for the report.
    assert "NO_GO" in body
    assert "0.42" in body
    assert "Hard gate failed" in body
    assert "Golden" in body
    assert "version 1" in body
    assert "text/plain" not in body
    assert "answer match" in body
    assert "not instrumented" in body
    assert "Is it fast?" in body
    assert "A wrong answer" in body
    assert "answer mismatch" in body
    assert "Attacks resisted" in body
    assert "42 of 44" in body
    assert "gpt-4o-mini" in body
    assert "Judge model" in body
    assert "Rubric version" in body


def test_json_report_is_the_full_result(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = _finished_run(session_factory, dataset)

    response = client.get(f"/api/v1/runs/{run_id}/report?format=json")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")

    document = json.loads(response.text)
    assert document["project"] == "Default project"
    assert document["run"]["id"] == str(run_id)
    assert document["verdict"]["verdict"] == "NO_GO"
    assert document["verdict"]["score"] == 0.42
    assert document["dataset"]["name"] == "Golden"
    assert document["dataset"]["version"] == 1
    assert document["dataset"]["content_hash"]
    assert document["target"]["connector"] == "http_endpoint"
    assert document["target"]["endpoint"] == "http://127.0.0.1:9099/ask"

    metrics = {metric["name"]: metric for metric in document["metrics"]}
    assert metrics["retrieval_context_recall"]["instrumented"] is False
    assert metrics["retrieval_context_recall"]["state"] == "not instrumented"
    assert metrics["attack_resisted"]["hard_gate"] is True

    assert document["safety"]["attacks_tried"] == 44
    assert document["safety"]["attacks_resisted"] == 42
    assert document["safety"]["critical_failures"] == ["sl-01"]
    assert document["safety"]["over_refusal_share"] == 0.0

    assert document["judge"]["model"] == "gpt-4o-mini"
    assert document["judge"]["rubric_version"] == "1.0"

    # The cases carry the golden answer from the approved dataset version.
    assert [case["row_index"] for case in document["cases"]] == [1, 2]
    assert document["cases"][0]["expected"] == "GreenLit tests LLM apps."
    assert [case["input"] for case in document["failed_cases"]] == ["Is it fast?"]
    assert document["failed_cases"][0]["reason"] == "answer mismatch"


def test_csv_report_is_case_level(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = _finished_run(session_factory, dataset)

    response = client.get(f"/api/v1/runs/{run_id}/report?format=csv")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "greenlit-run-" in response.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:5] == ["row_index", "input", "expected", "actual", "state"]
    # Failure detail: what happened at the target, next to the case.
    assert rows[0][9:13] == ["error_kind", "http_status", "target", "error_snippet"]
    assert len(rows) == 3  # header + two cases
    assert rows[1][1] == "What is GreenLit?"
    assert rows[1][2] == "GreenLit tests LLM apps."
    assert rows[2][4] == "failed"
    assert rows[2][8] == "answer mismatch"
    assert rows[2][13] == "NO_GO"
    assert rows[2][14] == "0.42"


def test_report_never_contains_secrets(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Header values and provider keys must not reach any export."""
    _register(client)
    dataset = _upload_and_approve(client)
    with session_factory() as session:
        provider = Provider(
            name="Secret provider",
            kind="openai-compatible",
            model_name="llama3",
            base_url="http://127.0.0.1:11434/v1",
            api_key_encrypted=SECRET_KEY,
        )
        session.add(provider)
        session.commit()
        provider_id = provider.id

    run_id = _finished_run(session_factory, dataset, provider_id=provider_id)

    for fmt in ("html", "json", "csv"):
        response = client.get(f"/api/v1/runs/{run_id}/report?format={fmt}")
        assert response.status_code == 200, response.text
        body = response.text
        assert SECRET_HEADER not in body
        assert "super-secret-token" not in body
        assert SECRET_KEY not in body
        # The header *name* is fine and useful; only its value is secret.
        assert "Authorization" in body or fmt == "csv"

    document = json.loads(client.get(f"/api/v1/runs/{run_id}/report?format=json").text)
    assert document["settings"]["headers"] == {
        "Authorization": "[redacted]",
        "X-Trace": "[redacted]",
    }
    assert document["target"]["provider"] == "Secret provider"
    assert document["target"]["model"] == "llama3:8b"


def test_html_escapes_case_text(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = _finished_run(
        session_factory, dataset, bad_output='<script>alert("x")</script> & <b>bold</b>'
    )

    body = client.get(f"/api/v1/runs/{run_id}/report?format=html").text
    assert "<script>alert" not in body
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in body
    assert "&amp; &lt;b&gt;bold&lt;/b&gt;" in body


def test_csv_prevents_formula_injection(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = _finished_run(
        session_factory,
        dataset,
        bad_output='=HYPERLINK("http://evil.example","click")',
    )

    rows = list(
        csv.reader(io.StringIO(client.get(f"/api/v1/runs/{run_id}/report?format=csv").text))
    )
    actual = rows[2][3]
    assert actual.startswith("'=")
    assert actual == '\'=HYPERLINK("http://evil.example","click")'


def test_report_is_owner_scoped(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = _finished_run(session_factory, dataset)

    client.post("/api/v1/auth/logout")
    _register(client, email="intruder@example.com")
    for fmt in ("html", "json", "csv"):
        assert client.get(f"/api/v1/runs/{run_id}/report?format={fmt}").status_code == 404


def test_report_rejects_an_unknown_format(client: TestClient) -> None:
    _register(client)
    response = client.get(f"/api/v1/runs/{uuid.uuid4()}/report?format=pdf")
    assert response.status_code == 422


def test_report_carries_the_operations_block(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Latency, error rate and token totals travel with the export."""
    _register(client)
    dataset = _upload_and_approve(client)
    run_id = _finished_run(session_factory, dataset)

    # Give the two cases the numbers a real connector would report.
    with session_factory() as session:
        items = list_run_items(session, run_id)
        by_row = {item.row_index: item for item in items}
        update_run_item(
            session,
            by_row[1],
            latency_ms=200,
            tokens_in=1000,
            tokens_out=500,
        )
        update_run_item(
            session,
            by_row[2],
            latency_ms=400,
            tokens_in=500,
            tokens_out=100,
        )
        session.commit()

    document = json.loads(client.get(f"/api/v1/runs/{run_id}/report?format=json").text)
    operations = document["operations"]
    assert operations["items_total"] == 2
    assert operations["items_attempted"] == 2
    assert operations["latency_p50_ms"] == 300.0
    assert operations["latency_p95_ms"] == pytest.approx(390.0)
    assert operations["error_rate"] == 0.5
    assert operations["tokens_in_total"] == 1500
    assert operations["tokens_out_total"] == 600
    # No prices are set on this run's provider, so no cost is invented.
    assert operations["cost_configured"] is False
    assert operations["cost_estimate"] is None

    body = client.get(f"/api/v1/runs/{run_id}/report?format=html").text
    assert "Operations" in body
    assert "p50 latency" in body
    assert "p95 latency" in body
    assert "not configured" in body

    rows = list(
        csv.reader(io.StringIO(client.get(f"/api/v1/runs/{run_id}/report?format=csv").text))
    )
    header = rows[0]
    for column in (
        "latency_p50_ms",
        "latency_p95_ms",
        "error_rate",
        "timeout_rate",
        "tokens_in_total",
        "tokens_out_total",
        "cost_estimate",
    ):
        assert column in header
