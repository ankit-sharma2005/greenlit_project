from __future__ import annotations

import argparse
import json
from math import sqrt
from pathlib import Path


def cohen_kappa(a: list[int], b: list[int]) -> float:
    if len(a) != len(b):
        raise ValueError("input lists must have the same length")
    if not a:
        return 0.0
    total = len(a)
    agree = sum(1 for left, right in zip(a, b) if left == right)
    observed = agree / total
    p1 = sum(x == 1 for x in a) / total
    p2 = sum(x == 1 for x in b) / total
    expected = (p1 * p2) + ((1 - p1) * (1 - p2))
    if abs(1 - expected) < 1e-12:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def bootstrap_ci(values: list[float], *, reps: int = 200, confidence: float = 0.95) -> dict[str, float]:
    if not values:
        return {"lower": 0.0, "upper": 0.0, "mean": 0.0}
    import random

    random.seed(7)
    sampled = []
    for _ in range(reps):
        sample = [random.choice(values) for _ in values]
        sampled.append(sum(sample) / len(sample))
    sampled.sort()
    cut = int((1.0 - confidence) * len(sampled) / 2)
    return {
        "lower": sampled[cut],
        "upper": sampled[-cut - 1],
        "mean": sum(values) / len(values),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize demo research statistics.")
    parser.add_argument("--output", type=Path, default=Path(".tmp/research.json"), help="Write JSON summary.")
    args = parser.parse_args()

    reviewer_a = [1, 0, 1, 1, 0, 1, 0]
    reviewer_b = [1, 0, 1, 0, 0, 1, 0]
    scores = [0.81, 0.88, 0.77, 0.92, 0.73, 0.85, 0.9]

    summary = {
        "cohens_kappa": cohen_kappa(reviewer_a, reviewer_b),
        "score_ci": bootstrap_ci(scores),
        "sample_size": len(scores),
        "mean_score": sum(scores) / len(scores),
        "std_dev": sqrt(sum((value - (sum(scores) / len(scores))) ** 2 for value in scores) / max(len(scores) - 1, 1)),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"cohens_kappa": summary["cohens_kappa"], "mean_score": summary["mean_score"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
