"""The preference fields beyond the theme: entry point, test types, zone, answers.

Two rules are pinned here. An invalid value is refused at the door (a time zone
must be one the tz database can resolve), and a key the request leaves out stays
unset — absent from the response rather than null — so the documents older
clients expect are byte-for-byte unchanged.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import User

PASSWORD = "correct horse battery staple"


def register(client: TestClient, email: str = "ada@example.com", name: str = "Ada") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def test_every_new_field_saves_and_survives_a_reload(client: TestClient) -> None:
    register(client)

    saved = client.patch(
        "/api/v1/auth/me/preferences",
        json={
            "theme": "light",
            "entry_point": "prompt_app",
            "test_types": ["quality", "operations"],
            "time_zone": "Europe/Berlin",
            "show_full_answers": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "theme": "light",
        "entry_point": "prompt_app",
        "test_types": ["quality", "operations"],
        "time_zone": "Europe/Berlin",
        "show_full_answers": True,
    }
    # Read again from the database, not from the response the write produced.
    assert client.get("/api/v1/auth/me/preferences").json() == saved.json()


def test_unset_fields_are_absent_rather_than_null(client: TestClient) -> None:
    register(client)

    # The theme alone is the document every older screen sends.
    saved = client.patch("/api/v1/auth/me/preferences", json={"theme": "dark"})
    assert saved.status_code == 200
    assert saved.json() == {"theme": "dark"}

    # Setting one of the new fields must not turn the others into nulls.
    partial = client.patch(
        "/api/v1/auth/me/preferences", json={"theme": "dark", "entry_point": "mcp_server"}
    )
    assert partial.json() == {"theme": "dark", "entry_point": "mcp_server"}


def test_a_later_save_does_not_wipe_a_field_it_omits(client: TestClient) -> None:
    register(client)
    client.patch(
        "/api/v1/auth/me/preferences",
        json={"theme": "dark", "time_zone": "Asia/Kolkata", "test_types": ["safety"]},
    )

    # A theme-only save from another screen keeps the rest of the document.
    after = client.patch("/api/v1/auth/me/preferences", json={"theme": "light"})
    assert after.json() == {
        "theme": "light",
        "test_types": ["safety"],
        "time_zone": "Asia/Kolkata",
    }


def test_an_invalid_time_zone_is_refused_and_nothing_is_stored(client: TestClient) -> None:
    register(client)

    refused = client.patch(
        "/api/v1/auth/me/preferences", json={"theme": "dark", "time_zone": "Mars/Olympus"}
    )
    assert refused.status_code == 422
    assert any(field["field"] == "time_zone" for field in refused.json()["error"]["fields"]), (
        refused.text
    )
    assert client.get("/api/v1/auth/me/preferences").json() == {"theme": "dark"}

    blank = client.patch("/api/v1/auth/me/preferences", json={"theme": "dark", "time_zone": ""})
    assert blank.status_code == 422


def test_unknown_entry_point_and_repeated_test_types_are_refused(client: TestClient) -> None:
    register(client)

    bad_entry = client.patch(
        "/api/v1/auth/me/preferences", json={"theme": "dark", "entry_point": "docker_image"}
    )
    assert bad_entry.status_code == 422

    repeated = client.patch(
        "/api/v1/auth/me/preferences",
        json={"theme": "dark", "test_types": ["quality", "quality"]},
    )
    assert repeated.status_code == 422

    unknown_type = client.patch(
        "/api/v1/auth/me/preferences", json={"theme": "dark", "test_types": ["speed"]}
    )
    assert unknown_type.status_code == 422

    assert client.get("/api/v1/auth/me/preferences").json() == {"theme": "dark"}


def test_a_stored_value_the_build_cannot_use_is_left_out(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    register(client)
    client.patch(
        "/api/v1/auth/me/preferences", json={"theme": "dark", "time_zone": "Europe/Berlin"}
    )

    # Simulate a row written by hand, or by a build whose lists have moved on.
    with session_factory() as db:
        user = db.query(User).one()
        user.preferences = {
            **(user.preferences or {}),
            "time_zone": "Nowhere/Special",
            "entry_point": "python_function",
            "test_types": ["quality", "speed"],
            "show_full_answers": "yes",
        }
        db.commit()

    served = client.get("/api/v1/auth/me/preferences").json()
    # The unusable values are dropped; `speed` is not a test type this build has.
    assert served == {"theme": "dark", "test_types": ["quality"]}
