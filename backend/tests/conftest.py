from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.security.rate_limit import RateLimiter, get_rate_limiter


class FakeRateLimiter(RateLimiter):
    """In-memory limiter so tests do not need Redis."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key] <= limit

    def reset(self, key: str) -> None:
        self.counts.pop(key, None)


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def limiter() -> FakeRateLimiter:
    return FakeRateLimiter()


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], limiter: FakeRateLimiter
) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_limiter() -> RateLimiter:
        return limiter

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_rate_limiter] = override_limiter
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth_headers(client: TestClient) -> dict[str, Any]:
    """Convenience for endpoints that only need cookies (kept for readability)."""
    return {}
