"""M4a API tests: dataset upload, listing, detail and versions."""

from __future__ import annotations

from fastapi.testclient import TestClient
from httpx import Response

CSV_BYTES = (
    b"id,question,answer,latency_ms\n"
    b"1,What is GreenLit?,A testing framework.,120\n"
    b"2,Is it free?,Yes.,80\n"
)

PASSWORD = "correct horse battery staple"


def _register(client: TestClient, email: str = "ada@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Ada", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _upload(
    client: TestClient,
    name: str = "Golden",
    content: bytes = CSV_BYTES,
    filename: str = "golden.csv",
    overrides: str | None = None,
) -> Response:
    data: dict[str, str] = {"name": name}
    if overrides is not None:
        data["column_overrides"] = overrides
    return client.post(
        "/api/v1/datasets",
        data=data,
        files={"file": (filename, content, "text/csv")},
    )


def test_upload_requires_auth(client: TestClient) -> None:
    response = _upload(client)
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["message"]


def test_upload_creates_version_and_hides_bytes(client: TestClient) -> None:
    _register(client)
    response = _upload(client)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["name"] == "Golden"
    assert body["file_format"] == "csv"
    assert len(body["content_hash"]) == 64
    assert "raw_content" not in body

    columns = body["columns"]
    assert columns["input_column"] == "question"
    assert columns["output_column"] == "answer"
    assert columns["detected"] is True

    assert len(body["versions"]) == 1
    version = body["versions"][0]
    assert version["version_no"] == 1
    assert version["row_count"] == 2
    assert version["columns_snapshot"] == {"columns": ["id", "question", "answer", "latency_ms"]}


def test_upload_with_overrides_marks_not_detected(client: TestClient) -> None:
    _register(client)
    response = _upload(
        client,
        name="Mapped",
        content=b"qry,resp\nhello,world\n",
        filename="mapped.csv",
        overrides='{"input_column": "qry", "output_column": "resp"}',
    )
    assert response.status_code == 201, response.text
    columns = response.json()["columns"]
    assert columns["input_column"] == "qry"
    assert columns["output_column"] == "resp"
    assert columns["detected"] is False


def test_upload_invalid_overrides_json_returns_422(client: TestClient) -> None:
    _register(client)
    response = _upload(client, overrides="not json at all")
    assert response.status_code == 422
    assert "column_overrides" in response.json()["error"]["message"]


def test_upload_duplicate_name_returns_409(client: TestClient) -> None:
    _register(client)
    assert _upload(client).status_code == 201

    duplicate = _upload(client, name="Golden", content=CSV_BYTES, filename="other.csv")
    assert duplicate.status_code == 409
    body = duplicate.json()
    assert body["error"]["code"] == "conflict"
    assert "Golden" in body["error"]["message"]


def test_upload_undetectable_columns_returns_400(client: TestClient) -> None:
    _register(client)
    response = _upload(client, content=b"foo,bar\n1,2\n", filename="useless.csv")
    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "input" in message
    assert "foo" in message


def test_upload_unknown_extension_returns_400(client: TestClient) -> None:
    _register(client)
    response = _upload(client, content=b"whatever", filename="dataset.pdf")
    assert response.status_code == 400
    assert "dataset.pdf" in response.json()["error"]["message"]


def test_upload_oversize_returns_413(client: TestClient) -> None:
    _register(client)
    response = _upload(client, content=b"x" * (10 * 1024 * 1024 + 1), filename="huge.csv")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_list_is_owner_scoped_and_paginated(client: TestClient) -> None:
    _register(client, "first@example.com")
    assert _upload(client, name="One").status_code == 201
    assert _upload(client, name="Two").status_code == 201

    page = client.get("/api/v1/datasets", params={"limit": 1, "offset": 0}).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["limit"] == 1

    second_page = client.get("/api/v1/datasets", params={"limit": 1, "offset": 1}).json()
    assert len(second_page["items"]) == 1
    assert second_page["items"][0]["name"] != page["items"][0]["name"]

    # Another signed-in user sees none of this.
    other = TestClient(client.app)
    _register(other, "second@example.com")
    other_page = other.get("/api/v1/datasets").json()
    assert other_page["total"] == 0
    assert other_page["items"] == []


def test_detail_and_versions_are_owner_scoped(client: TestClient) -> None:
    _register(client, "first@example.com")
    dataset_id = _upload(client, name="Mine").json()["id"]

    detail = client.get(f"/api/v1/datasets/{dataset_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == dataset_id

    versions = client.get(f"/api/v1/datasets/{dataset_id}/versions")
    assert versions.status_code == 200
    assert [v["version_no"] for v in versions.json()] == [1]

    other = TestClient(client.app)
    _register(other, "second@example.com")
    assert other.get(f"/api/v1/datasets/{dataset_id}").status_code == 404
    assert other.get(f"/api/v1/datasets/{dataset_id}/versions").status_code == 404

    missing = client.get("/api/v1/datasets/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
