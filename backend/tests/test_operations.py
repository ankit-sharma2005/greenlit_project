"""Operations metrics: percentiles, rates, token totals and the cost guard."""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.services.operations import (
    ItemSample,
    compute_operations,
    is_timeout,
    percentile,
    prices_from_metadata,
    samples_from_items,
)


class TestPercentile:
    """The percentile has to be defined for every awkward sample count."""

    def test_no_samples_returns_none(self) -> None:
        assert percentile([], 0.5) is None
        assert percentile([], 0.95) is None

    def test_single_sample_returns_that_value_for_every_fraction(self) -> None:
        assert percentile([42.0], 0.0) == 42.0
        assert percentile([42.0], 0.5) == 42.0
        assert percentile([42.0], 0.95) == 42.0
        assert percentile([42.0], 1.0) == 42.0

    def test_two_samples_interpolate_at_the_midpoint(self) -> None:
        assert percentile([10.0, 20.0], 0.5) == 15.0
        assert percentile([10.0, 20.0], 0.0) == 10.0
        assert percentile([10.0, 20.0], 1.0) == 20.0

    def test_odd_count_middle_value_is_the_median(self) -> None:
        assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0

    def test_even_count_averages_the_two_middle_values(self) -> None:
        assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5

    def test_does_not_mutate_the_input(self) -> None:
        values = [3.0, 1.0, 2.0]
        percentile(values, 0.5)
        assert values == [3.0, 1.0, 2.0]

    def test_p95_is_at_least_p50(self) -> None:
        values = [float(value) for value in range(1, 21)]
        p50 = percentile(values, 0.5)
        p95 = percentile(values, 0.95)
        assert p50 is not None and p95 is not None
        assert p95 >= p50

    def test_rejects_a_fraction_outside_zero_to_one(self) -> None:
        with pytest.raises(ValueError):
            percentile([1.0], 1.5)


class TestIsTimeout:
    def test_recognises_timeout_text(self) -> None:
        assert is_timeout("Request timed out after 60s") is True
        assert is_timeout("timeout") is True

    def test_ignores_other_errors_and_empty(self) -> None:
        assert is_timeout("Connection refused") is False
        assert is_timeout(None) is False
        assert is_timeout("") is False


class TestComputeOperations:
    def test_no_cases_means_unknown_not_zero(self) -> None:
        block = compute_operations([])
        assert block["items_total"] == 0
        assert block["latency_p50_ms"] is None
        assert block["latency_p95_ms"] is None
        assert block["error_rate"] is None
        assert block["timeout_rate"] is None
        assert block["tokens_in_total"] is None
        assert block["tokens_out_total"] is None
        assert block["cost_estimate"] is None

    def test_single_healthy_case(self) -> None:
        block = compute_operations([ItemSample(state="completed", latency_ms=120)])
        assert block["items_attempted"] == 1
        assert block["latency_p50_ms"] == 120.0
        assert block["latency_p95_ms"] == 120.0
        assert block["error_rate"] == 0.0
        assert block["timeout_rate"] == 0.0

    def test_all_failures_report_a_full_error_rate(self) -> None:
        samples = [
            ItemSample(state="failed", latency_ms=10, error="Connection refused"),
            ItemSample(state="failed", latency_ms=20, error="500 Server Error"),
        ]
        block = compute_operations(samples)
        assert block["error_rate"] == 1.0
        # Neither error is a timeout, so the timeout rate is a real zero here.
        assert block["timeout_rate"] == 0.0
        assert block["items_timed_out"] == 0

    def test_timeout_rate_counts_only_timed_out_failures(self) -> None:
        samples = [
            ItemSample(state="failed", error="Request timed out"),
            ItemSample(state="failed", error="Connection refused"),
            ItemSample(state="completed", latency_ms=50),
            ItemSample(state="completed", latency_ms=60),
        ]
        block = compute_operations(samples)
        assert block["items_timed_out"] == 1
        assert block["error_rate"] == 0.5
        assert block["timeout_rate"] == 0.25

    def test_cancelled_cases_do_not_count_against_reliability(self) -> None:
        samples = [
            ItemSample(state="completed", latency_ms=100),
            ItemSample(state="cancelled"),
            ItemSample(state="cancelled"),
        ]
        block = compute_operations(samples)
        assert block["items_total"] == 3
        assert block["items_cancelled"] == 2
        assert block["items_attempted"] == 1
        assert block["error_rate"] == 0.0

    def test_everything_cancelled_means_no_rate_rather_than_zero(self) -> None:
        block = compute_operations([ItemSample(state="cancelled")])
        assert block["items_attempted"] == 0
        assert block["error_rate"] is None
        assert block["timeout_rate"] is None

    def test_tokens_are_null_when_the_app_never_reported_them(self) -> None:
        block = compute_operations(
            [ItemSample(state="completed", latency_ms=10), ItemSample(state="completed")]
        )
        assert block["tokens_in_total"] is None
        assert block["tokens_out_total"] is None
        assert block["latency_samples"] == 1

    def test_tokens_are_summed_when_reported(self) -> None:
        block = compute_operations(
            [
                ItemSample(state="completed", tokens_in=100, tokens_out=20),
                ItemSample(state="completed", tokens_in=50, tokens_out=10),
            ]
        )
        assert block["tokens_in_total"] == 150
        assert block["tokens_out_total"] == 30

    def test_cost_is_unconfigured_without_prices(self) -> None:
        block = compute_operations([ItemSample(state="completed", tokens_in=1000, tokens_out=0)])
        assert block["cost_configured"] is False
        assert block["cost_estimate"] is None

    def test_cost_is_computed_from_prices_per_1k(self) -> None:
        block = compute_operations(
            [ItemSample(state="completed", tokens_in=2000, tokens_out=1000)],
            price_per_1k_tokens_in=0.01,
            price_per_1k_tokens_out=0.02,
        )
        assert block["cost_configured"] is True
        # 2 * 0.01 + 1 * 0.02
        assert block["cost_estimate"] == pytest.approx(0.04)

    def test_cost_stays_null_when_no_tokens_were_reported(self) -> None:
        block = compute_operations(
            [ItemSample(state="completed", latency_ms=5)],
            price_per_1k_tokens_in=0.01,
            price_per_1k_tokens_out=0.02,
        )
        assert block["cost_configured"] is True
        assert block["cost_estimate"] is None


