"""Safety set selection (spec 8.3): catalogue, validation, probes and the API.

The built-in sets are fixed, but a run may choose which of them to send. These
tests pin the three things that make that safe to offer:

* the catalogue's counts come from the loaded sets, so they cannot drift;
* a choice is validated when the run is created (unknown or empty is a 422);
* the runner sends exactly the selected prompts and reports a set that was not
  selected as *not instrumented*, never as a green pass.
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
from app.models import Provider, Run, User
from app.safety.metrics import ATTACK_RESISTED, OVER_REFUSAL
from app.safety.runner import NO_ATTACK_SET_REASON, NO_SAFE_PROMPT_REASON, probe_safety
from app.safety.sets import (
    SAFE_PROMPTS_SET_ID,
    SafetySetError,
    catalogue_payload,
    default_safety_set_ids,
    load_attack_set,
    load_safe_prompt_set,
    resolve_safety_sets,
    safety_catalogue,
)
from app.services.connectors import Trace
from app.services.generation import get_chat_fn
from app.services.run_progress import RunProgress
from app.services.run_service import get_enqueue

PASSWORD = "correct horse battery staple"
CSV_BYTES = (
    b"question,answer\nWhat is GreenLit?,GreenLit tests LLM apps.\nIs it fast?,Yes it is fast.\n"
)
CANARY = "CANARY-7F3A"
REFUSAL = "I can't help with that request."


def _trace(output: str) -> Trace:
    return Trace(
        output=output,
        retrieved_context="not instrumented",
        tool_calls="not instrumented",
        latency_ms=1,
        tokens_in=None,
        tokens_out=None,
        error=None,
        raw={"content": output},
    )


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #


def test_catalogue_lists_every_built_in_set_with_real_counts() -> None:
    """One set per attack category plus the harmless requests."""
    sets = {item.id: item for item in safety_catalogue()}

    assert list(sets) == [
        "direct_injection",
        "indirect_injection",
        "system_prompt_leak",
        "jailbreak",
        "disallowed_content",
        SAFE_PROMPTS_SET_ID,
    ]
    assert sets["direct_injection"].name == "Prompt injection"
    assert sets["indirect_injection"].name == "Hidden instruction extraction"
    assert sets["system_prompt_leak"].name == "System prompt leakage"
    assert sets["jailbreak"].name == "Jailbreak and role-play"
    assert sets["disallowed_content"].name == "Harmful request handling"
    assert sets[SAFE_PROMPTS_SET_ID].kind == "safe_prompts"


def test_attack_set_counts_add_up_to_the_loaded_attack_set() -> None:
    """The numbers the UI shows are the numbers a run would send."""
    attack_set = load_attack_set()
    attack_sets = [item for item in safety_catalogue() if item.kind == "attacks"]

    assert sum(item.case_count for item in attack_sets) == len(attack_set.cases)
    assert [item.case_count for item in attack_sets] == [10, 8, 8, 10, 8]
    # Only the leaking categories act as a hard gate.
    assert [item.critical_count for item in attack_sets] == [0, 0, 8, 0, 8]
    harmless = next(item for item in safety_catalogue() if item.kind == "safe_prompts")
    assert harmless.case_count == len(load_safe_prompt_set().prompts) == 26


def test_every_set_has_a_description_and_a_version_in_the_payload() -> None:
    payload = catalogue_payload()
    assert payload["version"] == load_attack_set().version
    assert payload["safe_prompt_version"] == load_safe_prompt_set().version
    for entry in payload["sets"]:
        assert entry["description"].strip()
        assert entry["case_count"] > 0


def test_payload_summarises_the_sets_and_names_the_canary_rule() -> None:
    payload = catalogue_payload()
    summary = payload["summary"]
    assert summary == {
        "attack_count": 44,
        "safe_prompt_count": 26,
        "category_count": 5,
        "critical_count": 16,
    }
    assert payload["marker"] == CANARY
    assert "synthetic test marker" in payload["marker_note"]
    assert "hard NO-GO" in payload["canary_rule"]
    # The leaking categories carry the hard gate, the others do not.
    severity = {entry["id"]: entry["severity"] for entry in payload["sets"]}
    assert severity["system_prompt_leak"] == "critical"
    assert severity["disallowed_content"] == "critical"
    assert severity["direct_injection"] == "standard"
    assert severity[SAFE_PROMPTS_SET_ID] == "standard"


def test_payload_lists_every_item_with_its_expected_behaviour() -> None:
    payload = catalogue_payload()
    items = payload["items"]
    attack_set = load_attack_set()
    assert len(items) == len(attack_set.cases) == 44
    by_id = {item["id"]: item for item in items}
    # A canary case: the app must not repeat the marker.
    assert "planted marker" in by_id["di-01"]["expected"]
    assert by_id["di-01"]["severity"] == "standard"
    # A disallowed-content case: the app must refuse.
    disallowed = next(case for case in attack_set.cases if case.category == "disallowed_content")
    assert "refuse" in by_id[disallowed.id]["expected"]
    assert by_id[disallowed.id]["severity"] == "critical"
    for item in items:
        assert item["prompt"].strip()
        assert item["category"] in {entry["id"] for entry in payload["sets"]}


def test_default_selection_is_every_set() -> None:
    assert default_safety_set_ids() == tuple(item.id for item in safety_catalogue())
    selection = resolve_safety_sets(None)
    assert selection.ids == default_safety_set_ids()
    assert selection.include_safe_prompts is True
    assert len(selection.attack_categories) == 5


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_one_set_can_be_selected_alone() -> None:
    selection = resolve_safety_sets(["jailbreak"])
    assert selection.ids == ("jailbreak",)
    assert selection.attack_categories == ("jailbreak",)
    assert selection.include_safe_prompts is False


def test_multiple_sets_keep_catalogue_order_and_drop_duplicates() -> None:
    selection = resolve_safety_sets(
        ["disallowed_content", "direct_injection", "disallowed_content"]
    )
    assert selection.ids == ("direct_injection", "disallowed_content")
    assert selection.include_safe_prompts is False


def test_an_empty_selection_is_rejected_rather_than_probing_nothing() -> None:
    with pytest.raises(SafetySetError) as caught:
        resolve_safety_sets([])
    assert "at least one safety set" in caught.value.message


def test_an_unknown_set_is_rejected_and_names_the_options() -> None:
    with pytest.raises(SafetySetError) as caught:
        resolve_safety_sets(["sql_injection"])
    message = caught.value.message
    assert "Unknown safety set 'sql_injection'" in message
    assert "direct_injection" in message


def test_a_blank_set_id_is_rejected() -> None:
    with pytest.raises(SafetySetError):
        resolve_safety_sets(["  "])


# --------------------------------------------------------------------------- #
# The runner sends only what was selected
# --------------------------------------------------------------------------- #


def test_runner_sends_only_the_selected_category() -> None:
    sent: list[str] = []

    def sender(prompt: str) -> Trace:
        sent.append(prompt)
        return _trace("A normal answer.")

    attacks = load_attack_set()
    metrics = probe_safety(sender, selection=resolve_safety_sets(["jailbreak"]), workers=1)

    expected = {case.prompt for case in attacks.cases if case.category == "jailbreak"}
    assert set(sent) == expected
    # Ten jailbreak cases and no harmless requests, which were not selected.
    assert len(sent) == len(expected) == 10
    assert metrics[ATTACK_RESISTED].details["attacks"] == 10
    assert metrics[ATTACK_RESISTED].details["selected_sets"] == ["jailbreak"]
    assert metrics[OVER_REFUSAL].instrumented is False
    assert NO_SAFE_PROMPT_REASON in metrics[OVER_REFUSAL].explanation


def test_runner_with_only_harmless_requests_reports_attacks_as_unmeasured() -> None:
    sent: list[str] = []

    def sender(prompt: str) -> Trace:
        sent.append(prompt)
        return _trace("Here is a helpful answer.")

    metrics = probe_safety(sender, selection=resolve_safety_sets([SAFE_PROMPTS_SET_ID]), workers=1)

    assert len(sent) == 26
    assert metrics[ATTACK_RESISTED].instrumented is False
    assert NO_ATTACK_SET_REASON in metrics[ATTACK_RESISTED].explanation
    assert metrics[OVER_REFUSAL].instrumented is True
    assert metrics[OVER_REFUSAL].passed is True


def test_leaking_the_canary_fails_the_selected_attacks_and_the_critical_gate() -> None:
    metrics = probe_safety(
        lambda prompt: _trace(f"Sure: {CANARY}"),
        selection=resolve_safety_sets(["direct_injection", "system_prompt_leak"]),
        workers=1,
    )

    attacks = metrics[ATTACK_RESISTED]
    assert attacks.score == 0.0
    # A marker in the system-prompt-leak set is critical, so the gate fails.
    assert attacks.passed is False
    assert len(attacks.details["critical_failures"]) == 8
    assert attacks.details["leaked_marker_cases"]


def test_a_missing_refusal_for_disallowed_content_is_a_critical_failure() -> None:
    def sender(prompt: str) -> Trace:
        # The harmless requests get an answer, the disallowed ones get an answer
        # too — which is exactly the failure this set exists to catch.
        return _trace("Sure, here is a generic answer.")

    metrics = probe_safety(sender, selection=resolve_safety_sets(["disallowed_content"]))
    attacks = metrics[ATTACK_RESISTED]
    assert attacks.score == 0.0
    assert attacks.passed is False
    assert len(attacks.details["critical_failures"]) == 8


def test_refusing_disallowed_content_and_answering_the_rest_passes() -> None:
    disallowed = [case for case in load_attack_set().cases if case.category == "disallowed_content"]
    attack_prompts = {case.prompt: case for case in disallowed}

    def sender(prompt: str) -> Trace:
        return _trace(REFUSAL if prompt in attack_prompts else "Here is a helpful answer.")

    metrics = probe_safety(
        sender,
        selection=resolve_safety_sets(["disallowed_content", SAFE_PROMPTS_SET_ID]),
    )
    assert metrics[ATTACK_RESISTED].score == 1.0
    assert metrics[ATTACK_RESISTED].passed is True
    assert metrics[OVER_REFUSAL].score == 1.0


def test_over_refusal_names_the_harmless_requests_that_were_refused() -> None:
    metrics = probe_safety(
        lambda prompt: _trace(REFUSAL),
        selection=resolve_safety_sets([SAFE_PROMPTS_SET_ID]),
    )
    over = metrics[OVER_REFUSAL]
    assert over.score == 0.0
    assert over.passed is False
    assert over.details["refused"] == 26


def test_per_set_findings_name_the_selected_sets_only() -> None:
    metrics = probe_safety(
        lambda prompt: _trace("A safe answer."),
        selection=resolve_safety_sets(["direct_injection", "jailbreak"]),
    )
    findings = metrics[ATTACK_RESISTED].details["sets"]
    assert [entry["id"] for entry in findings] == ["direct_injection", "jailbreak"]
    assert [entry["cases"] for entry in findings] == [10, 10]
    assert all(entry["failed"] == [] for entry in findings)


# --------------------------------------------------------------------------- #
# API: the catalogue and the run's stored selection
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def runtime() -> Iterator[SimpleNamespace]:
    """Queue, progress and generation seams so no test needs Redis or a model."""
    queue: list[uuid.UUID] = []
    progress: dict[uuid.UUID, RunProgress] = {}

    def generate(
        provider: Provider, messages: list[dict[str, str]], temperature: float, limit: int
    ) -> str:
        return (
            '[{"question": "What is GreenLit?", '
            '"answer": "GreenLit tests LLM apps.", "context": null}]'
        )

    app.dependency_overrides[get_enqueue] = lambda: queue.append
    app.dependency_overrides[get_progress_reader] = lambda: progress.get
    app.dependency_overrides[get_chat_fn] = lambda: generate
    yield SimpleNamespace(queue=queue, progress=progress)
    app.dependency_overrides.pop(get_enqueue, None)
    app.dependency_overrides.pop(get_progress_reader, None)
    app.dependency_overrides.pop(get_chat_fn, None)


def _register(client: TestClient, email: str = "safety-sets@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Safety Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _dataset(client: TestClient) -> dict[str, object]:
    created = client.post(
        "/api/v1/datasets",
        data={"name": "Safety sets golden"},
        files={"file": ("golden.csv", CSV_BYTES, "text/csv")},
    )
    assert created.status_code == 201, created.text
    dataset = created.json()
    approved = client.post(f"/api/v1/datasets/{dataset['id']}/versions/1/approve")
    assert approved.status_code == 200, approved.text
    return dataset


def _body(dataset: dict[str, object], **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "entry_point": "http_endpoint",
        "target": "http://127.0.0.1:9099/ask",
        "dataset_id": dataset["id"],
        "dataset_version_id": dataset["versions"][0]["id"],  # type: ignore[index]
        "body_template": '{"question": {{input}}}',
        "answer_path": "answer",
        "allow_private_targets": True,
    }
    body.update(extra)
    return body


def test_safety_sets_require_a_session(client: TestClient) -> None:
    response = client.get("/api/v1/safety/sets")
    assert response.status_code == 401


def test_safety_sets_endpoint_lists_the_catalogue(client: TestClient) -> None:
    _register(client)
    response = client.get("/api/v1/safety/sets")
    assert response.status_code == 200, response.text
    payload = response.json()
    ids = [entry["id"] for entry in payload["sets"]]
    assert ids == list(default_safety_set_ids())
    for entry in payload["sets"]:
        assert entry["description"]
        assert entry["case_count"] > 0


def test_start_stores_the_selected_safety_sets(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _dataset(client)
    response = client.post(
        "/api/v1/runs",
        json=_body(dataset, safety_sets=["direct_injection", "harmless_requests"]),
    )
    assert response.status_code == 202, response.text

    with session_factory() as session:
        run = session.get(Run, uuid.UUID(response.json()["id"]))
        assert run is not None
        assert run.settings_snapshot["safety_sets"] == [
            "direct_injection",
            "harmless_requests",
        ]


def test_start_defaults_to_every_set_when_none_are_named(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _dataset(client)
    response = client.post("/api/v1/runs", json=_body(dataset))
    assert response.status_code == 202, response.text

    with session_factory() as session:
        run = session.get(Run, uuid.UUID(response.json()["id"]))
        assert run is not None
        assert run.settings_snapshot["safety_sets"] == list(default_safety_set_ids())


def test_start_rejects_an_unknown_safety_set(client: TestClient) -> None:
    _register(client)
    dataset = _dataset(client)
    response = client.post("/api/v1/runs", json=_body(dataset, safety_sets=["nope"]))
    assert response.status_code == 422
    # The run never exists, so nothing half-valid is left behind.
    assert "Unknown safety set 'nope'" in response.json()["error"]["message"]


def test_start_rejects_an_empty_selection_when_safety_is_on(client: TestClient) -> None:
    _register(client)
    dataset = _dataset(client)
    response = client.post("/api/v1/runs", json=_body(dataset, safety_sets=[]))
    assert response.status_code == 422
    assert "at least one safety set" in response.json()["error"]["message"]


def test_start_ignores_safety_sets_when_safety_is_off(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client)
    dataset = _dataset(client)
    response = client.post(
        "/api/v1/runs",
        json=_body(dataset, test_types=["quality"], safety_sets=[]),
    )
    assert response.status_code == 202, response.text

    with session_factory() as session:
        run = session.get(Run, uuid.UUID(response.json()["id"]))
        assert run is not None
        assert "safety_sets" not in run.settings_snapshot


def test_the_owner_is_the_only_user_who_sees_their_run(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """A selection is stored per run, so another account must not read it back."""
    _register(client)
    dataset = _dataset(client)
    started = client.post("/api/v1/runs", json=_body(dataset, safety_sets=["jailbreak"]))
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]

    with session_factory() as session:
        owner = session.scalar(select(User).where(User.email == "safety-sets@example.com"))
        assert owner is not None
        run = session.get(Run, uuid.UUID(run_id))
        assert run is not None and run.owner_id == owner.id
