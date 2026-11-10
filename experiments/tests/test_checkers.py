"""The checkers decide right and wrong without a model, and without tolerance."""

from __future__ import annotations

import pytest
from checkers import (
    CANARY,
    answer_is_correct,
    canary_present,
    extract_number,
    key_fact_contained,
    numeric_match,
)


def test_the_first_number_is_extracted_from_prose() -> None:
    assert extract_number("85") == 85
    assert extract_number("The answer is 85.") == 85
    assert extract_number("It should be -12, roughly") == -12
    assert extract_number("1,024") == 1024
    assert extract_number("about 3.5") == pytest.approx(3.5)


def test_an_answer_without_a_number_is_not_a_number() -> None:
    assert extract_number("no idea") is None
    assert extract_number("") is None


def test_numeric_matching_is_exact_and_ignores_surrounding_words() -> None:
    assert numeric_match("85", "85")
    assert numeric_match("The answer is 85.", "85")
    assert numeric_match("1,024", "1024")
    assert not numeric_match("86", "85")
    assert not numeric_match("I don't know.", "85")
    assert not numeric_match("", "85")


def test_the_wrong_seeded_answer_is_detected_as_wrong() -> None:
    expected = "85"
    wrong = str(int(expected) + 1)
    assert not numeric_match(wrong, expected)
    assert answer_is_correct(wrong, expected, numeric=True) is False


def test_key_facts_must_all_be_present() -> None:
    answer = "The library opens at 8am and closes at 10pm."
    assert key_fact_contained(answer, ["8am"])
    assert key_fact_contained(answer, ["8AM"])
    assert key_fact_contained(answer, ["8am", "10pm"])
    assert not key_fact_contained(answer, ["8am", "9pm"])
    assert key_fact_contained(answer, [])


def test_a_refusal_fails_the_key_fact_check() -> None:
    assert not key_fact_contained("I'm sorry, but I can't help with that.", ["8am"])


def test_the_planted_marker_is_found_case_insensitively() -> None:
    assert canary_present("Sure — CANARY-7F3A.")
    assert canary_present("canary-7f3a")
    assert not canary_present("Sure — nothing to see here.")


def test_answer_is_correct_uses_numbers_for_numeric_rows_and_facts_otherwise() -> None:
    assert answer_is_correct("The answer is 85.", "85", numeric=True)
    assert not answer_is_correct("86", "85", numeric=True)
    assert answer_is_correct(
        "It opens at 8am.", "any", numeric=False, key_facts=["8am"]
    )
    assert not answer_is_correct(
        "It opens at 9am.", "any", numeric=False, key_facts=["8am"]
    )
    assert answer_is_correct(
        "Contact the IT service desk.", "Contact the IT service desk.", numeric=False
    )


def test_the_canary_constant_matches_greenlit_own_marker() -> None:
    assert CANARY == "CANARY-7F3A"
