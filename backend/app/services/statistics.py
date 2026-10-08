from __future__ import annotations

import itertools
import math
import random
from collections.abc import Sequence


def paired_bootstrap_interval(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    confidence: float = 0.95,
    iterations: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    differences = _paired_differences(baseline, candidate)
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if not differences:
        raise ValueError("at least one paired observation is required")

    generator = random.Random(seed)
    size = len(differences)
    estimates = sorted(
        sum(generator.choices(differences, k=size)) / size for _ in range(iterations)
    )
    tail = (1 - confidence) / 2
    return (
        _quantile(estimates, tail),
        _quantile(estimates, 1 - tail),
    )


def paired_permutation_p_value(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    exact_limit: int = 16,
    iterations: int = 10_000,
    seed: int = 0,
) -> float:
    differences = _paired_differences(baseline, candidate)
    if not differences:
        raise ValueError("at least one paired observation is required")
    observed = abs(sum(differences) / len(differences))
    if observed == 0:
        return 1.0
    if len(differences) <= exact_limit:
        extreme = sum(
            abs(
                sum(
                    sign * value for sign, value in zip(signs, differences, strict=True)
                )
                / len(differences)
            )
            >= observed - 1e-12
            for signs in itertools.product((-1.0, 1.0), repeat=len(differences))
        )
        return float(extreme / (2 ** len(differences)))
    if iterations < 1:
        raise ValueError("iterations must be positive")
    generator = random.Random(seed)
    extreme = sum(
        abs(sum(generator.choice((-1.0, 1.0)) * value for value in differences))
        / len(differences)
        >= observed - 1e-12
        for _ in range(iterations)
    )
    return float((extreme + 1) / (iterations + 1))


def mcnemar_exact_p_value(
    baseline_pass: Sequence[bool], candidate_pass: Sequence[bool]
) -> float:
    if len(baseline_pass) != len(candidate_pass):
        raise ValueError("McNemar observations must be paired")
    if not baseline_pass:
        raise ValueError("at least one paired observation is required")
    baseline_only = sum(
        before and not after
        for before, after in zip(baseline_pass, candidate_pass, strict=True)
    )
    candidate_only = sum(
        not before and after
        for before, after in zip(baseline_pass, candidate_pass, strict=True)
    )
    discordant = baseline_only + candidate_only
    if discordant == 0:
        return 1.0
    tail = min(baseline_only, candidate_only)
    probability = sum(int(math.comb(discordant, value)) for value in range(tail + 1))
    return float(min(1.0, 2 * probability / (2**discordant)))


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    if any(not 0 <= value <= 1 for value in p_values):
        raise ValueError("p-values must be between 0 and 1")
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [0.0] * len(p_values)
    running_max = 0.0
    count = len(p_values)
    for rank, index in enumerate(order):
        running_max = max(running_max, (count - rank) * p_values[index])
        adjusted[index] = min(1.0, running_max)
    return adjusted


def _paired_differences(
    baseline: Sequence[float], candidate: Sequence[float]
) -> list[float]:
    if len(baseline) != len(candidate):
        raise ValueError("paired observations must have equal length")
    if any(not math.isfinite(value) for value in (*baseline, *candidate)):
        raise ValueError("observations must be finite")
    return [after - before for before, after in zip(baseline, candidate, strict=True)]


def _quantile(values: Sequence[float], probability: float) -> float:
    index = (len(values) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight
