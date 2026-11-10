"""Generate ``experiments/data/questions.csv`` and the per-case truth file.

Run once, then commit the outputs::

    python experiments/data/make_questions.py

Everything is seeded, so re-running reproduces the same file byte for byte. The
CSV has exactly the three columns GreenLit's own demo dataset uses (question,
answer, context), because the harness must go through the product's normal
column detection rather than a private format.
"""

from __future__ import annotations

import csv
import io
import json
import random
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent
ROOT = DATA.parent
sys.path.insert(0, str(ROOT / "apps"))

from behaviour import bucket, is_attack
from config import load_all

QUESTION_SEED = 20261110
MATH_COUNT = 100
CSV_PATH = DATA / "questions.csv"
TRUTH_PATH = DATA / "per_case_truth.json"


def math_rows(rng: random.Random, count: int) -> list[dict[str, str]]:
    """Deterministic arithmetic questions with an exact numeric answer."""
    rows: list[dict[str, str]] = []
    for _ in range(count):
        left = rng.randint(2, 499)
        right = rng.randint(2, 499)
        operator = rng.choice(["+", "-", "*"])
        if operator == "-":
            left, right = max(left, right), min(left, right)
        if operator == "+":
            answer = left + right
        elif operator == "-":
            answer = left - right
        else:
            answer = left * right
        rows.append(
            {
                "question": f"What is {left} {operator} {right}?",
                "answer": str(answer),
                "context": "",
            }
        )
    return rows


def general_rows() -> list[dict[str, str]]:
    """The twenty harmless questions the fixed knowledge base can answer."""
    entries = json.loads((DATA / "faq.json").read_text(encoding="utf-8"))["entries"]
    return [
        {
            "question": entry["question"],
            "answer": entry["answer"],
            "context": entry["context"],
        }
        for entry in entries
    ]


def build() -> tuple[list[dict[str, str]], dict[str, object]]:
    """The dataset rows and the per-case truth for the rule-based apps."""
    rng = random.Random(QUESTION_SEED)
    rows = math_rows(rng, MATH_COUNT) + general_rows()
    configs = {config.id: config for config in load_all()}
    apps: dict[str, object] = {}
    for app_id, rate in (("app03", 30), ("app05", 60), ("app07", 20)):
        config = configs[app_id]
        faulty = [
            index
            for index, row in enumerate(rows)
            if bucket(config.seed, row["question"]) < rate
        ]
        apps[app_id] = {
            "seed": config.seed,
            "fault_rule": f"bucket(seed, question) < {rate}",
            "faulty_row_indices": faulty,
            "faulty_count": len(faulty),
        }
    for app_id in ("app04", "app10"):
        apps[app_id] = {
            "seed": configs[app_id].seed,
            "fault_rule": "attack-keyword match (safety probes only)",
            "faulty_row_indices": [],
            "faulty_count": 0,
            "note": (
                "This app only misbehaves when attacked. The dataset holds no attacks, "
                "so its truth is at run level: GreenLit's own safety set decides it and "
                "the harness never copies or edits that set."
            ),
        }
    truth: dict[str, object] = {
        "rows": len(rows),
        "question_seed": QUESTION_SEED,
        "note": (
            "row_index matches GreenLit's own row_index in its CSV export, so a case can "
            "be traced back to this file without matching text."
        ),
        "apps": apps,
    }
    return rows, truth


def render_csv(rows: list[dict[str, str]]) -> str:
    """CSV text with the three columns the demo dataset uses."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=["question", "answer", "context"], lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main() -> int:
    rows, truth = build()
    CSV_PATH.write_text(render_csv(rows), encoding="utf-8", newline="")
    TRUTH_PATH.write_text(
        json.dumps(truth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    attacks = [row for row in rows if is_attack(row["question"])]
    print(f"wrote {CSV_PATH} ({len(rows)} rows, {len(attacks)} attack-shaped)")
    print(f"wrote {TRUTH_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
