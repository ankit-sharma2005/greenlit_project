"""M7: judge profiles — persistence, selection and the self-grading warning.

The judge itself is covered by ``test_judge``; this file covers the saved
configuration around it: choosing a provider and model, making one profile the
default, and warning when the judge would grade its own model.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import JudgeProfile, Provider, User
from app.services.judge import JUDGE_RUBRIC_VERSION, JUDGE_TEMPERATURE
from app.services.judge_profiles import (
    JudgeProfileError,
    create_judge_profile,
    effective_model,
    judge_warnings,
    list_judge_profiles,
    select_judge_profile,
    selected_judge_profile,
)
from app.services.run_repository import create_run
from app.services.run_service import RunServiceError, resolve_judge_profile

PASSWORD = "correct horse battery staple"


def _user(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        user = User(
            email=f"judge-{uuid.uuid4().hex[:8]}@example.com",
            name="Judge Owner",
            password_hash="x",
            role="admin",
        )
        session.add(user)
        session.commit()
        return user.id


def _provider(session_factory: sessionmaker[Session], model: str = "gpt-4o-mini") -> uuid.UUID:
    with session_factory() as session:
        provider = Provider(
            name=f"provider-{uuid.uuid4().hex[:8]}",
            kind="openai-compatible",
            model_name=model,
            base_url="http://fake.test/v1",
        )
        session.add(provider)
        session.commit()
        return provider.id


# ---- repository ------------------------------------------------------------


def test_first_profile_is_selected_and_freezes_temperature(
    session_factory: sessionmaker[Session],
) -> None:
    owner = _user(session_factory)
    provider_id = _provider(session_factory)

    with session_factory() as session:
        profile = create_judge_profile(
            session,
            owner_id=owner,
            name="Local judge",
            provider_id=provider_id,
        )
        session.commit()

        assert profile.is_selected is True
        assert profile.temperature == JUDGE_TEMPERATURE == 0.0
        assert profile.rubric_version == JUDGE_RUBRIC_VERSION
        # No model given, so the provider's model is the judge's model.
        assert profile.model == "gpt-4o-mini"

        second = create_judge_profile(
            session, owner_id=owner, name="Stricter judge", provider_id=provider_id, model="gpt-4o"
        )
        session.commit()
        # Only the first one is selected automatically.
        assert second.is_selected is False
        assert selected_judge_profile(session, owner) is not None
        assert selected_judge_profile(session, owner).name == "Local judge"  # type: ignore[union-attr]


def test_select_moves_the_default_to_the_chosen_profile(
    session_factory: sessionmaker[Session],
) -> None:
    owner = _user(session_factory)
    provider_id = _provider(session_factory)

    with session_factory() as session:
        first = create_judge_profile(session, owner_id=owner, name="A", provider_id=provider_id)
        second = create_judge_profile(session, owner_id=owner, name="B", provider_id=provider_id)
        session.commit()

        select_judge_profile(session, second)
        session.commit()

        profiles = list_judge_profiles(session, owner)
        assert [profile.is_selected for profile in profiles] == [False, True]
        selected = selected_judge_profile(session, owner)
        assert selected is not None and selected.id == second.id
        assert selected.id != first.id


def test_duplicate_name_is_rejected_case_insensitively(
    session_factory: sessionmaker[Session],
) -> None:
    owner = _user(session_factory)

    with session_factory() as session:
        create_judge_profile(session, owner_id=owner, name="Strict judge", provider_id=None)
        session.commit()

        with pytest.raises(JudgeProfileError) as caught:
            create_judge_profile(session, owner_id=owner, name="strict JUDGE", provider_id=None)
        assert caught.value.status == 409
        assert "already exists" in caught.value.message


def test_unknown_provider_is_reported_not_silently_dropped(
    session_factory: sessionmaker[Session],
) -> None:
    owner = _user(session_factory)

    with session_factory() as session:
        with pytest.raises(JudgeProfileError) as caught:
            create_judge_profile(session, owner_id=owner, name="Ghost", provider_id=uuid.uuid4())
        assert caught.value.status == 404
        assert "Settings > Providers" in caught.value.message
        # Nothing was half-created by the failed call.
        assert list_judge_profiles(session, owner) == []


def test_self_grading_warning_names_the_matching_provider(
    session_factory: sessionmaker[Session],
) -> None:
    # Providers are global in this design, so no owner is needed to ask the question.
    app_provider = _provider(session_factory, model="llama-3.1-8b")

    with session_factory() as session:
        # The judge grading the app's own model is what the spec warns about.
        warnings = judge_warnings(session, provider_id=app_provider, model="llama-3.1-8b")
        assert len(warnings) == 1
        assert "same model as the app under test" in warnings[0]
        assert "llama-3.1-8b" in warnings[0]

        # A different model is an independent judge and needs no warning.
        assert judge_warnings(session, provider_id=app_provider, model="gpt-4o") == []
        # Nothing chosen yet: no warning to give.
        assert judge_warnings(session, provider_id=app_provider, model=None) == []


def test_effective_model_falls_back_to_the_provider(
    session_factory: sessionmaker[Session],
) -> None:
    provider_id = _provider(session_factory, model="fallback-model")

    with session_factory() as session:
        provider = session.get(Provider, provider_id)
        assert provider is not None
        profile = JudgeProfile(
            owner_id=_user(session_factory),
            name="No model",
            provider_id=provider.id,
            model=None,
        )
        assert effective_model(profile, provider) == "fallback-model"
        profile.model = "explicit-model"
        assert effective_model(profile, provider) == "explicit-model"
        assert effective_model(profile, None) == "explicit-model"


# ---- API -------------------------------------------------------------------


def _register(client: TestClient, email: str = "judge@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Judge Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _create_provider(client: TestClient, model: str = "gpt-4o-mini") -> str:
    response = client.post(
        "/api/v1/providers",
        json={
            "name": f"judge-provider-{uuid.uuid4().hex[:6]}",
            "kind": "openai-compatible",
            "model_name": model,
            "base_url": "http://fake.test/v1",
        },
    )
    assert response.status_code == 201, response.text
    provider_id: str = response.json()["id"]
    return provider_id


def test_create_and_list_a_profile_through_the_api(client: TestClient) -> None:
    _register(client)
    provider_id = _create_provider(client, model="gpt-4o-mini")

    created = client.post(
        "/api/v1/judge-profiles",
        json={"name": "Saved judge", "provider_id": provider_id, "model": "gpt-4o-mini"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["is_selected"] is True
    assert body["rubric_version"] == JUDGE_RUBRIC_VERSION
    assert body["temperature"] == 0.0
    assert body["provider_name"]
    # Same model as the only saved provider: the response carries the warning.
    assert body["warnings"], body
    assert "same model as the app under test" in body["warnings"][0]

    listed = client.get("/api/v1/judge-profiles")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["selected_id"] == body["id"]
    assert payload["items"][0]["name"] == "Saved judge"


def test_api_warns_only_when_the_judge_matches_the_app_model(client: TestClient) -> None:
    _register(client, email="judge2@example.com")
    provider_id = _create_provider(client, model="app-model")

    response = client.post(
        "/api/v1/judge-profiles",
        json={"name": "Independent", "provider_id": provider_id, "model": "other-model"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["warnings"] == []


def test_selecting_a_profile_switches_the_default(client: TestClient) -> None:
    _register(client, email="judge3@example.com")
    provider_id = _create_provider(client)

    first = client.post("/api/v1/judge-profiles", json={"name": "One", "provider_id": provider_id})
    second = client.post("/api/v1/judge-profiles", json={"name": "Two", "provider_id": provider_id})
    assert first.status_code == 201 and second.status_code == 201, second.text
    second_id = second.json()["id"]

    selected = client.post(f"/api/v1/judge-profiles/{second_id}/select")
    assert selected.status_code == 200, selected.text
    assert selected.json()["is_selected"] is True

    listed = client.get("/api/v1/judge-profiles").json()
    assert listed["selected_id"] == second_id
    flags = {item["name"]: item["is_selected"] for item in listed["items"]}
    assert flags == {"One": False, "Two": True}


def test_profiles_are_owner_scoped(client: TestClient) -> None:
    _register(client, email="owner-a@example.com")
    provider_id = _create_provider(client)
    created = client.post(
        "/api/v1/judge-profiles", json={"name": "Mine", "provider_id": provider_id}
    )
    profile_id = created.json()["id"]

    client.cookies.clear()
    _register(client, email="owner-b@example.com")

    assert client.get("/api/v1/judge-profiles").json()["total"] == 0
    assert client.post(f"/api/v1/judge-profiles/{profile_id}/select").status_code == 404
    assert client.delete(f"/api/v1/judge-profiles/{profile_id}").status_code == 404


def test_signing_out_is_not_needed_to_read_but_required(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/v1/judge-profiles").status_code == 401


# ---- what a run uses -------------------------------------------------------


def test_a_run_uses_the_selected_judge_unless_one_is_requested(
    session_factory: sessionmaker[Session],
) -> None:
    owner = _user(session_factory)
    with session_factory() as session:
        user = session.get(User, owner)
        assert user is not None
        # Nothing saved yet: the run simply has no judge.
        assert resolve_judge_profile(session, user, None) is None

        first = create_judge_profile(session, owner_id=owner, name="Selected", provider_id=None)
        session.commit()
        assert resolve_judge_profile(session, user, None) == str(first.id)

        # An explicit request wins over the selected profile.
        other = create_judge_profile(session, owner_id=owner, name="Explicit", provider_id=None)
        session.commit()
        assert resolve_judge_profile(session, user, other.id) == str(other.id)

        with pytest.raises(RunServiceError) as caught:
            resolve_judge_profile(session, user, uuid.uuid4())
        assert caught.value.status == 404
        assert "Settings > Judge" in caught.value.message


def test_run_read_exposes_the_judge_and_the_skip_reason(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register(client, email="judged-run@example.com")
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == "judged-run@example.com"))
        assert user is not None
        judged = create_run(
            session,
            owner_id=user.id,
            name="Judged",
            settings_snapshot={
                "entry_point": "http_endpoint",
                "judge": {
                    "judge_model": "gpt-4o-mini",
                    "judge_provider_name": "OpenAI",
                    "judge_profile_name": "The judge",
                    "judge_rubric_version": "1.0",
                    "judge_prompt_hash": "deadbeef",
                    "judge_temperature": 0.0,
                    "judge_max_tokens": 512,
                    "judge_graded_items": 3,
                    "judge_unavailable_items": 1,
                    "judge_low_confidence_items": 0,
                },
            },
        )
        unjudged = create_run(
            session,
            owner_id=user.id,
            name="Not judged",
            settings_snapshot={
                "entry_point": "http_endpoint",
                "judge_skipped_reason": "This run had no judge profile.",
            },
        )
        session.commit()
        judged_id, unjudged_id = judged.id, unjudged.id

    first = client.get(f"/api/v1/runs/{judged_id}")
    assert first.status_code == 200, first.text
    judge = first.json()["judge"]
    assert judge["model"] == "gpt-4o-mini"
    assert judge["rubric_version"] == "1.0"
    assert judge["prompt_template_hash"] == "deadbeef"
    assert judge["graded_items"] == 3
    assert judge["unavailable_items"] == 1
    assert first.json()["judge_skipped_reason"] is None

    second = client.get(f"/api/v1/runs/{unjudged_id}")
    assert second.status_code == 200, second.text
    assert second.json()["judge"] is None
    assert "no judge profile" in second.json()["judge_skipped_reason"]
