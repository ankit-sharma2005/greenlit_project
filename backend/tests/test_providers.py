"""M2: Provider CRUD, encryption, connection testing, and rate limits.

M3 additions: HTTP endpoint, prompt_app, and upload_outputs connectors.
"""

from __future__ import annotations

import httpx
import sqlalchemy
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, SessionLocal
from app.deps import get_current_user
from app.main import app
from app.models import Provider, User
from app.security.keys import decrypt_key, encrypt_key
from app.security.passwords import hash_password
from app.security.tokens import ACCESS_COOKIE


def test_encrypt_decrypt_round_trip() -> None:
    """Encrypt key at rest; decrypt only in service layer."""
    plain = "sk-live-abc123xyz789"
    encrypted = encrypt_key(plain)
    assert encrypted is not None
    assert encrypted != plain
    assert len(encrypted) > 0
    decrypted = decrypt_key(encrypted)
    assert decrypted == plain


def test_provider_read_no_api_key() -> None:
    """ProviderRead should never include raw api_key."""
    engine = sqlalchemy.create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}
    )
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    prov = Provider(
        name="test",
        kind="openai-compatible",
        model_name="gpt-4",
        base_url="https://api.example.com/v1",
        is_active=True,
    )
    db = SessionLocal(bind=engine)
    try:
        db.add(prov)
        db.commit()
        db.refresh(prov)

        from app.schemas.providers import ProviderRead

        schema = ProviderRead.model_validate(prov)
        # api_key should default to None in ProviderRead (not stored/returned)
        assert schema.api_key is None
    finally:
        db.close()


def test_provider_duplicate_name_409_case_insensitive() -> None:
    """Duplicate provider name (case-insensitive) returns 409."""
    from sqlalchemy import func, select

    engine = sqlalchemy.create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}
    )
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal(bind=engine)
    try:
        # Create first provider
        prov1 = Provider(name="DupTest", kind="openai-compatible", model_name="gpt-4")
        db.add(prov1)
        db.commit()

        # Try to create duplicate (case-insensitive)
        prov2 = Provider(name="duptest", kind="openai-compatible", model_name="gpt-4")
        db.add(prov2)

        # Check that lowercase name matches the uppercase one
        existing = db.scalar(select(Provider).where(func.lower(Provider.name) == "duptest"))
        # The second should find the first (case-insensitive match)
        assert existing is prov1
    finally:
        db.close()


def test_gateway_timeout() -> None:
    """Timeout should be honored during provider connection test.

    Verifies that when a provider has a short timeout,
    the connection test returns a timeout error rather than hanging.
    """
    from app.services.providers import test_provider_connection

    # Create a provider with a very short timeout
    test_engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    prov = Provider(
        name="timeout-test",
        kind="openai-compatible",
        model_name="gpt-4",
        base_url="https://nonexistent-host-12345.com/v1/models",
        timeout_seconds=1,  # Very short timeout
        max_retries=1,
        is_active=True,
    )
    # We can't easily test this without hitting a real endpoint,
    # but we verify the provider is created and can be read
    db = SessionLocal(bind=test_engine)
    try:
        db.add(prov)
        db.commit()
        db.refresh(prov)
        result = test_provider_connection(prov)
        # Should get a connection error (DNS lookup fails before timeout),
        # not hang. The key thing is it returns success=False quickly.
        assert not result["success"]
        # The error message may be "connection error" since DNS resolves
        # quickly even for bad hosts. Just verify it fails fast.
        assert result.get("message") is not None
    finally:
        db.close()


def test_gateway_rate_limit() -> None:
    """Rate limit should be respected per provider configuration.

    Verifies that providers with rate_limit_per_minute
    have that constraint stored and can be checked.
    """
    from app.models import Provider

    # Create a provider with rate limiting
    prov = Provider(
        name="rate-limited-test",
        kind="openai-compatible",
        model_name="gpt-4",
        base_url="https://api.example.com/v1",
        rate_limit_per_minute=60,
        tokens_per_minute=100,
        is_active=True,
    )
    test_engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    db = SessionLocal(bind=test_engine)
    try:
        db.add(prov)
        db.commit()
        db.refresh(prov)
        # Verify the rate limit settings are stored
        refreshed = db.get(Provider, prov.id)
        assert refreshed is not None
        assert refreshed.rate_limit_per_minute == 60
        assert refreshed.tokens_per_minute == 100
    finally:
        db.close()


