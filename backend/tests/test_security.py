from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
import pytest

from app.config import Settings
from app.security.passwords import hash_password, verify_password
from app.security.rate_limit import RateLimiter
from app.security.tokens import (
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_token,
    utcnow,
)

SETTINGS = Settings(_env_file=None, app_secret_key="test-secret-key-value-0123456789abcdef")


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct horse battery")
    second = hash_password("correct horse battery")

    assert first != second
    assert verify_password("correct horse battery", first)
    assert not verify_password("wrong password", first)
    assert not verify_password("anything", "not-a-hash")


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, "admin", SETTINGS)

    payload = decode_access_token(token, SETTINGS)

    assert payload["sub"] == str(user_id)
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_expired_access_token_is_rejected() -> None:
    now = utcnow()
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "member",
            "type": "access",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        SETTINGS.app_secret_key,
        algorithm="HS256",
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, SETTINGS)


def test_non_access_token_is_rejected() -> None:
    now = utcnow()
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "iat": now, "exp": now + timedelta(days=1)},
        SETTINGS.app_secret_key,
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, SETTINGS)


def test_opaque_tokens_are_unique_and_hashed() -> None:
    raw = generate_opaque_token()

    assert len(raw) >= 43
    assert raw != generate_opaque_token()
    assert hash_token(raw) != raw
    assert hash_token(raw) == hash_token(raw)


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds

    def delete(self, key: str) -> None:
        self.counts.pop(key, None)


def test_rate_limiter_counts_and_resets() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(redis)

    assert limiter.allow("k", limit=2, window_seconds=60)
    assert limiter.allow("k", limit=2, window_seconds=60)
    assert not limiter.allow("k", limit=2, window_seconds=60)
    assert redis.expiries["k"] == 60

    limiter.reset("k")
    assert limiter.allow("k", limit=2, window_seconds=60)


def test_rate_limiter_fails_open_when_redis_is_down() -> None:
    class BrokenRedis:
        def incr(self, key: str) -> int:
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("down")

    limiter = RateLimiter(BrokenRedis())

    assert limiter.allow("k", limit=1, window_seconds=60)
