"""The blind sheet and the two-rater merge.

A sheet that leaked the app or the judge's own label would not be blind; a merge
that guessed at a stray value would quietly invent a label. Both are checked here
on a two-case fixture written by hand.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from analyze import judge_human_table
from make_label_sheet import blind_rows, merge_sheets, write_sheet


def _report(results: Path, app: str, cases: list[tuple[int, str, str]]) -> None:
    path = results / app / "run-1.report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "cases": [
            {
                "row_index": index,
                "input": question,
                "output": answer,
                "judge_label": "pass",
            }
            for index, question, answer in cases
        ]
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def results(tmp_path: Path) -> Path:
    folder = tmp_path / "results"
    _report(folder, "app01", [(1, "What is 2 + 2?", "4")])
    _report(folder, "app04", [(1, "What is 2 + 2?", "5")])
    return folder


def test_the_sheet_is_question_answer_and_nothing_else(results: Path) -> None:
    rows = blind_rows(results, ["app04"])

    assert rows == [
        {
            "question_id": "app04.1",
            "question": "What is 2 + 2?",
            "app_answer": "5",
            "label": "",
        }
    ]


def test_the_sheet_holds_no_app_id_and_no_judge_label(
    results: Path, tmp_path: Path
) -> None:
    out = tmp_path / "sheet.csv"
    write_sheet(out, blind_rows(results, ["app01", "app04"]), seed=7)

    with out.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == ["question_id", "question", "app_answer", "label"]
    for row in _read(out):
        assert set(row) == set(header)
        assert "judge" not in " ".join(row).lower()
        assert row["label"] == ""


def test_the_same_seed_shuffles_the_same_way(results: Path, tmp_path: Path) -> None:
    rows = blind_rows(results, ["app01", "app04"])
    first, second, other = tmp_path / "a.csv", tmp_path / "b.csv", tmp_path / "c.csv"
    write_sheet(first, rows, seed=11)
    write_sheet(second, rows, seed=11)
    write_sheet(other, rows, seed=12)

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    # Two rows can shuffle into the same order by chance; the seed is what is claimed,
    # not a guarantee of a different order for a tiny sheet.
    assert sorted(r["question_id"] for r in _read(other)) == ["app01.1", "app04.1"]


def test_merging_two_raters_keeps_the_name_and_skips_empty_cells(
    tmp_path: Path,
) -> None:
    alice = tmp_path / "alice.csv"
    bob = tmp_path / "bob.csv"
    header = "question_id,question,app_answer,label\n"
    alice.write_text(header + "app01.1,q,a,pass\napp04.1,q,b,fail\n", encoding="utf-8")
    bob.write_text(header + "app01.1,q,a,unsure\napp04.1,q,b,\n", encoding="utf-8")

    out = tmp_path / "human_labels.csv"
    written = merge_sheets([alice, bob], out)

    assert written == {"alice": 2, "bob": 1}
    assert _read(out) == [
        {"question_id": "app01.1", "rater": "alice", "label": "pass"},
        {"question_id": "app04.1", "rater": "alice", "label": "fail"},
        {"question_id": "app01.1", "rater": "bob", "label": "unsure"},
    ]


def test_merge_refuses_a_label_outside_the_three_words(tmp_path: Path) -> None:
    sheet = tmp_path / "alice.csv"
    sheet.write_text(
        "question_id,question,app_answer,label\napp01.1,q,a,good\n", "utf-8"
    )

    with pytest.raises(ValueError, match="not pass, fail or unsure"):
        merge_sheets([sheet], tmp_path / "out.csv")


def test_a_sheet_label_meets_the_judge_label_on_the_same_key(
    results: Path, tmp_path: Path
) -> None:
    # The runner's own file, written the way the runner writes it.
    cases = results / "app04" / "run-1.cases.csv"
    with cases.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["row_index", "judge_label", "judge_score", "judge_reason"])
        writer.writerow([1, "fail", 0.1, "wrong number"])

    labels = tmp_path / "human_labels.csv"
    labels.write_text("question_id,rater,label\napp04.1,alice,fail\n", encoding="utf-8")

    table = judge_human_table(results, labels)
    row = table["raters"][0]

    assert table["n_questions"] == 1
    assert (row["tp"], row["fn"]) == (1, 0)
    assert row["accuracy"] == pytest.approx(1.0)
