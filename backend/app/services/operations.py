"""Operations metrics for a finished run: latency, reliability and tokens.

This module is pure: it reads the per-case samples and returns a plain dict, so
the worker can store it and the API, the report and the tests can all reuse it
without touching a database.

Two rules matter more than the numbers:

* a metric with no samples is ``None``, never ``0`` — a run whose app never
  reported token counts has *unknown* token usage, not zero tokens;
* ``answer_quality``-style scoring is not involved here. These numbers describe
  how the app behaved, not how good its answers were.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# Connector and gateway error strings that mean "the app did not answer in time".
# Matching on text is the only signal available: a timeout is reported to us as
# an error message, not as a distinct field.
_TIMEOUT_MARKERS = ("timeout", "timed out")


@dataclass(frozen=True)
class ItemSample:
    """The per-case fields operations metrics need."""

    state: str
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Return the ``fraction`` percentile of ``values``, or ``None`` if empty.

    Uses linear interpolation between the two closest ranks (the same definition
    NumPy's default uses), which keeps one sample, two samples and uneven counts
    all well defined:

    * one value: that value, for every fraction;
    * two values: the midpoint at 0.5;
    * ``fraction`` 0 and 1 return the minimum and maximum.
    """
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between 0 and 1")
    if not values:
        return None

    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]

    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def is_timeout(error: str | None) -> bool:
    """True when an item's error text describes a timeout."""
    if not error:
        return False
    lowered = error.lower()
    return any(marker in lowered for marker in _TIMEOUT_MARKERS)


def _share(count: int, total: int) -> float | None:
    """A rate, or ``None`` when nothing was attempted (never a fake 0.0)."""
    if total <= 0:
        return None
    return count / total


def _sum_or_none(values: Sequence[int]) -> int | None:
    """Sum the reported values, or ``None`` when nothing was reported."""
    if not values:
        return None
    return sum(values)


def compute_operations(
    samples: Sequence[ItemSample],
    *,
    price_per_1k_tokens_in: float | None = None,
    price_per_1k_tokens_out: float | None = None,
) -> dict[str, Any]:
    """Summarise a run's cases into the operations block.

    ``price_per_1k_tokens_in``/``_out`` come from the provider's settings. When
    either is missing the cost estimate is ``None`` and ``cost_configured`` is
    false, which the UI and the report render as "not configured" rather than a
    misleading zero.
    """
    total = len(samples)
    failed = sum(1 for sample in samples if sample.state == "failed")
    cancelled = sum(1 for sample in samples if sample.state == "cancelled")

    # A cancelled case never ran, so it must not count against reliability.
    attempted = total - cancelled

    timed_out = sum(
        1 for sample in samples if sample.state == "failed" and is_timeout(sample.error)
    )
    latencies = [float(sample.latency_ms) for sample in samples if sample.latency_ms is not None]
    tokens_in_total = _sum_or_none(
        [sample.tokens_in for sample in samples if sample.tokens_in is not None]
    )
    tokens_out_total = _sum_or_none(
        [sample.tokens_out for sample in samples if sample.tokens_out is not None]
    )

    prices_configured = price_per_1k_tokens_in is not None and price_per_1k_tokens_out is not None
    cost_estimate: float | None = None
    if (
        price_per_1k_tokens_in is not None
        and price_per_1k_tokens_out is not None
        and (tokens_in_total is not None or tokens_out_total is not None)
    ):
        cost_estimate = round(
            ((tokens_in_total or 0) / 1000.0) * price_per_1k_tokens_in
            + ((tokens_out_total or 0) / 1000.0) * price_per_1k_tokens_out,
            6,
        )

    return {
        "items_total": total,
        "items_attempted": attempted,
        "items_failed": failed,
        "items_cancelled": cancelled,
        "latency_samples": len(latencies),
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p95_ms": percentile(latencies, 0.95),
        "error_rate": _share(failed, attempted),
        "timeout_rate": _share(timed_out, attempted),
        "items_timed_out": timed_out,
        "tokens_in_total": tokens_in_total,
        "tokens_out_total": tokens_out_total,
        "price_per_1k_tokens_in": price_per_1k_tokens_in,
        "price_per_1k_tokens_out": price_per_1k_tokens_out,
        "cost_configured": prices_configured,
        "cost_estimate": cost_estimate,
    }


def samples_from_items(items: Sequence[Any]) -> list[ItemSample]:
    """Adapt ORM run items (or any objects with the same attributes) to samples."""
    return [
        ItemSample(
            state=str(getattr(item, "state", "")),
            latency_ms=getattr(item, "latency_ms", None),
            tokens_in=getattr(item, "tokens_in", None),
            tokens_out=getattr(item, "tokens_out", None),
            error=getattr(item, "error", None),
        )
        for item in items
    ]


def prices_from_metadata(metadata: Any) -> tuple[float | None, float | None]:
    """Read token prices out of a provider's ``metadata`` bag.

    Anything unparseable is treated as "not configured" rather than raising: a
    bad price must never make a finished run unreadable.
    """
    if not isinstance(metadata, dict):
        return None, None

    def _price(key: str) -> float | None:
        raw = metadata.get(key)
        if raw is None or isinstance(raw, bool):
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if value < 0:
            return None
        return value

    return _price("price_per_1k_tokens_in"), _price("price_per_1k_tokens_out")
