"""The three model roles in the account's preference document.

Covers the rules the Settings panel depends on: a role can only name a provider
of the caller's own account, a role is left out of the response until it is
chosen, a theme-only save does not clear one, and no provider key is ever part
of the document.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


def register(client: TestClient, email: str = "model@example.com", name: str = "Model") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def make_provider(client: TestClient, name: str = "Local Ollama", model: str = "llama3") -> dict:
    response = client.post(
        "/api/v1/providers",
        json={"name": name, "kind": "ollama", "model_name": model, "api_key": "sentinel-key-123"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_roles_are_absent_until_chosen(client: TestClient) -> None:
    register(client)
    assert client.get("/api/v1/auth/me/preferences").json() == {"theme": "dark"}


def test_three_roles_persist_and_never_carry_the_provider_key(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)

    saved = client.patch(
        "/api/v1/auth/me/preferences",
        json={
            "theme": "dark",
            "judge": {"provider_id": provider["id"], "model": "llama3"},
            "target": {"provider_id": provider["id"], "model": "llama3"},
            "generator": {"provider_id": provider["id"], "model": "mixtral"},
        },
    )
    assert saved.status_code == 200, saved.text
    document = saved.json()
    assert document["judge"] == {"provider_id": provider["id"], "model": "llama3"}
    assert document["target"] == {"provider_id": provider["id"], "model": "llama3"}
    assert document["generator"] == {"provider_id": provider["id"], "model": "mixtral"}
    assert "sentinel-key-123" not in saved.text
    assert "api_key" not in saved.text

    # Read back from the database, not from the response alone.
    assert client.get("/api/v1/auth/me/preferences").json() == document


def test_a_theme_only_save_keeps_the_chosen_roles(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)
    client.patch(
        "/api/v1/auth/me/preferences",
        json={"theme": "dark", "judge": {"provider_id": provider["id"], "model": "llama3"}},
    )

    saved = client.patch("/api/v1/auth/me/preferences", json={"theme": "light"})
    assert saved.status_code == 200, saved.text
    document = saved.json()
    assert document["theme"] == "light"
    assert document["judge"]["model"] == "llama3"


def test_an_unknown_provider_is_rejected_and_nothing_is_stored(client: TestClient) -> None:
    """Providers are workspace-wide here, so the rule is "the id must exist"."""
    register(client)

    refused = client.patch(
        "/api/v1/auth/me/preferences",
        json={
            "theme": "dark",
            "judge": {
                "provider_id": "00000000-0000-4000-8000-000000000000",
                "model": "llama3",
            },
        },
    )
    assert refused.status_code == 422
    assert "judge" not in client.get("/api/v1/auth/me/preferences").json()


def test_two_accounts_keep_separate_role_defaults(client: TestClient) -> None:
    register(client, "first@example.com", "First")
    provider = make_provider(client)
    client.patch(
        "/api/v1/auth/me/preferences",
        json={"theme": "dark", "judge": {"provider_id": provider["id"], "model": "llama3"}},
    )

    with TestClient(client.app) as second:
        register(second, "second@example.com", "Second")
        assert "judge" not in second.get("/api/v1/auth/me/preferences").json()

    assert client.get("/api/v1/auth/me/preferences").json()["judge"]["model"] == "llama3"


def test_a_role_needs_a_model_and_unknown_keys_are_refused(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)

    blank_model = client.patch(
        "/api/v1/auth/me/preferences",
        json={"theme": "dark", "generator": {"provider_id": provider["id"], "model": ""}},
    )
    assert blank_model.status_code == 422

    extra_key = client.patch(
        "/api/v1/auth/me/preferences",
        json={
            "theme": "dark",
            "judge": {"provider_id": provider["id"], "model": "llama3", "temperature": 0},
        },
    )
    assert extra_key.status_code == 422

    assert client.get("/api/v1/auth/me/preferences").json() == {"theme": "dark"}
