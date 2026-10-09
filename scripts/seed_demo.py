from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_demo_states() -> dict[str, dict[str, Any]]:
    return {
        "GOOD": {
            "name": "GOOD",
            "outcome": "GO",
            "status": "GO",
            "summary": "Meets all hard gates and quality thresholds.",
            "checks": [
                {"name": "safety", "status": "PASS"},
                {"name": "schema", "status": "PASS"},
                {"name": "latency", "status": "PASS"},
            ],
            "score": 0.94,
            "reason": "Strong answer quality and no critical failures.",
        },
        "BROKEN": {
            "name": "BROKEN",
            "outcome": "NO_GO",
            "status": "NO_GO",
            "summary": "Fails the launch gate for safety and output validity.",
            "checks": [
                {"name": "safety", "status": "BLOCK"},
                {"name": "schema", "status": "BLOCK"},
                {"name": "latency", "status": "WARN"},
            ],
            "score": 0.41,
            "reason": "Multiple hard-gate failures and low score stability.",
        },
        "REGRESSING": {
            "name": "REGRESSING",
            "outcome": "BLOCK",
            "status": "BLOCK",
            "summary": "Regression against the approved baseline is still active.",
            "checks": [
                {"name": "baseline-compare", "status": "BLOCK"},
                {"name": "safety", "status": "WARN"},
                {"name": "latency", "status": "PASS"},
            ],
            "score": 0.62,
            "reason": "Candidate slipped relative to the approved baseline.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create demo seed data for Phase 9.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/seed-demo.json"),
        help="Where to write the JSON summary.",
    )
    args = parser.parse_args()

    payload = {
        "seeded_states": build_demo_states(),
        "generated_at": "2026-10-09T00:00:00Z",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"states": sorted(payload["seeded_states"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
