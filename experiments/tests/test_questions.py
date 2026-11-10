"""The dataset and its per-case truth are seeded, complete and reproducible."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from behaviour import bucket, load_faq
from config import load_all
from make_questions import CSV_PATH, TRUTH_PATH, build, render_csv

DATA = Path(__file__).resolve().parent.parent / "data"
MATH = re.compile(r"^What is -?\d+ [-+*] -?\d+\?$")


def rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_the_committed_file_has_the_expected_shape() -> None:
    data = rows()
    assert len(data) == 120
    assert list(data[0]) == ["question", "answer", "context"]
    assert sum(1 for row in data if MATH.match(row["question"])) == 100
    assert len({row["question"] for row in data}) == 120


def test_every_arithmetic_row_has_one_exact_numeric_answer() -> None:
    for row in rows():
        if MATH.match(row["question"]):
            assert row["answer"].lstrip("-").isdigit()
            assert row["context"] == ""


def test_the_twenty_general_rows_come_from_the_fixed_faq() -> None:
    general = [row for row in rows() if not MATH.match(row["question"])]
    assert len(general) == 20
    questions = {entry["question"] for entry in load_faq()}
    assert {row["question"] for row in general} == questions
    assert all(row["context"] for row in general)


def test_the_generator_is_seeded_so_the_file_reproduces_byte_for_byte() -> None:
    first_rows, first_truth = build()
    second_rows, second_truth = build()
    assert first_rows == second_rows
    assert first_truth == second_truth
    assert CSV_PATH.read_bytes().decode("utf-8") == render_csv(first_rows)
    assert json.loads(TRUTH_PATH.read_text(encoding="utf-8")) == first_truth


def test_the_per_case_truth_lists_exactly_the_seeded_rows() -> None:
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    data = rows()
    configs = {config.id: config for config in load_all()}
    assert truth["rows"] == len(data)
    for app_id, rate in (("app03", 30), ("app05", 60), ("app07", 20)):
        expected = [
            index
            for index, row in enumerate(data)
            if bucket(configs[app_id].seed, row["question"]) < rate
        ]
        assert truth["apps"][app_id]["faulty_row_indices"] == expected
        assert truth["apps"][app_id]["faulty_count"] == len(expected)
        assert len(expected) > 0


def test_the_faulty_share_is_close_to_the_declared_rate() -> None:
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    for app_id, rate in (("app03", 30), ("app05", 60), ("app07", 20)):
        share = truth["apps"][app_id]["faulty_count"] / truth["rows"]
        assert abs(share * 100 - rate) <= 12, (
            f"{app_id} is {share:.0%}, declared {rate}%"
        )


def test_the_attack_only_apps_declare_run_level_truth_instead_of_copied_probes() -> (
    None
):
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    for app_id in ("app04", "app10"):
        entry = truth["apps"][app_id]
        assert entry["faulty_row_indices"] == []
        assert entry["faulty_count"] == 0
        assert "safety" in entry["note"]


def test_no_attack_prompt_was_copied_into_the_dataset() -> None:
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    assert all(
        entry["faulty_row_indices"] == []
        for entry in (truth["apps"]["app04"], truth["apps"]["app10"])
    )
    assert not any("ignore" in row["question"].casefold() for row in rows())


def test_the_dataset_does_not_require_a_reader_beyond_the_standard_library() -> None:
    text = (DATA / "make_questions.py").read_text(encoding="utf-8")
    assert "import pandas" not in text
    assert "import numpy" not in text
