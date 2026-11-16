"""Tests for the operator CLI and for the role the register endpoint never accepts."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.models import ROLE_ADMIN, ROLE_MEMBER, ROLE_REVIEWER, AuditEvent, User

PASSWORD = "correct horse battery staple"


def _user(email: str, role: str = ROLE_MEMBER) -> User:
    return User(email=email, name="Test User", password_hash="not-a-real-hash", role=role)


def _add(factory: sessionmaker[Session], email: str, role: str = ROLE_MEMBER) -> User:
    session = factory()
    user = _user(email, role)
    session.add(user)
    session.commit()
    session.refresh(user)
    session.close()
    return user


def test_set_role_promotes_an_existing_account(session_factory: sessionmaker[Session]) -> None:
    _add(session_factory, "promote@example.com")
    session = session_factory()
    email, previous, current = cli.set_role(session, "Promote@Example.com", ROLE_ADMIN)

    assert (email, previous, current) == ("promote@example.com", ROLE_MEMBER, ROLE_ADMIN)
    assert session.scalar(select(User).where(User.email == email)).role == ROLE_ADMIN
    session.close()


def test_set_role_writes_one_audit_entry_naming_the_cli(
    session_factory: sessionmaker[Session],
) -> None:
    target = _add(session_factory, "audited@example.com")
    session = session_factory()
    cli.set_role(session, "audited@example.com", ROLE_REVIEWER)

    events = session.scalars(select(AuditEvent)).all()
    assert len(events) == 1
    event = events[0]
    assert event.action == "user.role_changed"
    assert event.actor_id is None
    assert event.target_id == str(target.id)
    assert event.event_metadata == {
        "from": ROLE_MEMBER,
        "to": ROLE_REVIEWER,
        "actor": "cli",
    }
    session.close()


def test_an_unknown_email_fails_and_creates_nothing(
    session_factory: sessionmaker[Session],
) -> None:
    session = session_factory()
    with pytest.raises(cli.CliError, match="No account with the email"):
        cli.set_role(session, "nobody@example.com", ROLE_ADMIN)
    assert session.scalar(select(User).where(User.email == "nobody@example.com")) is None
    session.close()


def test_an_invalid_role_is_refused(session_factory: sessionmaker[Session]) -> None:
    _add(session_factory, "typo@example.com")
    session = session_factory()
    with pytest.raises(cli.CliError, match="Unknown role"):
        cli.set_role(session, "typo@example.com", "superuser")
    assert session.scalar(select(User).where(User.email == "typo@example.com")).role == ROLE_MEMBER
    session.close()


def test_the_last_admin_cannot_be_demoted(session_factory: sessionmaker[Session]) -> None:
    _add(session_factory, "only-admin@example.com", ROLE_ADMIN)
    session = session_factory()
    with pytest.raises(cli.CliError, match="last admin"):
        cli.set_role(session, "only-admin@example.com", ROLE_MEMBER)
    still_admin = session.scalar(select(User).where(User.email == "only-admin@example.com"))
    assert still_admin.role == ROLE_ADMIN
    session.close()


def test_an_admin_can_be_demoted_when_another_admin_remains(
    session_factory: sessionmaker[Session],
) -> None:
    _add(session_factory, "first@example.com", ROLE_ADMIN)
    _add(session_factory, "second@example.com", ROLE_ADMIN)
    session = session_factory()
    email, previous, current = cli.set_role(session, "first@example.com", ROLE_MEMBER)
    assert (email, previous, current) == ("first@example.com", ROLE_ADMIN, ROLE_MEMBER)
    session.close()


def test_list_users_returns_only_safe_fields(session_factory: sessionmaker[Session]) -> None:
    _add(session_factory, "listed@example.com", ROLE_REVIEWER)
    session = session_factory()
    rows = cli.list_users(session, limit=5)
    assert rows and set(rows[0]) == {"email", "role", "created_at"}
    assert rows[0]["email"] == "listed@example.com"
    assert rows[0]["role"] == ROLE_REVIEWER
    assert len(cli.list_users(session, limit=1000)) <= cli.MAX_LIST_LIMIT
    session.close()


def test_the_cli_prints_no_password_or_hash(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add(session_factory, "quiet@example.com")
    monkeypatch.setattr(cli, "SessionLocal", session_factory)

    assert cli.main(["set-role", "--email", "quiet@example.com", "--role", "admin"]) == 0
    assert cli.main(["list-users", "--limit", "5"]) == 0
    printed = capsys.readouterr().out
    assert "quiet@example.com: member -> admin" in printed
    assert "not-a-real-hash" not in printed
    assert "password" not in printed.lower()
    assert "hash" not in printed.lower()


def test_the_cli_exits_non_zero_on_a_refusal(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    assert cli.main(["set-role", "--email", "ghost@example.com", "--role", "admin"]) == 2
    assert "No account" in capsys.readouterr().err


def test_register_cannot_choose_a_role(client: TestClient) -> None:
    payload: dict[str, Any] = {
        "email": "sneaky@example.com",
        "name": "Sneaky",
        "password": PASSWORD,
        "role": "admin",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422, response.text

    created = client.post(
        "/api/v1/auth/register",
        json={"email": "plain@example.com", "name": "Plain", "password": PASSWORD},
    )
    assert created.status_code == 201, created.text
    assert created.json()["user"]["role"] == ROLE_ADMIN  # first account on a fresh database
