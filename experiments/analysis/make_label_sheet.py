"""A blind label sheet for one person, and the merge that turns two into a file.

A sheet is deliberately blind: each row is a question, the answer an app gave, and
an empty ``label`` cell. Nothing else — no app id, no judge label, no verdict — and
the rows are shuffled with a fixed seed so a run of good or bad answers cannot be
labelled by pattern.

``question_id`` is ``<app id>.<dataset row>`` (for example ``app04.17``): the label
is about *that* app's answer to *that* question, and the analysis matches it to the
judge's per-case label with the same key.

    python experiments/analysis/make_label_sheet.py results/<timestamp> --rater alice
    python experiments/analysis/make_label_sheet.py results/<timestamp> --rater bob
    python experiments/analysis/make_label_sheet.py --merge sheets/alice.csv \\
        sheets/bob.csv --out data/human_labels.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET_COLUMNS = ("question_id", "question", "app_answer", "label")
LABEL_COLUMNS = ("question_id", "rater", "label")
LABELS = {"pass", "fail", "unsure"}


def app_ids(results_dir: Path) -> list[str]:
    """The apps that have an exported report in this results folder."""
    return sorted(path.name for path in results_dir.glob("*/run-*.report.json"))


def blind_rows(results_dir: Path, apps: list[str]) -> list[dict[str, str]]:
    """One row per case, from the first run of each chosen app."""
    rows: list[dict[str, str]] = []
    for app in apps:
        report = results_dir / app / "run-1.report.json"
        if not report.exists():
            paths = sorted((results_dir / app).glob("run-*.report.json"))
            if not paths:
                continue
            report = paths[0]
        document = json.loads(report.read_text(encoding="utf-8"))
        for case in document.get("cases") or []:
            row_index = case.get("row_index")
            if row_index is None:
                continue
            rows.append(
                {
                    "question_id": f"{app}.{row_index}",
                    "question": str(case.get("input") or ""),
                    "app_answer": str(case.get("output") or ""),
                    "label": "",
                }
            )
    return rows


def write_sheet(
    path: Path,
    rows: list[dict[str, str]],
    *,
    seed: int,
    limit: int | None = None,
) -> int:
    """Shuffle and write the sheet; returns how many rows it holds."""
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    if limit is not None:
        shuffled = shuffled[:limit]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(shuffled)
    return len(shuffled)


def merge_sheets(paths: list[Path], out: Path) -> dict[str, int]:
    """Combine filled sheets into ``question_id, rater, label``.

    The rater's name is the sheet's file stem, a row with an empty label is not a
    label and is skipped, and a value outside pass/fail/unsure is refused rather
    than guessed at.
    """
    written: dict[str, int] = {}
    lines: list[dict[str, str]] = []
    for path in paths:
        rater = path.stem
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                label = (row.get("label") or "").strip().lower()
                question_id = (row.get("question_id") or "").strip()
                if not label:
                    continue
                if label not in LABELS:
                    raise ValueError(
                        f"{path.name}: label {label!r} is not pass, fail or unsure"
                    )
                if not question_id:
                    continue
                lines.append(
                    {"question_id": question_id, "rater": rater, "label": label}
                )
        written[rater] = sum(1 for line in lines if line["rater"] == rater)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LABEL_COLUMNS))
        writer.writeheader()
        writer.writerows(lines)
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path, nargs="?", default=None)
    parser.add_argument("--rater", default=None, help="whose sheet this is")
    parser.add_argument(
        "--app",
        action="append",
        default=None,
        help="limit the sheet to one app (repeatable); default: every app",
    )
    parser.add_argument("--seed", type=int, default=20261110)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--merge",
        nargs="+",
        type=Path,
        default=None,
        metavar="SHEET",
        help="merge filled sheets (the file stem is the rater) instead of writing one",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.merge:
        out = args.out or (ROOT / "data" / "human_labels.csv")
        try:
            written = merge_sheets(list(args.merge), out)
        except ValueError as exc:
            print(f"label sheet error: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {out} ({sum(written.values())} labels): {written}")
        return 0
    if args.results_dir is None or not args.rater:
        print(
            "a results folder and --rater are required to write a sheet",
            file=sys.stderr,
        )
        return 2
    apps = args.app or app_ids(args.results_dir)
    rows = blind_rows(args.results_dir, apps)
    if not rows:
        print(
            f"no exported reports under {args.results_dir}: run the experiment first",
            file=sys.stderr,
        )
        return 2
    out = args.out or (args.results_dir / "label_sheets" / f"{args.rater}.csv")
    count = write_sheet(out, rows, seed=args.seed, limit=args.limit)
    print(f"wrote {out} ({count} cases from {len(apps)} app(s), blind, shuffled)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
