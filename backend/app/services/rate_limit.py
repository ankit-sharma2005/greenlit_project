from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID


class DailyQuotaPaused(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Provider daily request quota has been reached")


class ProviderRateLimiter:
    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper or asyncio.sleep
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._queue_lengths: defaultdict[UUID, int] = defaultdict(int)
        self._next_request_at: dict[UUID, float] = {}
        self._daily_counts: dict[UUID, tuple[date, int]] = {}

    def _now(self) -> float:
        if self._clock is not None:
            return self._clock()
        return asyncio.get_running_loop().time()

    async def wait_for_slot(self, provider_id: UUID, rpm: int, rpd: int) -> int:
        self._queue_lengths[provider_id] += 1
        queued_position = self._queue_lengths[provider_id]
        is_queued = True
        lock = self._locks.setdefault(provider_id, asyncio.Lock())
        try:
            async with lock:
                self._queue_lengths[provider_id] -= 1
                is_queued = False
                now_utc = datetime.now(UTC)
                day, count = self._daily_counts.get(provider_id, (now_utc.date(), 0))
                if day != now_utc.date():
                    day, count = now_utc.date(), 0
                if count >= rpd:
                    tomorrow = datetime.combine(
                        now_utc.date() + timedelta(days=1), time.min, tzinfo=UTC
                    )
                    raise DailyQuotaPaused(
                        max(1, int((tomorrow - now_utc).total_seconds()))
                    )

                now = self._now()
                slot = self._next_request_at.get(provider_id, now)
                delay = max(0.0, slot - now)
                if delay:
                    await self._sleeper(delay)
                self._daily_counts[provider_id] = (day, count + 1)
                self._next_request_at[provider_id] = max(now, slot) + 60 / rpm
                return queued_position - 1
        finally:
            if is_queued:
                self._queue_lengths[provider_id] -= 1

    def queue_length(self, provider_id: UUID) -> int:
        return self._queue_lengths[provider_id]

    def reset(self) -> None:
        self._locks.clear()
        self._queue_lengths.clear()
        self._next_request_at.clear()
        self._daily_counts.clear()
