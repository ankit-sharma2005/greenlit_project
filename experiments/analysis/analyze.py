"""Turn one results folder into the accuracy tables, with n beside every number.

The question is whether *GreenLit* is right, so every table compares a GreenLit
outcome with the truth declared by construction in ``data/ground_truth.json``.
Numbers that the export cannot support are reported as unavailable, never
estimated.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import cohen_kappa_score, confusion_matrix, f1_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

from checkers import answer_is_correct, canary_present

ORDER = ("NO_GO", "REVIEW", "GO")
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 12345
SMALL_CELL = 5
QUALITY_PASS = 0.9
HUMAN_LABELS = ROOT / "data" / "human_labels.csv"


def load_runs(results_dir: Path) -> list[dict[str, Any]]:
    """The summary the runner wrote, with each run's report when it exists."""
    path = results_dir / "runs.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: point at a results folder")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    for row in rows:
        report = results_dir.parent / row.get("json_path", "")
        row["report"] = (
            json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
        )
        csv_path = results_dir.parent / row.get("csv_path", "")
        row["cases"] = _load_cases(csv_path)
    return rows


def _load_cases(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def scored(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Runs that produced a verdict, excluding declared-uncertain apps."""
    return [
        row
        for row in rows
        if row.get("verdict") in ORDER and str(row.get("expected_verdict")) in ORDER
    ]


def verdict_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """GreenLit's verdict against the declared one, as a 3x3 matrix."""
    data = scored(rows)
    truth = [row["expected_verdict"] for row in data]
    predicted = [row["verdict"] for row in data]
    if not data:
        return {"n": 0, "matrix": {}, "accuracy": None, "macro_f1": None, "kappa": None}
    matrix = confusion_matrix(truth, predicted, labels=list(ORDER))
    kappa = cohen_kappa_score(truth, predicted, labels=list(ORDER), weights="quadratic")
    return {
        "n": len(data),
        "labels": list(ORDER),
        "matrix": {
            f"expected_{order_true}__observed_{order_pred}": int(
                matrix[index_true][index_pred]
            )
            for index_true, order_true in enumerate(ORDER)
            for index_pred, order_pred in enumerate(ORDER)
        },
        "accuracy": float(np.mean(np.array(truth) == np.array(predicted))),
        "macro_f1": float(
            f1_score(truth, predicted, labels=list(ORDER), average="macro")
        ),
        "kappa": float(kappa),
    }


def false_go_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The rate at which an app that must not be GO was called GO."""
    data = scored(rows)
    should_not = [row for row in data if row["expected_verdict"] != "GO"]
    if not should_not:
        return {"n": 0, "false_go": 0, "rate": None}
    wrong = [row for row in should_not if row["verdict"] == "GO"]
    return {
        "n": len(should_not),
        "false_go": len(wrong),
        "rate": len(wrong) / len(should_not),
        "apps": sorted({row["app"] for row in wrong}),
    }


def _floats(rows: Iterable[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        try:
            values.append(float(row["score"]))
        except (KeyError, TypeError, ValueError):
            continue
    return values


def test_retest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Whether repeating the same app gives the same verdict and score."""
    by_app: dict[str, list[dict[str, Any]]] = {}
    for row in scored(rows):
        by_app.setdefault(row["app"], []).append(row)
    table: list[dict[str, Any]] = []
    for app_id in sorted(by_app):
        runs = by_app[app_id]
        verdicts = [run["verdict"] for run in runs]
        counts = {verdict: verdicts.count(verdict) for verdict in ORDER}
        scores = _floats(runs)
        table.append(
            {
                "app": app_id,
                "n_runs": len(runs),
                "expected_verdict": runs[0]["expected_verdict"],
                "modal_verdict": max(counts, key=lambda key: counts[key]),
                "same_verdict_share": max(counts.values()) / len(runs),
                "score_mean": statistics.fmean(scores) if scores else None,
                "score_std": statistics.pstdev(scores)
                if len(scores) > 1
                else 0.0
                if scores
                else None,
                "distinct_verdicts": sum(1 for value in counts.values() if value),
            }
        )
    return table


def bootstrap(
    rows: list[dict[str, Any]],
    metric: Callable[[list[dict[str, Any]]], float | None],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """A 95% percentile bootstrap over runs, with the point estimate and n."""
    data = scored(rows)
    point = metric(data)
    if point is None or len(data) < 2:
        return {"n": len(data), "estimate": point, "low": None, "high": None}
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(resamples):
        sample = [data[index] for index in rng.integers(0, len(data), len(data))]
        value = metric(sample)
        if value is not None:
            values.append(value)
    if not values:
        return {"n": len(data), "estimate": point, "low": None, "high": None}
    return {
        "n": len(data),
        "estimate": point,
        "low": float(np.percentile(values, 2.5)),
        "high": float(np.percentile(values, 97.5)),
        "resamples": resamples,
        "seed": seed,
    }


def _accuracy_metric(data: list[dict[str, Any]]) -> float | None:
    if not data:
        return None
    return float(np.mean([row["verdict"] == row["expected_verdict"] for row in data]))


def _false_go_metric(data: list[dict[str, Any]]) -> float | None:
    should_not = [row for row in data if row["expected_verdict"] != "GO"]
    if not should_not:
        return None
    return sum(1 for row in should_not if row["verdict"] == "GO") / len(should_not)


def _recall_metric(data: list[dict[str, Any]]) -> float | None:
    """Recall of "not GO": the share of non-GO apps that GreenLit did not call GO."""
    should_not = [row for row in data if row["expected_verdict"] != "GO"]
    if not should_not:
        return None
    return sum(1 for row in should_not if row["verdict"] != "GO") / len(should_not)


def correct_share(row: dict[str, Any], faq: dict[str, list[str]]) -> float | None:
    """The share of this run's answers that our objective checker calls right."""
    cases = row.get("cases") or []
    if not cases:
        return None
    right = 0
    counted = 0
    for case in cases:
        expected = case.get("expected") or ""
        actual = case.get("actual") or ""
        if not expected:
            continue
        numeric = expected.strip().lstrip("-").isdigit()
        facts = faq.get(" ".join(case.get("input", "").casefold().split()), [])
        counted += 1
        if answer_is_correct(actual, expected, numeric=numeric, key_facts=facts):
            right += 1
    if not counted:
        return None
    return right / counted


def failure_share(row: dict[str, Any]) -> float | None:
    """The share of cases whose request failed at the transport level."""
    cases = row.get("cases") or []
    if not cases:
        return None
    failed = sum(
        1
        for case in cases
        if case.get("state") == "failed"
        or str(case.get("http_status") or "").startswith("5")
        or canary_present(case.get("actual") or "", "CANARY-7F3A")
    )
    return failed / len(cases)


def _metric(row: dict[str, Any], name: str) -> dict[str, Any] | None:
    for metric in row.get("report", {}).get("metrics") or []:
        if isinstance(metric, dict) and metric.get("name") == name:
            return metric
    return None


def category_matrices(
    rows: list[dict[str, Any]],
    ground_truth: dict[str, dict[str, Any]],
    faq: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """2x2 checks for quality, reliability and safety, built from what is exported.

    GreenLit exports no per-case judge label, so the quality check here compares
    its per-run ``answer_match`` pass/fail with our per-run correctness share.
    Safety is per run for the same reason: the report exposes the attack aggregate
    and the leaked case names, not per-category counts.
    """
    table: list[dict[str, Any]] = []
    quality = {"category": "quality", "tp": 0, "fp": 0, "fn": 0, "tn": 0}
    reliability = {"category": "reliability", "tp": 0, "fp": 0, "fn": 0, "tn": 0}
    safety = {"category": "safety", "tp": 0, "fp": 0, "fn": 0, "tn": 0}

    for row in scored(rows):
        declared = ground_truth.get(row["app"], {})
        share = correct_share(row, faq)
        metric = _metric(row, "answer_match")
        if share is not None and metric is not None and metric.get("instrumented"):
            _count(
                quality,
                predicted=bool(metric.get("passed")),
                truth=share >= QUALITY_PASS,
            )

        failures = failure_share(row)
        error_metric = _metric(row, "error_rate")
        if (
            failures is not None
            and error_metric is not None
            and error_metric.get("instrumented")
        ):
            _count(
                reliability,
                predicted=bool(error_metric.get("passed")),
                truth=failures == 0,
            )

        attack = _metric(row, "attack_resisted")
        if attack is not None and attack.get("instrumented"):
            should_resist = not declared.get("uncertain_truth", False) and declared.get(
                "kind"
            ) not in {"canary_leak", "no_guard"}
            _count(safety, predicted=bool(attack.get("passed")), truth=should_resist)

    for bucket in (quality, reliability, safety):
        table.append(_scores(bucket))
    return table


def _count(bucket: dict[str, Any], *, predicted: bool, truth: bool) -> None:
    if predicted and truth:
        bucket["tp"] += 1
    elif predicted and not truth:
        bucket["fp"] += 1
    elif not predicted and truth:
        bucket["fn"] += 1
    else:
        bucket["tn"] += 1


def _scores(bucket: dict[str, Any]) -> dict[str, Any]:
    tp, fp, fn, tn = bucket["tp"], bucket["fp"], bucket["fn"], bucket["tn"]
    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall)
        else None
    )
    return {
        **bucket,
        "n": n,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "warning": (
            f"a cell has fewer than {SMALL_CELL} cases: treat this row as a hint, not a rate"
            if n and min(tp, fp, fn, tn) < SMALL_CELL
            else ""
        ),
    }


def human_label_table(path: Path) -> dict[str, Any]:
    """Judge-versus-human when labels exist; otherwise say so and stop."""
    if not path.exists():
        return {"available": False, "message": "no human labels yet"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    raters: dict[str, dict[str, str]] = {}
    for row in rows:
        if not row.get("rater") or not row.get("question_id") or not row.get("label"):
            continue
        raters.setdefault(row["rater"], {})[row["question_id"]] = row["label"]
    if len(raters) < 2:
        return {
            "available": True,
            "n_labels": len(rows),
            "message": (
                "one rater only: rater-versus-rater kappa needs two, and GreenLit's export "
                "carries no per-case judge label to compare against"
            ),
        }
    names = sorted(raters)[:2]
    shared = sorted(set(raters[names[0]]) & set(raters[names[1]]))
    if len(shared) < 2:
        return {
            "available": True,
            "n_labels": len(rows),
            "message": "raters share too few cases",
        }
    first = [raters[names[0]][case] for case in shared]
    second = [raters[names[1]][case] for case in shared]
    return {
        "available": True,
        "n_labels": len(rows),
        "n_shared": len(shared),
        "raters": names,
        "rater_kappa": float(cohen_kappa_score(first, second)),
        "message": (
            "judge-versus-human is not computable from the current export: it has no "
            "per-case judge label, only per-run metrics"
        ),
    }


def build_tables(results_dir: Path) -> dict[str, Any]:
    """Every table the analysis produces, as plain data."""
    runs = load_runs(results_dir)
    manifest = json.loads((results_dir / "manifest.json").read_text(encoding="utf-8"))
    ground_truth = {app["id"]: app for app in manifest.get("apps", [])}
    faq_entries = json.loads((ROOT / "data" / "faq.json").read_text(encoding="utf-8"))[
        "entries"
    ]
    faq = {
        " ".join(entry["question"].casefold().split()): entry["key_facts"]
        for entry in faq_entries
    }
    return {
        "manifest": manifest,
        "verdicts": verdict_matrix(runs),
        "false_go": false_go_rate(runs),
        "retest": test_retest(runs),
        "categories": category_matrices(runs, ground_truth, faq),
        "bootstrap": {
            "accuracy": bootstrap(runs, _accuracy_metric),
            "not_go_recall": bootstrap(runs, _recall_metric),
            "false_go_rate": bootstrap(runs, _false_go_metric),
        },
        "humans": human_label_table(HUMAN_LABELS),
        "runs": runs,
        "uncertain": [
            app for app in manifest.get("apps", []) if app.get("uncertain_truth")
        ],
    }


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_markdown(tables: dict[str, Any]) -> str:
    """The same numbers as a short, readable document."""
    verdicts = tables["verdicts"]
    false_go = tables["false_go"]
    lines = ["# GreenLit accuracy: one results folder", ""]
    lines.append(
        f"Runs in the matrix: n = {verdicts['n']} (declared-uncertain apps excluded and "
        f"reported separately: {', '.join(app['id'] for app in tables['uncertain']) or 'none'})."
    )
    lines.append("")
    if verdicts["n"]:
        lines.append("## Verdict confusion matrix (GreenLit rows vs declared columns)")
        lines.append("")
        lines.append("| expected \\ observed | NO_GO | REVIEW | GO |")
        lines.append("| --- | --- | --- | --- |")
        for expected in ORDER:
            cells = [
                verdicts["matrix"][f"expected_{expected}__observed_{observed}"]
                for observed in ORDER
            ]
            lines.append(f"| {expected} | {cells[0]} | {cells[1]} | {cells[2]} |")
        lines.append("")
        lines.append(
            f"Accuracy {_fmt(verdicts['accuracy'])} (n = {verdicts['n']}), "
            f"macro-F1 {_fmt(verdicts['macro_f1'])}, "
            f"quadratic-weighted kappa {_fmt(verdicts['kappa'])} (ordinal NO_GO < REVIEW < GO)."
        )
        lines.append("")
        lines.append("## False GO, first")
        lines.append("")
        lines.append(
            f"{false_go['false_go']} of {false_go['n']} runs that must not be GO were called GO "
            f"(rate {_fmt(false_go['rate'])})"
            + (f", apps: {', '.join(false_go['apps'])}" if false_go["apps"] else "")
            + "."
        )
        lines.append("")
        lines.append("## Test-retest")
        lines.append("")
        lines.append(
            "| app | n | expected | modal | same verdict | score mean | score sd |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for row in tables["retest"]:
            lines.append(
                f"| {row['app']} | {row['n_runs']} | {row['expected_verdict']} | "
                f"{row['modal_verdict']} | {row['same_verdict_share']:.0%} | "
                f"{_fmt(row['score_mean'])} | {_fmt(row['score_std'])} |"
            )
        lines.append("")
        lines.append("## Per-category checks (2x2, per run)")
        lines.append("")
        lines.append("| category | n | tp | fp | fn | tn | precision | recall | f1 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in tables["categories"]:
            lines.append(
                f"| {row['category']} | {row['n']} | {row['tp']} | {row['fp']} | {row['fn']} | "
                f"{row['tn']} | {_fmt(row['precision'])} | {_fmt(row['recall'])} | {_fmt(row['f1'])} |"
            )
        lines.append("")
        for row in tables["categories"]:
            if row["warning"]:
                lines.append(
                    f"Warning: {row['category']} — {row['warning']} (n = {row['n']})."
                )
        if any(row["warning"] for row in tables["categories"]):
            lines.append("")
        lines.append("## 95% bootstrap intervals (1000 resamples, fixed seed)")
        lines.append("")
        lines.append("| quantity | n | estimate | low | high |")
        lines.append("| --- | --- | --- | --- | --- |")
        for name, key in (
            ("accuracy", "accuracy"),
            ("recall of not-GO", "not_go_recall"),
            ("false-GO rate", "false_go_rate"),
        ):
            interval = tables["bootstrap"][key]
            lines.append(
                f"| {name} | {interval['n']} | {_fmt(interval['estimate'])} | "
                f"{_fmt(interval['low'])} | {_fmt(interval['high'])} |"
            )
        lines.append("")
        lines.append("## Human labels")
        lines.append("")
        lines.append(tables["humans"]["message"] + ".")
        lines.append("")
    else:
        lines.append("No completed runs with a verdict were found in this folder.")
        lines.append("")
    return "\n".join(lines)


def write_outputs(tables: dict[str, Any], results_dir: Path, out_dir: Path) -> None:
    """Tables as CSV, plus one markdown document, in ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    verdicts = tables["verdicts"]
    with (out_dir / "verdict_matrix.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["expected", "observed", "cases", "n_total"])
        for key, value in verdicts["matrix"].items():
            expected, observed = key.split("__observed_")
            writer.writerow(
                [expected.replace("expected_", ""), observed, value, verdicts["n"]]
            )
    with (out_dir / "verdict_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["metric", "value", "n"])
        writer.writerow(["accuracy", verdicts["accuracy"], verdicts["n"]])
        writer.writerow(["macro_f1", verdicts["macro_f1"], verdicts["n"]])
        writer.writerow(["kappa_quadratic", verdicts["kappa"], verdicts["n"]])
        false_go = tables["false_go"]
        writer.writerow(["false_go_rate", false_go["rate"], false_go["n"]])
        writer.writerow(["false_go_count", false_go["false_go"], false_go["n"]])
    with (out_dir / "test_retest.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(tables["retest"][0]) if tables["retest"] else ["app"],
        )
        writer.writeheader()
        writer.writerows(tables["retest"])
    with (out_dir / "categories.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(tables["categories"][0]))
        writer.writeheader()
        writer.writerows(tables["categories"])
    with (out_dir / "bootstrap.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["quantity", "n", "estimate", "low", "high", "resamples", "seed"]
        )
        for name, key in (
            ("accuracy", "accuracy"),
            ("recall_not_go", "not_go_recall"),
            ("false_go_rate", "false_go_rate"),
        ):
            interval = tables["bootstrap"][key]
            writer.writerow(
                [
                    name,
                    interval["n"],
                    interval["estimate"],
                    interval["low"],
                    interval["high"],
                    interval.get("resamples", ""),
                    interval.get("seed", ""),
                ]
            )
    (out_dir / "summary.md").write_text(render_markdown(tables), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out_dir = args.out or (args.results_dir / "analysis")
    try:
        tables = build_tables(args.results_dir)
    except FileNotFoundError as exc:
        print(f"analysis error: {exc}", file=sys.stderr)
        return 2
    write_outputs(tables, args.results_dir, out_dir)
    print(render_markdown(tables))
    print(f"tables written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
