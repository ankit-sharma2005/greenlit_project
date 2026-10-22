from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_unknown_route_uses_error_envelope() -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]
    assert body["error"]["fields"] == []


def test_validation_errors_list_fields() -> None:
    @app.get("/_test/validate")
    def validate(count: int) -> dict[str, int]:
        return {"count": count}

    response = client.get("/_test/validate", params={"count": "not-a-number"})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["fields"][0]["field"] == "count"
    assert "valid integer" in body["fields"][0]["message"]


def test_unhandled_exception_hides_details() -> None:
    @app.get("/_test/boom")
    def boom() -> None:
        raise RuntimeError("secret internals")

    response = client.get("/_test/boom")

    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "error"
    assert "secret internals" not in body["message"]
