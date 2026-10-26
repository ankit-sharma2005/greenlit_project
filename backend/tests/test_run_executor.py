"""M6b: the run executor — worker-side execution, isolation and verdict (spec 8.1)."""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from unittest.mock import MagicMock

import pytest
from redis.exceptions import RedisError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Dataset,
    DatasetColumnMapping,
    DatasetItem,
    DatasetVersion,
    Run,
    RunState,
    User,
    utcnow,
)
from app.services.connectors import ConnectorError, Trace
from app.services.run_executor import execute_run
from app.services.run_progress import MemoryProgress, RedisProgress, RunProgress
from app.services.run_repository import (
    create_run,
    get_metric_results,
    list_run_items,
    update_run,
)

ROWS: list[dict[str, str]] = [
    {
        "question": "What is GreenLit?",
        "answer": "GreenLit tests LLM applications before launch.",
        "context": "GreenLit is a pre-launch testing tool for LLM apps.",
    },
    {
        "question": "Who approves dataset versions?",
        "answer": "An admin approves dataset versions.",
        "context": "Only admins approve dataset versions.",
    },
    {
        "question": "Where do runs execute?",
        "answer": "Runs execute in the Celery worker.",
        "context": "Runs are executed by a Celery worker, never in a request.",
    },
]


def echo_answers(rows: Sequence[dict[str, str]] = ROWS) -> dict[str, str]:
    """Perfect answers: input question -> golden answer."""
    return {row["question"]: row["answer"] for row in rows}


class FakeSender:
    """Injectable sender factory: answers/failures by input, records every call."""

    def __init__(
        self,
        answers: dict[str, str] | None = None,
        failures: dict[str, tuple[str, str]] | None = None,
        on_call: Callable[[str], None] | None = None,
        delay: float = 0.0,
    ) -> None:
        self.answers = answers or {}
        self.failures = failures or {}
        self.on_call = on_call
        self.delay = delay
        self.calls: list[str] = []
        self.snapshots: list[dict[str, object]] = []
        self._lock = threading.Lock()

    def factory(
        self, snapshot: dict[str, object], session_factory: object
    ) -> Callable[[str], Trace]:
        self.snapshots.append(dict(snapshot))

        def send(input_text: str) -> Trace:
            with self._lock:
                self.calls.append(input_text)
            if self.on_call is not None:
                self.on_call(input_text)
            if self.delay:
                time.sleep(self.delay)
            failure = self.failures.get(input_text)
            if failure is not None:
                message, code = failure
                raise ConnectorError(message, code=code)
            return Trace(
                output=self.answers.get(input_text, "ok"),
                retrieved_context="not instrumented",
                tool_calls="not instrumented",
                latency_ms=120,
                tokens_in=None,
                tokens_out=None,
                error=None,
                raw={"echo": input_text},
            )

        return send


