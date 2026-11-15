"""A5: the deterministic math solver, correct and seeded-faulty."""

from __future__ import annotations

import csv
import threading
from pathlib import Path
from typing import Any

import pytest
import requests
from math_solver.app import (
    _is_loopback,
    answer_for,
    create_server,
    expression_of,
    is_faulty,
)

QUESTIONS_CSV = (
    Path(__file__).resolve().parents[3] / "experiments" / "data" / "questions.csv"
)


def _questions() -> list[tuple[str, str]]:
    with QUESTIONS_CSV.open(encoding="utf-8", newline="") as handle:
        return [(row["question"], row["answer"]) for row in csv.DictReader(handle)]


@pytest.fixture()
def solver(tmp_path: Path) -> Any:
    server = create_server("correct", control_enabled=False, log_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_the_arithmetic_questions_are_answered_correctly(solver: str) -> None:
    for question, expected in _questions()[:10]:
        response = requests.post(f"{solver}/", json={"question": question}, timeout=10)
        assert response.status_code == 200
        assert response.json() == {"answer": expected}


def test_health_names_the_app_and_the_mode(solver: str) -> None:
    body = requests.get(f"{solver}/health", timeout=10).json()
    assert body == {
        "status": "ok",
        "app": "math-solver",
        "mode": "correct",
        "provider": "none",
        "model": "none",
    }


def test_the_faulty_set_is_the_same_every_time_for_a_seed() -> None:
    questions = [question for question, _answer in _questions()]
    first = {question for question in questions if is_faulty(question, 7)}
    second = {question for question in questions if is_faulty(question, 7)}
    assert first == second
    assert first != {question for question in questions if is_faulty(question, 8)}
    share = len(first) / len(questions)
    assert 0.2 <= share <= 0.4


def test_a_seeded_faulty_question_answers_a_wrong_number() -> None:
    question = next(q for q, _a in _questions() if is_faulty(q, 7))
    correct = answer_for(question, "correct")
    faulty = answer_for(question, "faulty_30", seed=7)
    assert faulty != correct


def test_a_healthy_question_stays_right_in_faulty_mode() -> None:
    question = next(q for q, _a in _questions() if not is_faulty(q, 7))
    assert answer_for(question, "faulty_30", seed=7) == answer_for(question, "correct")


def test_the_answer_path_strips_the_question_words() -> None:
    assert expression_of("What is 12 * 3?") == "12 * 3"
    assert expression_of("Calculate (3+4)/2?") == "(3+4)/2"


def test_the_control_endpoint_does_not_exist_without_the_flag(solver: str) -> None:
    response = requests.post(
        f"{solver}/_control/mode", json={"mode": "faulty_30"}, timeout=10
    )
    assert response.status_code == 404


def test_the_control_endpoint_flips_the_mode(tmp_path: Path) -> None:
    server = create_server("correct", control_enabled=True, log_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert requests.post(
            f"{url}/_control/mode", json={"mode": "faulty_30"}, timeout=10
        ).json() == {"mode": "faulty_30"}
        assert requests.get(f"{url}/health", timeout=10).json()["mode"] == "faulty_30"
        refused = requests.post(
            f"{url}/_control/mode", json={"mode": "chaos"}, timeout=10
        )
        assert refused.status_code == 400
        assert requests.get(f"{url}/health", timeout=10).json()["mode"] == "faulty_30"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_control_endpoint_refuses_a_non_loopback_caller() -> None:
    assert _is_loopback("127.0.0.1")
    assert _is_loopback("::1")
    assert not _is_loopback("10.1.2.3")
    assert not _is_loopback("host.docker.internal")


def test_a_hostile_expression_is_a_400_and_never_runs(solver: str) -> None:
    for question in (
        "What is __import__('os').system('echo pwned')?",
        "What is open('secrets.txt').read()?",
        "What is 2**999?",
        "What is (1).__class__?",
    ):
        response = requests.post(f"{solver}/", json={"question": question}, timeout=10)
        assert response.status_code == 400
        assert "answer" not in response.json()
