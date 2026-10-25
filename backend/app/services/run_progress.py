"""Live run progress for the UI to poll (spec 8.1).

The worker publishes after every finished case; ``GET /runs/{id}/progress``
(M6c) reads it. Redis being down must never break a run, so both directions
fail open: publish drops the update with a warning, read reports "no progress".
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from typing import Any, Protocol

import redis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger("greenlit.run_progress")

PROGRESS_TTL_SECONDS = 60 * 60 * 24  # one day, then the key expires


@dataclass(frozen=True)
class RunProgress:
    """What the UI shows: cases done/total, stage and timestamps."""

    items_done: int = 0
    items_total: int = 0
    items_failed: int = 0
    items_cancelled: int = 0
    stage: str = "queued"
    started_at: str | None = None  # ISO timestamps, computed by the worker
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunProgress:
        """Rebuild from a Redis payload, ignoring keys added by newer workers."""
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in payload.items() if key in known})


class ProgressReporter(Protocol):
    """Where the worker writes progress and the API reads it."""

    def publish(self, run_id: uuid.UUID, progress: RunProgress) -> None: ...

    def read(self, run_id: uuid.UUID) -> RunProgress | None: ...


def _key(run_id: uuid.UUID) -> str:
    return f"run:{run_id}:progress"


class RedisProgress:
    """Publishes JSON blobs to Redis; every failure is logged, never raised."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def publish(self, run_id: uuid.UUID, progress: RunProgress) -> None:
        try:
            self._client.set(
                _key(run_id),
                json.dumps(progress.to_dict()),
                ex=PROGRESS_TTL_SECONDS,
            )
        except (RedisError, OSError, TypeError, ValueError):
            logger.warning("Could not publish progress for run %s", run_id, exc_info=True)

    def read(self, run_id: uuid.UUID) -> RunProgress | None:
        try:
            raw = self._client.get(_key(run_id))
        except (RedisError, OSError):
            logger.warning("Could not read progress for run %s", run_id, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            return RunProgress.from_dict(payload)
        except (TypeError, ValueError):
            return None


class MemoryProgress:
    """In-process reporter for tests (thread-safe, no Redis)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[uuid.UUID, RunProgress] = {}
        self.history: list[tuple[uuid.UUID, RunProgress]] = []

    def publish(self, run_id: uuid.UUID, progress: RunProgress) -> None:
        with self._lock:
            self._entries[run_id] = progress
            self.history.append((run_id, progress))

    def read(self, run_id: uuid.UUID) -> RunProgress | None:
        with self._lock:
            return self._entries.get(run_id)


@lru_cache(maxsize=1)
def get_progress() -> RedisProgress:
    """Shared reporter bound to the app's Redis instance."""
    client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=2)
    return RedisProgress(client)


def read_progress(run_id: uuid.UUID) -> RunProgress | None:
    """Convenience for API code: current progress or ``None`` if unavailable."""
    return get_progress().read(run_id)