class TestPricesFromMetadata:
    def test_reads_both_prices(self) -> None:
        prices = prices_from_metadata(
            {"price_per_1k_tokens_in": 0.5, "price_per_1k_tokens_out": "1.25"}
        )
        assert prices == (0.5, 1.25)

    def test_missing_or_bad_values_are_not_configured(self) -> None:
        assert prices_from_metadata({}) == (None, None)
        assert prices_from_metadata(None) == (None, None)
        assert prices_from_metadata({"price_per_1k_tokens_in": "free"}) == (None, None)

    def test_negative_prices_are_rejected(self) -> None:
        assert prices_from_metadata({"price_per_1k_tokens_in": -1}) == (None, None)

    def test_booleans_are_not_prices(self) -> None:
        assert prices_from_metadata({"price_per_1k_tokens_in": True}) == (None, None)


class TestRetriedCases:
    """A case that recovered after retries is a success that needed retries."""

    def test_a_retried_success_is_not_an_error(self) -> None:
        result = compute_operations(
            [
                ItemSample(state="completed", latency_ms=120, retry_count=2),
                ItemSample(state="completed", latency_ms=90),
            ]
        )
        assert result["retried_cases"] == 1
        assert result["items_failed"] == 0
        assert result["error_rate"] == 0.0

    def test_no_retries_reports_zero_not_none(self) -> None:
        result = compute_operations([ItemSample(state="completed", latency_ms=50)])
        assert result["retried_cases"] == 0

    def test_the_item_trace_supplies_the_count(self) -> None:
        class Row:
            state = "completed"
            latency_ms = 30
            trace: ClassVar[dict[str, int]] = {"retry_count": 3, "waited_ms": 1200}

        samples = samples_from_items([Row()])
        assert samples[0].retry_count == 3
        assert compute_operations(samples)["retried_cases"] == 1


class TestSamplesFromItems:
    def test_adapts_objects_with_the_item_attributes(self) -> None:
        class Row:
            state = "completed"
            latency_ms = 30
            tokens_in = 7
            tokens_out = 3
            error = None

        samples = samples_from_items([Row()])
        assert samples == [
            ItemSample(state="completed", latency_ms=30, tokens_in=7, tokens_out=3, error=None)
        ]
