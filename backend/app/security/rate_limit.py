"""Redis-backed login rate limiting.

Fails open when Redis is unreachable: a cache outage must not lock every user out, and
passwords are still Argon2-verified.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import redis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger("greenlit.rate_limit")


class RateLimiter:
    """Fixed-window counter."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        try:
            count = int(self._client.incr(key))
            if count == 1:
                self._client.expire(key, window_seconds)
            return count <= limit
        except RedisError:
            logger.warning("Rate limiter unavailable; allowing request", exc_info=True)
            return True

    def reset(self, key: str) -> None:
        try:
            self._client.delete(key)
        except RedisError:
            logger.warning("Rate limiter unavailable; cannot reset", exc_info=True)


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """Shared limiter backed by the app's Redis instance."""
    client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=2)
    return RateLimiter(client)
