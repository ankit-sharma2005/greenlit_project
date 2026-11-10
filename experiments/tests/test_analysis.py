"""The analysis maths, checked against values computed by hand on a tiny folder."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import analyze
import numpy as np
import pytest

ORDER = ("NO_GO", "REVIEW", "GO")


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _cases(path: Path, answers: list[tuple[str, str, str]]) -> None:
    _write_csv(
        path,
        ["row_index", "input", "expected", "actual", "state", "http_status", "verdict"],
        [
            [index, question, expected, actual, "completed", "", "GO"]
            for index, (question, expected, actual) in enumerate(answers)
        ],
    )


def _report(path: Path, metrics: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"metrics": metrics}), encoding="utf-8")


def build_fixture(root: Path) -> Path:
    """Five scored runs (plus one uncertain) whose answers are known by hand."""
    results = root / "20260101T000000Z"
    results.mkdir(parents=True, exist_ok=True)
    runs = [
        ("app01", 1, "completed", "GO", "0.95", "GO"),
        ("app01", 2, "completed", "GO", "0.95", "GO"),
        ("app03", 1, "completed", "GO", "0.88", "NO_GO"),
        ("app04", 1, "completed", "NO_GO", "0.20", "NO_GO"),
        ("app06", 1, "completed", "REVIEW", "0.70", "REVIEW"),
        ("app02", 1, "completed", "GO", "0.91", "UNCERTAIN"),
    ]
    rows = []
    for app, index, state, verdict, score, expected in runs:
        csv_rel = f"{results.name}/{app}/run-{index}.csv"
        json_rel = f"{results.name}/{app}/run-{index}.report.json"
        rows.append(
            [
                app,
                index,
                f"run-{app}-{index}",
                state,
                verdict,
                score,
                expected,
                "rule 5",
                csv_rel,
                json_rel,
            ]
        )
    _write_csv(
        results / "runs.csv",
        [
            "app",
            "run_index",
            "run_id",
            "state",
            "verdict",
            "score",
            "expected_verdict",
            "verdict_reason",
            "csv_path",
            "json_path",
        ],
        rows,
    )
    _cases(
        results / "app01" / "run-1.csv",
        [
            ("What is 2 + 2?", "4", "4"),
            (
                "What time does the library open?",
                "The library opens at 8am.",
                "It opens at 8am.",
            ),
        ],
    )
    _cases(results / "app01" / "run-2.csv", [("What is 2 + 2?", "4", "4")])
    _cases(
        results / "app03" / "run-1.csv",
        [("What is 2 + 2?", "4", "5"), ("What is 3 + 3?", "6", "7")],
    )
    _cases(results / "app04" / "run-1.csv", [("What is 2 + 2?", "4", "4")])
    _cases(results / "app06" / "run-1.csv", [("What is 2 + 2?", "4", "4")])
    metrics_ok = [
        {"name": "answer_match", "instrumented": True, "passed": True},
        {"name": "error_rate", "instrumented": True, "passed": True},
        {"name": "attack_resisted", "instrumented": True, "passed": True},
    ]
    _report(results / "app01" / "run-1.report.json", metrics_ok)
    _report(results / "app01" / "run-2.report.json", metrics_ok)
    _report(
        results / "app03" / "run-1.report.json",
        [
            {"name": "answer_match", "instrumented": True, "passed": False},
            {"name": "error_rate", "instrumented": True, "passed": True},
            {"name": "attack_resisted", "instrumented": True, "passed": True},
        ],
    )
    _report(
        results / "app04" / "run-1.report.json",
        [
            {"name": "answer_match", "instrumented": True, "passed": True},
            {"name": "error_rate", "instrumented": True, "passed": True},
            {"name": "attack_resisted", "instrumented": True, "passed": False},
        ],
    )
    _report(
        results / "app06" / "run-1.report.json",
        [
            {"name": "answer_match", "instrumented": True, "passed": True},
            {"name": "error_rate", "instrumented": True, "passed": True},
            {"name": "attack_resisted", "instrumented": True, "passed": True},
        ],
    )
    manifest = {
        "experiment": "greenlit-accuracy",
        "runs_per_app": 1,
        "apps": [
            {
                "id": "app01",
                "expected_verdict": "GO",
                "kind": "math",
                "uncertain_truth": False,
            },
            {
                "id": "app02",
                "expected_verdict": "UNCERTAIN",
                "kind": "llm_math",
                "uncertain_truth": True,
            },
            {
                "id": "app03",
                "expected_verdict": "NO_GO",
                "kind": "numeric_wrong",
                "uncertain_truth": False,
            },
            {
                "id": "app04",
                "expected_verdict": "NO_GO",
                "kind": "canary_leak",
                "uncertain_truth": False,
            },
            {
                "id": "app06",
                "expected_verdict": "REVIEW",
                "kind": "slow",
                "uncertain_truth": False,
            },
        ],
        "judge": {"provider_name": "ollama", "model": "llama3"},
    }
    (results / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return results


def hand_kappa(truth: list[str], predicted: list[str]) -> float:
    """Quadratic-weighted kappa, written out rather than imported."""
    index = {label: position for position, label in enumerate(ORDER)}
    size = len(ORDER)
    observed = np.zeros((size, size))
    for expected, actual in zip(truth, predicted, strict=True):
        observed[index[expected]][index[actual]] += 1
    total = observed.sum()
    weights = np.array(
        [[(i - j) ** 2 / (size - 1) ** 2 for j in range(size)] for i in range(size)]
    )
    expected_matrix = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / total
    return float(1 - (weights * observed).sum() / (weights * expected_matrix).sum())


@pytest.fixture()
def tables(tmp_path: Path) -> dict[str, Any]:
    return analyze.build_tables(build_fixture(tmp_path))


def test_the_matrix_matches_the_hand_count(tables: dict[str, Any]) -> None:
    matrix = tables["verdicts"]["matrix"]
    assert matrix["expected_NO_GO__observed_NO_GO"] == 1
    assert matrix["expected_NO_GO__observed_GO"] == 1
    assert matrix["expected_REVIEW__observed_REVIEW"] == 1
    assert matrix["expected_GO__observed_GO"] == 2
    assert sum(matrix.values()) == 5
    assert tables["verdicts"]["n"] == 5


def test_the_uncertain_app_is_excluded_and_reported_separately(
    tables: dict[str, Any],
) -> None:
    assert [app["id"] for app in tables["uncertain"]] == ["app02"]
    assert tables["runs"], "the raw runs are still loaded"
    assert all(row["app"] != "app02" for row in analyze.scored(tables["runs"]))


def test_accuracy_macro_f1_and_kappa_match_the_hand_values(
    tables: dict[str, Any],
) -> None:
    assert tables["verdicts"]["accuracy"] == pytest.approx(4 / 5)
    one = 2 * 1.0 * 0.5 / 1.5
    go = 2 * (2 / 3) * 1.0 / (2 / 3 + 1.0)
    assert tables["verdicts"]["macro_f1"] == pytest.approx((one + 1.0 + go) / 3)
    truth = ["GO", "GO", "NO_GO", "NO_GO", "REVIEW"]
    predicted = ["GO", "GO", "GO", "NO_GO", "REVIEW"]
    assert tables["verdicts"]["kappa"] == pytest.approx(hand_kappa(truth, predicted))


def test_the_false_go_rate_is_one_of_three(tables: dict[str, Any]) -> None:
    false_go = tables["false_go"]
    assert false_go["n"] == 3
    assert false_go["false_go"] == 1
    assert false_go["rate"] == pytest.approx(1 / 3)
    assert false_go["apps"] == ["app03"]


def test_test_retest_reports_each_app_with_its_n(tables: dict[str, Any]) -> None:
    by_app = {row["app"]: row for row in tables["retest"]}
    assert by_app["app01"]["n_runs"] == 2
    assert by_app["app01"]["same_verdict_share"] == 1.0
    assert by_app["app01"]["score_mean"] == pytest.approx(0.95)
    assert by_app["app01"]["score_std"] == 0.0
    assert by_app["app03"]["n_runs"] == 1


def test_category_matrices_are_counted_per_run(tables: dict[str, Any]) -> None:
    by_name = {row["category"]: row for row in tables["categories"]}
    # app01 twice, app03, app04 and app06 all have cases and a passed answer_match:
    # four are right and pass, app03 is wrong and fails.
    assert (
        by_name["quality"]["n"],
        by_name["quality"]["tp"],
        by_name["quality"]["tn"],
    ) == (5, 4, 1)
    assert by_name["quality"]["precision"] == 1.0
    assert by_name["quality"]["recall"] == 1.0
    assert (
        by_name["safety"]["n"],
        by_name["safety"]["tp"],
        by_name["safety"]["tn"],
    ) == (5, 4, 1)
    assert by_name["reliability"]["n"] == 5
    assert "fewer than 5 cases" in by_name["quality"]["warning"]


def test_bootstrap_intervals_bracket_the_point_estimate_and_are_reproducible(
    tmp_path: Path,
) -> None:
    results = build_fixture(tmp_path)
    rows = analyze.load_runs(results)
    first = analyze.bootstrap(rows, analyze._accuracy_metric)
    second = analyze.bootstrap(rows, analyze._accuracy_metric)
    assert first["n"] == 5
    assert first["estimate"] == pytest.approx(0.8)
    assert first["low"] <= first["estimate"] <= first["high"]
    assert (first["low"], first["high"]) == (second["low"], second["high"])
    assert first["resamples"] == 1000


def test_human_labels_absent_says_so_instead_of_inventing(tmp_path: Path) -> None:
    table = analyze.human_label_table(tmp_path / "missing.csv")
    assert table["available"] is False
    assert table["message"] == "no human labels yet"


def test_only_one_rater_is_reported_as_insufficient(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    _write_csv(
        path,
        ["question_id", "label", "rater"],
        [["q1", "pass", "ada"], ["q2", "fail", "ada"]],
    )
    table = analyze.human_label_table(path)
    assert table["available"] is True
    assert "one rater only" in table["message"]


def test_two_raters_get_a_kappa(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    _write_csv(
        path,
        ["question_id", "label", "rater"],
        [
            ["q1", "pass", "ada"],
            ["q2", "fail", "ada"],
            ["q3", "pass", "ada"],
            ["q1", "pass", "bob"],
            ["q2", "fail", "bob"],
            ["q3", "fail", "bob"],
        ],
    )
    table = analyze.human_label_table(path)
    assert table["n_shared"] == 3
    # agree on 2 of 3; chance agreement (2/3*1/3 + 1/3*2/3) = 4/9, so (2/3-4/9)/(5/9) = 0.4.
    assert table["rater_kappa"] == pytest.approx(0.4)


def test_the_markdown_carries_n_next_to_every_number(tables: dict[str, Any]) -> None:
    text = analyze.render_markdown(tables)
    assert "n = 5" in text
    assert "False GO, first" in text
    assert "no human labels yet" in text
    assert "quadratic-weighted kappa" in text
