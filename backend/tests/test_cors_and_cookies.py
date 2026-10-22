from __future__ import annotations

from fastapi.testclient import TestClient


def test_cors_allows_the_web_origin_with_credentials(client: TestClient) -> None:
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5177",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5177"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_unknown_origins(client: TestClient) -> None:
    response = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_secure_cookies_over_https(client: TestClient) -> None:
    # Reuse the fixture's app (its SQLite overrides) but pretend the request came over TLS.
    with TestClient(client.app, base_url="https://testserver") as secure_client:
        response = secure_client.post(
            "/api/v1/auth/register",
            json={"email": "tls@example.com", "name": "TLS", "password": "correct horse battery"},
        )

    assert response.status_code == 201
    cookies = response.headers.get_list("set-cookie")
    assert cookies
    assert all("Secure" in value for value in cookies)
