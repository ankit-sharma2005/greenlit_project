"""Judge-versus-human: the numbers are compared with values done by hand.

The runner now saves each case's judge label (``run-N.cases.csv``); a human label
file supplies the other side. Six cases are enough to pin every counter: one
agreement each way, one disagreement each way, an ``unsure`` judge, an ``unsure``
human and a case the judge never scored — and none of the last three may be
counted as pass or fail.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from analyze import judge_human_table

HEADER = ["row_index", "judge_label", "judge_score", "judge_reason"]


def _cases(path: Path, rows: list[tuple[int, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        for row_index, label in rows:
            writer.writerow([row_index, label, "" if not label else "0.9", ""])


def _labels(path: Path, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["question_id", "rater", "label"])
        for question_id, label in rows:
            writer.writerow([question_id, "r1", label])


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    results = tmp_path / "results"
    _cases(
        results / "app01" / "run-1.cases.csv",
        [(1, "pass"), (2, "pass"), (3, "fail"), (4, "unsure"), (5, ""), (6, "pass")],
    )
    return results


def test_the_confusion_is_the_one_worked_out_by_hand(
    folder: Path, tmp_path: Path
) -> None:
    labels = tmp_path / "human_labels.csv"
    _labels(
        labels,
        [("1", "pass"), ("2", "fail"), ("3", "fail"), ("4", "pass"), ("5", "pass")],
    )

    table = judge_human_table(folder, labels)
    row = table["raters"][0]

    assert table["available"] is True
    assert table["positive_class"] == "fail"
    # Row 1 pass/pass (tn), row 2 pass/fail (fn), row 3 fail/fail (tp).
    assert (row["tp"], row["fp"], row["fn"], row["tn"]) == (1, 0, 1, 1)
    assert row["n"] == 3
    assert row["accuracy"] == pytest.approx(2 / 3)
    # Fail is the positive class: every judge fail was a human fail, and it caught
    # one of the human's two.
    assert row["precision"] == pytest.approx(1.0)
    assert row["recall"] == pytest.approx(0.5)
    assert row["f1"] == pytest.approx(2 / 3)
    # judge pass/pass/fail, human pass/fail/fail: po = 2/3, and the marginals are
    # 2:1 the other way round, so pe = (2/3)(1/3) + (1/3)(2/3) = 4/9 and
    # kappa = (2/3 - 4/9) / (5/9) = 0.4.
    assert row["kappa"] == pytest.approx(0.4)


def test_unsure_is_its_own_column_and_never_a_pass_or_fail(
    folder: Path, tmp_path: Path
) -> None:
    labels = tmp_path / "human_labels.csv"
    _labels(
        labels,
        [("1", "pass"), ("2", "fail"), ("3", "fail"), ("4", "pass"), ("6", "unsure")],
    )

    table = judge_human_table(folder, labels)
    row = table["raters"][0]

    # The judge's unsure (row 4) and the human's unsure (row 6) are counted apart.
    assert row["judge_unsure"] == 1
    assert row["human_unsure"] == 1
    # Row 5 has no judge label at all: excluded, not a pass.
    assert row["unjudged"] == 1
    # Row 5's human label exists but is skipped with the unjudged case; rows 4 and 6
    # are skipped as unsure, so three pairs remain.
    assert row["n"] == 3
    assert row["tp"] + row["fp"] + row["fn"] + row["tn"] == 3


def test_without_human_labels_it_says_so_and_counts_what_it_has(folder: Path) -> None:
    table = judge_human_table(folder, Path("does-not-exist.csv"))

    assert table["available"] is False
    assert table["n_cases"] == 6
    assert "no human labels yet" in table["message"]


def test_without_per_case_labels_it_says_what_to_run(tmp_path: Path) -> None:
    table = judge_human_table(tmp_path / "empty", tmp_path / "human_labels.csv")

    assert table["available"] is False
    assert table["n_cases"] == 0
    assert "run-N.cases.csv" in table["message"]


def test_each_rater_gets_its_own_row(folder: Path, tmp_path: Path) -> None:
    labels = tmp_path / "human_labels.csv"
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["question_id", "rater", "label"])
        for question_id, first, second in (
            ("1", "pass", "pass"),
            ("2", "fail", "pass"),
            ("3", "fail", "fail"),
        ):
            writer.writerow([question_id, "r1", first])
            writer.writerow([question_id, "r2", second])

    table = judge_human_table(folder, labels)
    rows = {row["rater"]: row for row in table["raters"]}

    assert set(rows) == {"r1", "r2"}
    assert rows["r1"]["fn"] == 1  # r1 says fail where the judge passed
    # r2 agrees on rows 1 and 2 (both pass) and on row 3 (both fail).
    assert rows["r2"]["tn"] == 2
    assert rows["r2"]["tp"] == 1
    assert rows["r2"]["fp"] == 0 and rows["r2"]["fn"] == 0