@pytest.fixture
def owner(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        user = User(
            email=f"worker-{uuid.uuid4().hex[:8]}@example.com",
            name="Worker",
            password_hash="x",
            role="admin",
        )
        session.add(user)
        session.commit()
        return user.id


def seed_run(
    session_factory: sessionmaker[Session],
    owner_id: uuid.UUID,
    *,
    rows: list[dict[str, str]] | None = None,
    entry: str = "http_endpoint",
    settings_extra: dict[str, object] | None = None,
    approved: bool = True,
    with_dataset: bool = True,
    criteria: str = "plain_chatbot",
) -> uuid.UUID:
    """One queued run over a small dataset, with its settings snapshot."""
    rows = rows if rows is not None else ROWS
    settings: dict[str, object] = {
        "entry_point": entry,
        "url": "http://fake.test/ask",
        "body_template": '{"question": {{input}}}',
        "timeout_seconds": 7,
        "method": "POST",
    }
    settings.update(settings_extra or {})
    with session_factory() as session:
        dataset: Dataset | None = None
        version: DatasetVersion | None = None
        if with_dataset:
            dataset = Dataset(
                owner_id=owner_id,
                name=f"ds-{uuid.uuid4().hex[:10]}",
                source_filename="cases.csv",
                file_format="csv",
            )
            session.add(dataset)
            session.flush()
            session.add(
                DatasetColumnMapping(
                    dataset_id=dataset.id,
                    input_column="question",
                    output_column="answer",
                    retrieved_context_column="context",
                )
            )
            session.flush()
            version = DatasetVersion(
                dataset_id=dataset.id,
                version_no=1,
                row_count=len(rows),
                approved_at=utcnow() if approved else None,
                approved_by=owner_id if approved else None,
            )
            session.add(version)
            session.flush()
            for index, row in enumerate(rows):
                session.add(
                    DatasetItem(
                        dataset_version_id=version.id,
                        row_index=index + 1,
                        data=row,
                    )
                )
        run = create_run(
            session,
            owner_id=owner_id,
            name=f"run-{uuid.uuid4().hex[:10]}",
            settings_snapshot=settings,
            dataset_id=dataset.id if dataset else None,
            dataset_version_id=version.id if version else None,
            criteria_profile=criteria,
        )
        session.commit()
        return run.id


def run_it(
    run_id: uuid.UUID,
    session_factory: sessionmaker[Session],
    sender: FakeSender | None = None,
    *,
    sender_factory: Callable[..., Callable[[str], Trace]] | None = None,
    parallelism: int = 1,
) -> tuple[dict[str, object], MemoryProgress]:
    progress = MemoryProgress()
    report = execute_run(
        run_id,
        session_factory=session_factory,
        sender_factory=sender_factory or (sender.factory if sender else None),
        progress=progress,
        parallelism=parallelism,
    )
    return report, progress


# ---- happy path -----------------------------------------------------------


def test_run_completes_with_go_verdict_and_stored_metrics(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner)
    sender = FakeSender(answers=echo_answers())
    report, progress = run_it(run_id, session_factory, sender)

    assert report["status"] == "completed", report
    assert report["verdict"] == "GO"
    assert report["items_total"] == 3
    assert report["items_completed"] == 3
    assert report["partial"] is False

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == "completed"
        assert run.started_at is not None and run.completed_at is not None
        assert run.is_partial is False
        assert run.score is not None and run.score >= 0.8
        assert run.verdict_reason  # plain-words explanation is stored

        items = list_run_items(session, run_id)
        assert [item.state for item in items] == ["completed"] * 3
        assert items[0].output == ROWS[0]["answer"]
        assert items[0].trace is not None
        assert items[0].trace["connector"] == "http_endpoint"
        assert items[0].trace["timed_out"] is False
        assert items[0].latency_ms == 120

        metric_rows = get_metric_results(session, run_id)

    names = {row.name for row in metric_rows}
    assert names == {
        "answer_match",
        "output_nonempty",
        "latency_under_limit",
        "error_rate",
        "timeout_rate",
    }
    assert all(row.instrumented for row in metric_rows)
    assert all(row.passed for row in metric_rows)

    # The sender saw the run's saved settings (the snapshot is honoured).
    assert sender.snapshots[0]["timeout_seconds"] == 7
    assert sender.snapshots[0]["entry_point"] == "http_endpoint"

    final = progress.read(run_id)
    assert final is not None
    assert final.items_done == 3
    assert final.items_total == 3
    assert final.stage == "completed"


# ---- failure isolation ----------------------------------------------------


def test_one_failing_item_does_not_fail_the_run(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner)
    bad_input = ROWS[1]["question"]
    sender = FakeSender(
        answers=echo_answers(),
        failures={bad_input: ("your app rejected the request: check API key/auth", "auth_error")},
    )
    report, _ = run_it(run_id, session_factory, sender)

    # The run finishes; the failing item stores its error and the rest score.
    assert report["status"] == "completed", report
    assert report["items_completed"] == 2
    assert report["items_failed"] == 1
    assert report["verdict"] is not None

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None and run.state == "completed"
        items = list_run_items(session, run_id)
        failed = [item for item in items if item.state == "failed"]
        assert len(failed) == 1
        assert failed[0].input_text == bad_input
        assert failed[0].error == "your app rejected the request: check API key/auth"
        assert failed[0].output is None
        assert failed[0].trace is not None
        assert failed[0].trace["timed_out"] is False
        assert failed[0].trace["error_code"] == "auth_error"
        completed = [item for item in items if item.state == "completed"]
        assert len(completed) == 2


def test_all_items_fail_still_completes_with_no_go(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner)
    sender = FakeSender(
        answers=echo_answers(),
        failures={row["question"]: ("your app is unreachable", "connector_error") for row in ROWS},
    )
    report, _ = run_it(run_id, session_factory, sender)

    assert report["status"] == "completed"
    assert report["verdict"] == "NO_GO"  # no valid items -> NO_GO (decision rule 1)
    assert report["items_failed"] == 3
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == "completed"
        assert run.verdict == "NO_GO"
        assert run.verdict_reason


def test_timeout_item_is_flagged_and_counted(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner)
    sender = FakeSender(
        answers=echo_answers(),
        failures={
            row["question"]: ("increase the timeout or speed up the app", "timeout") for row in ROWS
        },
    )
    report, _ = run_it(run_id, session_factory, sender)

    assert report["status"] == "completed"
    with session_factory() as session:
        items = list_run_items(session, run_id)
        assert all(item.state == "failed" for item in items)
        assert all(item.trace is not None and item.trace["timed_out"] is True for item in items)
        timeout_rows = [
            row for row in get_metric_results(session, run_id) if row.name == "timeout_rate"
        ]
        assert len(timeout_rows) == 1
        assert timeout_rows[0].instrumented is True
        assert timeout_rows[0].passed is False
        assert timeout_rows[0].score == 0.0


# ---- cancel ---------------------------------------------------------------


def test_cancel_mid_run_keeps_partial_results(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner)
    first_input = ROWS[0]["question"]

    def cancel_during_first_call(input_text: str) -> None:
        if input_text != first_input:
            return
        with session_factory() as session:
            run = session.get(Run, run_id)
            assert run is not None
            update_run(session, run, state=RunState.CANCELLING)
            session.commit()

    sender = FakeSender(answers=echo_answers(), on_call=cancel_during_first_call)
    report, _ = run_it(run_id, session_factory, sender)

    assert report["status"] == "cancelled", report
    assert report["partial"] is True
    assert report["items_completed"] == 1
    assert report["items_cancelled"] == 2

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == "cancelled"
        assert run.is_partial is True
        assert run.verdict is not None  # partial results are still scored
        assert run.verdict_reason is not None
        assert "partial" in run.verdict_reason.lower()
        items = list_run_items(session, run_id)
        assert [item.state for item in items] == ["completed", "cancelled", "cancelled"]
        metrics = get_metric_results(session, run_id)
    assert metrics, "cancelled runs still store the partial metric table"


# ---- run-level failures ---------------------------------------------------


def test_skips_a_run_that_is_not_queued(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner)
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        update_run(session, run, state=RunState.RUNNING)
        session.commit()

    report, _ = run_it(run_id, session_factory, FakeSender())

    assert report["status"] == "skipped"
    assert report["state"] == "running"
    with session_factory() as session:
        assert list_run_items(session, run_id) == []


def test_missing_dataset_fails_the_run_with_a_reason(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, with_dataset=False)
    report, _ = run_it(run_id, session_factory, FakeSender())

    assert report["status"] == "failed"
    assert report["state"] == "failed"
    assert "dataset" in str(report["reason"]).lower()
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == "failed"
        assert run.verdict is None
        assert run.verdict_reason is not None
        assert "dataset" in run.verdict_reason.lower()
        assert list_run_items(session, run_id) == []


def test_unapproved_version_fails_the_run_with_a_reason(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, approved=False)
    report, _ = run_it(run_id, session_factory, FakeSender())

    assert report["status"] == "failed"
    assert "not approved" in str(report["reason"])
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None and run.state == "failed"


def test_missing_target_url_fails_with_a_friendly_reason(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, settings_extra={"url": ""})
    report, _ = run_it(run_id, session_factory, FakeSender())

    assert report["status"] == "failed"
    assert "target URL" in str(report["reason"])


def test_unknown_entry_point_reports_coming_soon(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner, entry="mcp_tools")
    report, _ = run_it(run_id, session_factory, FakeSender())

    assert report["status"] == "failed"
    assert "coming soon" in str(report["reason"])


# ---- upload_outputs -------------------------------------------------------


def test_upload_outputs_scores_the_file_without_calling_the_app(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    rows = [
        {
            "question": row["question"],
            "answer": row["answer"],
            "expected_answer": row["answer"],
        }
        for row in ROWS
    ]
    run_id = seed_run(session_factory, owner, rows=rows, entry="upload_outputs")

    def forbidden_factory(snapshot: object, session_factory_arg: object) -> Callable[[str], Trace]:
        raise AssertionError("upload_outputs runs must not build a sender")

    report, _ = run_it(run_id, session_factory, sender_factory=forbidden_factory)

    assert report["status"] == "completed", report
    assert report["verdict"] == "GO"
    with session_factory() as session:
        items = list_run_items(session, run_id)
        assert [item.state for item in items] == ["completed"] * 3
        assert items[0].output == rows[0]["answer"]
        assert items[0].trace is not None
        assert items[0].trace["connector"] == "upload_outputs"
        answer_match = [
            row for row in get_metric_results(session, run_id) if row.name == "answer_match"
        ]
        assert answer_match and answer_match[0].passed is True


# ---- progress -------------------------------------------------------------


def test_progress_fails_open_without_redis() -> None:
    client = MagicMock()
    client.set.side_effect = RedisError("redis is down")
    client.get.side_effect = RedisError("redis is down")
    reporter = RedisProgress(client)

    reporter.publish(uuid.uuid4(), RunProgress(items_total=3, stage="running"))  # no raise
    assert reporter.read(uuid.uuid4()) is None

    # Forward compatibility: unknown keys from newer workers are ignored.
    rebuilt = RunProgress.from_dict({"items_done": 2, "stage": "running", "future_key": 1})
    assert rebuilt.items_done == 2
    assert rebuilt.stage == "running"


# ---- concurrency and task wiring -----------------------------------------


def test_parallelism_two_executes_every_item(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    rows = [{"question": f"q{index}", "answer": f"a{index}"} for index in range(4)]
    run_id = seed_run(session_factory, owner, rows=rows)
    sender = FakeSender(answers=echo_answers(rows), delay=0.05)

    report, _ = run_it(run_id, session_factory, sender, parallelism=2)

    assert report["status"] == "completed"
    assert report["items_completed"] == 4
    assert sorted(sender.calls) == ["q0", "q1", "q2", "q3"]
    with session_factory() as session:
        items = list_run_items(session, run_id)
        assert all(item.state == "completed" for item in items)


def test_celery_task_registered() -> None:
    import app.tasks
    from app.celery_app import celery

    assert app.tasks.run_test is not None
    assert "app.tasks.run_test" in celery.tasks


# ---- right reason --------------------------------------------------------


def test_broken_run_gets_no_go_and_the_reason_names_the_real_engine(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """The stored verdict reason must explain itself: score, threshold, weak metrics.

    The broken demo answers wrong on every case, so the run must come out NO_GO
    (rule 2) with the weighted score and the REVIEW threshold spelled out, the
    weak metrics named, and metrics the app never reported excluded from the
    score instead of counted as zero.
    """
    run_id = seed_run(session_factory, owner, criteria="rag_chatbot")
    sender = FakeSender(answers={row["question"]: "I am not sure about that." for row in ROWS})
    report, _ = run_it(run_id, session_factory, sender)

    assert report["status"] == "completed", report
    assert report["verdict"] == "NO_GO"

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == "completed"
        reason = run.verdict_reason or ""

        # The explanation, in plain words, must be usable on its own.
        assert re.search(r"Weighted score 0\.\d\d", reason), reason
        assert "below the REVIEW threshold 0.60" in reason
        assert "Weakest metrics:" in reason
        assert "answer_match 0.00" in reason
        assert "Suggested fixes:" in reason

        # Not-instrumented metrics are excluded from the weighted score, not
        # counted as zero: with recall (0.25) and tokens (0.05) excluded the
        # score is 0.40/0.70, not the 0.26 a naive average would give.
        assert run.score is not None
        assert run.score == pytest.approx(0.40 / 0.70, abs=0.01), run.score

        metrics = {row.name: row for row in get_metric_results(session, run_id)}
        assert metrics["answer_match"].score == 0.0
        assert metrics["answer_match"].passed is False
        assert metrics["retrieval_context_recall"].instrumented is False
        assert metrics["token_usage_present"].instrumented is False