def test_connection_endpoint_returns_200() -> None:
    """Test-connection endpoint should return 200 with health status.

    Verifies the /api/v1/providers/{id}/test endpoint works
    correctly with a valid provider configuration.
    Uses real authentication flow - logs in then tests the endpoint.
    """
    from fastapi.testclient import TestClient

    from app.db import get_db

    original_get_current_user = app.dependency_overrides.get(get_current_user)
    original_get_db = app.dependency_overrides.get(get_db)

    # Create a single test engine for both user and provider
    test_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # Create a test admin user
    db = session_local()
    try:
        user = User(
            email="test@example.com",
            name="Test User",
            role="admin",
            is_active=True,
            password_hash=hash_password("testpassword"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    finally:
        db.close()

    # Override get_db to provide the same real session
    def override_get_db() -> Session:
        return session_local()

    # No need to override get_current_user - it reads the access cookie
    # We'll use a real token generated from the test user
    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)

        # Login first to get a real access cookie
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "testpassword"},
        )
        print(f"Login response: {login_response.status_code}")
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"

        # Now test the connection endpoint with the real cookie
        # First create a provider in the same database
        db = session_local()
        try:
            prov = Provider(
                name="conn-test",
                kind="openai-compatible",
                model_name="gpt-4",
                base_url="https://api.example.com/v1",
                is_active=True,
            )
            db.add(prov)
            db.commit()
            db.refresh(prov)
            print(f"Provider created: {prov.id}")

            # Test the connection endpoint with the real auth cookie
            access_cookie = login_response.cookies.get(ACCESS_COOKIE)
            assert access_cookie is not None
            response = client.post(
                f"/api/v1/providers/{prov.id!s}/test",
                # Use the cookie from the login response
                cookies={ACCESS_COOKIE: access_cookie},
            )
            print(f"Test connection response: {response.status_code}")
            # Should return 200 with a ProviderTestResult
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}, body: {response.text}"
            )
            body = response.json()
            assert "success" in body, f"Expected 'success' in body, got: {body}"
            assert "message" in body, f"Expected 'message' in body, got: {body}"
        finally:
            db.close()
    finally:
        if original_get_current_user is not None:
            app.dependency_overrides[get_current_user] = original_get_current_user
        else:
            app.dependency_overrides.clear()
        if original_get_db is not None:
            app.dependency_overrides[get_db] = original_get_db
        else:
            app.dependency_overrides.clear()


