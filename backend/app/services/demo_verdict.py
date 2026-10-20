from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.phase5_schemas import VerdictCriteria
from app.services.metrics import (
    ANSWER_MATCH_METRIC_NAME,
    METRIC_BY_NAME,
    MetricCase,
)
from app.services.verdicts import VerdictItem, evaluate_verdict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_DIR = REPO_ROOT / "greenlit_demo"
DEFAULT_CRITERIA = VerdictCriteria(
    go_threshold=0.8,
    review_threshold=0.6,
    category_weights={
        "quality": 1.0,
        "rag": 1.0,
        "tool": 1.0,
        "operational": 1.0,
    },
)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def _build_trace(row: dict[str, str]) -> dict[str, object]:
    retrieved_context = row.get("retrieved_context", "").strip()
    return {
        "output": row.get("output", ""),
        "latency_ms": int(row.get("latency_ms", "0") or 0),
        "usage": {
            "tokens_in": int(row.get("tokens_in", "0") or 0),
            "tokens_out": int(row.get("tokens_out", "0") or 0),
        },
        "steps": {
            "retrieved_chunks": [retrieved_context] if retrieved_context else [],
        },
    }


def evaluate_demo_output(
    dataset_path: Path,
    output_path: Path,
    *,
    criteria: VerdictCriteria = DEFAULT_CRITERIA,
) -> dict[str, object]:
    dataset_rows = _read_csv_rows(dataset_path)
    output_rows = _read_csv_rows(output_path)
    if len(dataset_rows) != len(output_rows):
        raise ValueError(
            f"Dataset row count ({len(dataset_rows)}) does not match output row count "
            f"({len(output_rows)})."
        )

    verdict_items: list[VerdictItem] = []
    metric_details: list[dict[str, object]] = []
    for dataset_row, output_row in zip(dataset_rows, output_rows, strict=True):
        case = MetricCase(
            input_text=dataset_row["input"],
            reference_answer=dataset_row.get("reference_answer"),
            reference_context=dataset_row.get("reference_context"),
            category=dataset_row.get("category", "quality"),
            data={},
        )
        trace = _build_trace(output_row)
        scores = [
            METRIC_BY_NAME["output_nonempty"].evaluator(case, trace),
            METRIC_BY_NAME[ANSWER_MATCH_METRIC_NAME].evaluator(case, trace),
            METRIC_BY_NAME["retrieval_context_recall"].evaluator(case, trace),
            METRIC_BY_NAME["latency_under_5s"].evaluator(case, trace),
            METRIC_BY_NAME["token_usage_present"].evaluator(case, trace),
        ]
        metric_details.append(
            {
                "item_id": dataset_row["id"],
                "metrics": [
                    {
                        "name": score.name,
                        "score": score.score,
                        "reason": score.reason,
                    }
                    for score in scores
                ],
            }
        )
        verdict_items.append(
            VerdictItem(
                id=dataset_row["id"],
                position=1,
                status="completed",
                category=dataset_row.get("category", "quality"),
                scores=scores,
            )
        )

    report = evaluate_verdict(criteria, verdict_items, run_status="completed")
    return {
        "verdict": report.verdict,
        "score": report.score,
        "summary": report.summary,
        "reasons": report.reasons,
        "metrics": metric_details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real verdict engine against the demo golden dataset and "
            "output CSVs."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEMO_DIR / "golden_dataset.csv",
        help="Path to the golden_dataset.csv file.",
    )
    parser.add_argument(
        "--good-output",
        type=Path,
        default=DEMO_DIR / "outputs_good.csv",
        help="Path to the known-good output CSV.",
    )
    parser.add_argument(
        "--broken-output",
        type=Path,
        default=DEMO_DIR / "outputs_broken.csv",
        help="Path to the intentionally broken output CSV.",
    )
    args = parser.parse_args()

    for label, path in {
        "GOOD": args.good_output,
        "BROKEN": args.broken_output,
    }.items():
        result = evaluate_demo_output(args.dataset, path)
        verdict = result["verdict"]
        score = result["score"]
        reasons = result["reasons"]
        assert isinstance(verdict, str)
        assert isinstance(score, float)
        assert isinstance(reasons, list)
        print(f"{label}: verdict={verdict} score={score:.3f}")
        for reason in reasons:
            print(f"  - {reason}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
