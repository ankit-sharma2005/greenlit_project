"""Write ``experiments/data/ground_truth.json`` from the declared app configs.

Run before any experiment, and re-run whenever a config changes::

    python experiments/build_ground_truth.py

The file is deterministic (no timestamps), so a diff shows exactly which
declaration changed. The runner refuses to start if this file is missing an app
or contradicts a config, which is what keeps "expected" from being decided after
the fact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "apps"))

from config import ConfigError, load_all

TRUTH_PATH = ROOT / "data" / "ground_truth.json"


def build() -> dict[str, object]:
    """The whole declared ground truth, in id order."""
    apps = [config.ground_truth_entry() for config in load_all()]
    return {
        "experiment": "greenlit-accuracy",
        "version": 1,
        "declared": "before any GreenLit run; every verdict comes from the design, not from a result",
        "apps": apps,
    }


def main() -> int:
    try:
        document = build()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRUTH_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {TRUTH_PATH} ({len(document['apps'])} apps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