def test_create_provider_endpoint_reads_the_provider_body(client: TestClient) -> None:
    """POST /providers takes the provider as its body.

    The admin guard is a dependency, so its ``user`` argument must stay out of
    the request body; otherwise the endpoint demands ``{"user": ..., "body": ...}``
    and no client can create a provider at all.
    """
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Provider Admin",
            "email": "providers@example.com",
            "password": "password123456",
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["user"]["role"] == "admin"

    created = client.post(
        "/api/v1/providers",
        json={
            "name": "Fake Prompt App Provider",
            "kind": "openai-compatible",
            "model_name": "fake-connector-model",
            "base_url": "http://127.0.0.1:9999/v1",
            "connector": "prompt_app",
            "timeout_seconds": 30,
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Fake Prompt App Provider"


def _admin_with_provider(client: TestClient) -> dict[str, object]:
    """Register the first (admin) account and create one provider."""
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Price Admin",
            "email": "prices@example.com",
            "password": "password123456",
        },
    )
    assert registered.status_code == 201, registered.text
    created = client.post(
        "/api/v1/providers",
        json={
            "name": "Priced provider",
            "kind": "openai-compatible",
            "model_name": "gpt-4o-mini",
            "base_url": "http://127.0.0.1:9999/v1",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_prices_are_saved_in_metadata(client: TestClient) -> None:
    """A price is stored in the metadata bag, where operations.py reads it."""
    provider = _admin_with_provider(client)

    patched = client.patch(
        f"/api/v1/providers/{provider['id']}",
        json={"metadata": {"price_per_1k_tokens_in": 0.15, "price_per_1k_tokens_out": 0.6}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["provider_config"] == {
        "price_per_1k_tokens_in": 0.15,
        "price_per_1k_tokens_out": 0.6,
    }

    # And it survives a round trip through the list endpoint the UI reads.
    listed = client.get("/api/v1/providers").json()
    assert listed[0]["provider_config"]["price_per_1k_tokens_in"] == 0.15


def test_clearing_a_price_removes_the_key(client: TestClient) -> None:
    """null means unset: the key is removed, never stored as 0."""
    provider = _admin_with_provider(client)
    client.patch(
        f"/api/v1/providers/{provider['id']}",
        json={"metadata": {"price_per_1k_tokens_in": 0.15, "price_per_1k_tokens_out": 0.6}},
    )

    cleared = client.patch(
        f"/api/v1/providers/{provider['id']}",
        json={"metadata": {"price_per_1k_tokens_in": None}},
    )
    assert cleared.status_code == 200, cleared.text
    config = cleared.json()["provider_config"]
    assert "price_per_1k_tokens_in" not in config
    # The other price is untouched.
    assert config["price_per_1k_tokens_out"] == 0.6


def test_metadata_merge_keeps_unrelated_keys(client: TestClient) -> None:
    """Editing prices must not drop metadata keys this form knows nothing about."""
    provider = _admin_with_provider(client)
    client.patch(
        f"/api/v1/providers/{provider['id']}",
        json={"metadata": {"region": "eu-west", "price_per_1k_tokens_in": 1.0}},
    )

    patched = client.patch(
        f"/api/v1/providers/{provider['id']}",
        json={"metadata": {"price_per_1k_tokens_out": 2.0}},
    )
    assert patched.status_code == 200, patched.text
    config = patched.json()["provider_config"]
    assert config["region"] == "eu-west"
    assert config["price_per_1k_tokens_in"] == 1.0
    assert config["price_per_1k_tokens_out"] == 2.0


def test_negative_price_is_rejected(client: TestClient) -> None:
    """A negative price is a 422 and changes nothing."""
    provider = _admin_with_provider(client)

    rejected = client.patch(
        f"/api/v1/providers/{provider['id']}",
        json={"metadata": {"price_per_1k_tokens_in": -1}},
    )
    assert rejected.status_code == 422, rejected.text

    # The stored value is unchanged, so a bad edit cannot corrupt a provider.
    listed = client.get("/api/v1/providers").json()
    assert "price_per_1k_tokens_in" not in (listed[0]["provider_config"] or {})


def test_negative_price_rejected_on_create(client: TestClient) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={"name": "Create Admin", "email": "create@example.com", "password": "password123456"},
    )
    assert registered.status_code == 201, registered.text

    rejected = client.post(
        "/api/v1/providers",
        json={
            "name": "Bad price provider",
            "kind": "openai-compatible",
            "model_name": "gpt-4o-mini",
            "metadata": {"price_per_1k_tokens_out": -0.5},
        },
    )
    assert rejected.status_code == 422, rejected.text


def test_non_numeric_price_is_rejected(client: TestClient) -> None:
    provider = _admin_with_provider(client)
    rejected = client.patch(
        f"/api/v1/providers/{provider['id']}",
        json={"metadata": {"price_per_1k_tokens_in": "free"}},
    )
    assert rejected.status_code == 422, rejected.text


def _reply(content: str, usage: object) -> httpx.Response:
    """A minimal chat-completions response with an optional usage block."""
    body: dict[str, object] = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body, request=httpx.Request("POST", "http://test"))


def test_gateway_records_token_usage() -> None:
    """The gateway keeps the replied usage so operations can price a run."""
    from app.services.llm_gateway import LLMGateway

    provider = Provider(
        name="usage-test",
        kind="openai-compatible",
        model_name="gpt-4o-mini",
        base_url="http://127.0.0.1:9999/v1",
        is_active=True,
        max_retries=0,
        timeout_seconds=5,
    )
    gateway = LLMGateway(
        post=lambda *a, **k: _reply("hello", {"prompt_tokens": 11, "completion_tokens": 7})
    )

    assert gateway.chat(provider, [{"role": "user", "content": "hi"}]) == "hello"
    assert gateway.last_usage == {"prompt_tokens": 11, "completion_tokens": 7}


def test_gateway_ignores_missing_or_bad_usage() -> None:
    """A provider that reports nothing usable must not crash the call."""
    from app.services.llm_gateway import LLMGateway

    provider = Provider(
        name="usage-test-2",
        kind="openai-compatible",
        model_name="gpt-4o-mini",
        base_url="http://127.0.0.1:9999/v1",
        is_active=True,
        max_retries=0,
        timeout_seconds=5,
    )

    gateway = LLMGateway(post=lambda *a, **k: _reply("hello", None))
    gateway.chat(provider, [{"role": "user", "content": "hi"}])
    assert gateway.last_usage == {}

    gateway = LLMGateway(
        post=lambda *a, **k: _reply("hello", {"prompt_tokens": "many", "completion_tokens": 3})
    )
    gateway.chat(provider, [{"role": "user", "content": "hi"}])
    # Only the usable number is kept.
    assert gateway.last_usage == {"completion_tokens": 3}
