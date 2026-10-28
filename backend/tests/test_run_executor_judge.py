"""M7: the worker judges a run's answers (spec 8.2).

The model call is injected, exactly like the app's sender: nothing here needs a
model or a network. What is checked is the wiring the spec asks for — every
answered case is judged at temperature 0, the provenance is stored on the run
and per item, and a judge that is unavailable or unsure becomes REVIEW through
rule 3 instead of failing the run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import JudgeProfile, Provider, Run, User
from app.services.judge import JUDGE_RUBRIC_VERSION, prompt_template_hash
from app.services.run_executor import execute_run
from app.services.run_progress import MemoryProgress
from app.services.run_repository import get_metric_results, list_run_items
from tests.test_run_executor import ROWS, FakeSender, echo_answers, seed_run


class FakeJudge:
    """A judge model call with a fixed reply, recording what it was asked."""

    def __init__(self, reply: str | None = None, error: Exception | None = None) -> None:
        self.reply = (
            reply
            if reply is not None
            else json.dumps({"score": 0.9, "reason": "the answer matches", "confidence": 0.9})
        )
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        model: str | None,
    ) -> str:
        self.calls.append(
            {
                "provider": provider.name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "model": model,
            }
        )
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture
def owner(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        user = User(
            email=f"judged-{uuid.uuid4().hex[:8]}@example.com",
            name="Judge Owner",
            password_hash="x",
            role="admin",
        )
        session.add(user)
        session.commit()
        return user.id


def seed_judge(
    session_factory: sessionmaker[Session], owner_id: uuid.UUID, *, model: str = "judge-model"
) -> uuid.UUID:
    """One provider plus the judge profile a run will use."""
    with session_factory() as session:
        provider = Provider(
            name=f"judge-provider-{uuid.uuid4().hex[:6]}",
            kind="openai-compatible",
            model_name=model,
            base_url="http://judge.test/v1",
        )
        session.add(provider)
        session.flush()
        profile = JudgeProfile(
            owner_id=owner_id,
            name="The judge",
            provider_id=provider.id,
            model=model,
            rubric_version=JUDGE_RUBRIC_VERSION,
            temperature=0.0,
            max_tokens=256,
            is_selected=True,
        )
        session.add(profile)
        session.commit()
        return profile.id


def run_judged(
    run_id: uuid.UUID,
    session_factory: sessionmaker[Session],
    sender: FakeSender,
    chat: FakeJudge,
) -> dict[str, Any]:
    """Execute a run with both the app's sender and the judge's model injected."""
    return execute_run(
        run_id,
        session_factory=session_factory,
        sender_factory=sender.factory,
        progress=MemoryProgress(),
        parallelism=1,
        judge_chat=chat,
    )


def judged_run(
    session_factory: sessionmaker[Session], owner_id: uuid.UUID, **kwargs: Any
) -> uuid.UUID:
    profile_id = seed_judge(session_factory, owner_id)
    settings: dict[str, object] = {"judge_profile_id": str(profile_id)}
    settings.update(kwargs.pop("settings_extra", {}))
    return seed_run(session_factory, owner_id, settings_extra=settings, **kwargs)


# ---- happy path -----------------------------------------------------------


def test_every_answered_case_is_judged_with_stored_provenance(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = judged_run(session_factory, owner)
    chat = FakeJudge()
    report = run_judged(run_id, session_factory, FakeSender(answers=echo_answers()), chat)

    assert report["status"] == "completed", report
    assert report["verdict"] == "GO"

    # Temperature 0 and the profile's own max_tokens reach the model call.
    assert len(chat.calls) == len(ROWS)
    assert {call["temperature"] for call in chat.calls} == {0.0}
    assert {call["max_tokens"] for call in chat.calls} == {256}
    assert {call["model"] for call in chat.calls} == {"judge-model"}
    # Every case is fenced as untrusted data, never as the instruction channel.
    user_message = chat.calls[0]["messages"][1]["content"]
    assert "<data>" in user_message and ROWS[0]["question"] in user_message
    assert "UNTRUSTED DATA" in chat.calls[0]["messages"][0]["content"]

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        snapshot = dict(run.settings_snapshot or {})
        provenance = snapshot["judge"]
        assert provenance["judge_model"] == "judge-model"
        assert provenance["judge_rubric_version"] == JUDGE_RUBRIC_VERSION
        assert provenance["judge_prompt_hash"] == prompt_template_hash()
        assert provenance["judge_temperature"] == 0.0
        assert provenance["judge_graded_items"] == len(ROWS)
        assert provenance["judge_unavailable_items"] == 0
        assert "judge_skipped_reason" not in snapshot

        rows = get_metric_results(session, run_id)
        items = list_run_items(session, run_id)

    run_level = [row for row in rows if row.name == "answer_quality" and row.run_item_id is None]
    assert len(run_level) == 1
    assert run_level[0].instrumented is True
    assert run_level[0].score == pytest.approx(0.9)
    assert run_level[0].details is not None
    assert run_level[0].details["rubric_version"] == JUDGE_RUBRIC_VERSION
    assert run_level[0].details["prompt_template_hash"] == prompt_template_hash()

    # One judge row per item, each pointing at the item it graded.
    per_item = [row for row in rows if row.name == "answer_quality" and row.run_item_id is not None]
    assert len(per_item) == len(items)
    assert {row.run_item_id for row in per_item} == {item.id for item in items}
    assert all(row.explanation == "the answer matches" for row in per_item)
    assert all((row.details or {})["confidence"] == 0.9 for row in per_item)


# ---- an untrustworthy judge is REVIEW, never a failure ---------------------


def test_unparseable_judge_output_forces_review(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = judged_run(session_factory, owner)
    chat = FakeJudge(reply="I think the answer is quite good.")
    report = run_judged(run_id, session_factory, FakeSender(answers=echo_answers()), chat)

    assert report["status"] == "completed", report
    assert report["verdict"] == "REVIEW"
    # One retry per item, then the item is marked unavailable (spec 8.2).
    assert len(chat.calls) == len(ROWS) * 2

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert "judge was unavailable" in (run.verdict_reason or "")
        assert (run.settings_snapshot or {})["judge"]["judge_unavailable_items"] == len(ROWS)
        rows = get_metric_results(session, run_id)

    quality = [row for row in rows if row.name == "answer_quality"]
    assert quality and all(row.instrumented is False for row in quality)


def test_a_provider_outage_never_fails_the_run(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = judged_run(session_factory, owner)
    chat = FakeJudge(error=RuntimeError("connection refused"))
    report = run_judged(run_id, session_factory, FakeSender(answers=echo_answers()), chat)

    assert report["status"] == "completed", report
    assert report["verdict"] == "REVIEW"
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == "completed"
        # The run is not failed; the outage is reported where a human can act on it.
        assert "judge was unavailable" in (run.verdict_reason or "")
        rows = [row for row in get_metric_results(session, run_id) if row.name == "answer_quality"]
    per_item = [row for row in rows if row.run_item_id is not None]
    assert per_item and all("could not score" in row.explanation for row in per_item)


def test_low_confidence_forces_review(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = judged_run(session_factory, owner)
    chat = FakeJudge(
        reply=json.dumps({"score": 0.95, "reason": "probably fine", "confidence": 0.1})
    )
    report = run_judged(run_id, session_factory, FakeSender(answers=echo_answers()), chat)

    assert report["status"] == "completed", report
    assert report["verdict"] == "REVIEW"
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert "not confident" in (run.verdict_reason or "")
        assert (run.settings_snapshot or {})["judge"]["judge_low_confidence_items"] == len(ROWS)


# ---- no judge, or a judge that cannot run ---------------------------------


def test_a_run_without_a_judge_records_that_it_was_skipped(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(session_factory, owner)
    chat = FakeJudge()
    report = run_judged(run_id, session_factory, FakeSender(answers=echo_answers()), chat)

    assert report["status"] == "completed", report
    assert report["verdict"] == "GO"
    assert chat.calls == []

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        snapshot = dict(run.settings_snapshot or {})
        assert "judge" not in snapshot
        assert "no judge profile" in snapshot["judge_skipped_reason"]
        names = {row.name for row in get_metric_results(session, run_id)}
    # answer_quality is absent rather than scored 0.
    assert "answer_quality" not in names


def test_a_deleted_judge_profile_forces_review_with_a_clear_reason(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = seed_run(
        session_factory,
        owner,
        settings_extra={"judge_profile_id": str(uuid.uuid4())},
    )
    report = run_judged(run_id, session_factory, FakeSender(answers=echo_answers()), FakeJudge())

    assert report["status"] == "completed", report
    assert report["verdict"] == "REVIEW"

    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        snapshot = dict(run.settings_snapshot or {})
        assert "no longer exists" in snapshot["judge_skipped_reason"]
        assert "judge" not in snapshot
        rows = [row for row in get_metric_results(session, run_id) if row.name == "answer_quality"]
    assert rows and all(row.instrumented is False for row in rows)
    assert "no longer exists" in rows[0].explanation


# ---- scope of the judging -------------------------------------------------


def test_items_that_failed_before_answering_are_not_judged(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    run_id = judged_run(session_factory, owner)
    broken = ROWS[1]["question"]
    sender = FakeSender(answers=echo_answers(), failures={broken: ("boom", "server_error")})
    chat = FakeJudge()
    report = run_judged(run_id, session_factory, sender, chat)

    assert report["status"] == "completed", report
    # Two answered cases were judged; the failed one has nothing to grade.
    assert len(chat.calls) == len(ROWS) - 1

    with session_factory() as session:
        items = list_run_items(session, run_id)
        failed = [item for item in items if item.state == "failed"]
        assert len(failed) == 1
        per_item = [
            row
            for row in get_metric_results(session, run_id)
            if row.name == "answer_quality" and row.run_item_id is not None
        ]
    assert failed[0].id not in {row.run_item_id for row in per_item}


def test_judge_metadata_is_absent_for_an_upload_outputs_run(
    session_factory: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """Uploaded answers are still judged; the provenance is the same shape."""
    profile_id = seed_judge(session_factory, owner)
    csv = "id,input,output\n1,What is GreenLit?,GreenLit tests LLM apps.\n"
    run_id = seed_run(
        session_factory,
        owner,
        entry="upload_outputs",
        settings_extra={"judge_profile_id": str(profile_id), "csv": csv},
        rows=[ROWS[0]],
    )
    chat = FakeJudge()
    report = execute_run(
        run_id,
        session_factory=session_factory,
        progress=MemoryProgress(),
        parallelism=1,
        judge_chat=chat,
    )

    assert report["status"] == "completed", report
    assert len(chat.calls) == 1
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert isinstance(run.settings_snapshot, Mapping)
        assert run.settings_snapshot["judge"]["judge_graded_items"] == 1
