"""M7 unit tests: judge-versus-human calibration (spec 8.5).

Kappa is worth testing against a hand-computed example, not only against its own
edges: the point of the metric is that it removes the agreement you would get by
chance, and raw agreement alone cannot show that.
"""

from __future__ import annotations

import pytest

from app.services.calibration import (
    Calibration,
    agreement_reading,
    calibrate,
    cohen_kappa,
    label_pairs,
    pass_fail,
    raw_agreement,
)

# ---- buckets and pairing ---------------------------------------------------


def test_pass_fail_buckets_a_score_against_the_threshold() -> None:
    assert pass_fail(0.60) == "pass"
    assert pass_fail(0.59) == "fail"
    assert pass_fail(None) == "unscored"
    assert pass_fail(0.4, threshold=0.3) == "pass"


def test_label_pairs_skips_cases_that_both_sides_did_not_label() -> None:
    pairs = label_pairs(["pass", None, "fail"], ["pass", "fail", None])

    assert pairs == [("pass", "pass")]


def test_label_pairs_survives_mismatched_lengths() -> None:
    assert label_pairs(["pass"], ["pass", "fail"]) == [("pass", "pass")]
    assert label_pairs([], ["pass"]) == []


# ---- raw agreement ---------------------------------------------------------


def test_raw_agreement_is_the_share_that_match() -> None:
    assert raw_agreement([("pass", "pass"), ("fail", "fail"), ("pass", "fail")]) == pytest.approx(
        2 / 3
    )
    assert raw_agreement([("pass", "fail")]) == 0.0
    assert raw_agreement([]) is None


# ---- kappa -----------------------------------------------------------------


def test_kappa_is_one_when_the_raters_always_agree() -> None:
    pairs = [("pass", "pass")] * 8 + [("fail", "fail")] * 4

    assert cohen_kappa(pairs) == pytest.approx(1.0)


def test_kappa_is_zero_when_agreement_is_exactly_chance() -> None:
    # Both raters say "pass" half the time and "fail" half the time, and they
    # agree on exactly half the cases: po == pe == 0.5, so kappa is 0.
    pairs = (
        [("pass", "pass")] * 25
        + [("pass", "fail")] * 25
        + [("fail", "pass")] * 25
        + [("fail", "fail")] * 25
    )

    assert raw_agreement(pairs) == pytest.approx(0.5)
    assert cohen_kappa(pairs) == pytest.approx(0.0)


def test_kappa_is_minus_one_when_the_raters_never_agree() -> None:
    # Perfectly opposite answers on a balanced set: the worst possible score.
    pairs = [("pass", "fail")] * 25 + [("fail", "pass")] * 25

    assert cohen_kappa(pairs) == pytest.approx(-1.0)


def test_kappa_matches_a_hand_computed_confusion_matrix() -> None:
    #        human pass  human fail
    # judge pass   20         5
    # judge fail   10        15
    # po = 35/50 = 0.70; pe = 0.5*0.6 + 0.5*0.4 = 0.50; k = 0.20/0.50 = 0.40
    pairs = (
        [("pass", "pass")] * 20
        + [("pass", "fail")] * 5
        + [("fail", "pass")] * 10
        + [("fail", "fail")] * 15
    )

    assert raw_agreement(pairs) == pytest.approx(0.70)
    assert cohen_kappa(pairs) == pytest.approx(0.40)


def test_kappa_can_be_negative_when_the_raters_are_worse_than_chance() -> None:
    # The judge is consistently the opposite of the human, and the human is
    # lopsided, so chance agreement is high and real agreement is zero.
    pairs = [("pass", "fail")] * 9 + [("fail", "pass")]

    kappa = cohen_kappa(pairs)

    assert kappa is not None
    assert kappa < 0


@pytest.mark.parametrize(
    "pairs",
    [
        [],
        [("pass", "pass")],
        [("pass", "pass"), ("pass", "pass")],  # only one category is in play
    ],
)
def test_kappa_is_undefined_rather_than_invented(pairs: list[tuple[str, str]]) -> None:
    assert cohen_kappa(pairs) is None


# ---- the plain-language reading -------------------------------------------


def test_agreement_reading_names_the_band_in_plain_words() -> None:
    assert "almost perfect" in agreement_reading(0.9)
    assert "substantial" in agreement_reading(0.7)
    assert "moderate" in agreement_reading(0.5)
    assert "fair" in agreement_reading(0.4)
    assert "slight" in agreement_reading(0.1)
    assert "worse than chance" in agreement_reading(-0.2)


def test_agreement_reading_explains_itself_when_kappa_is_undefined() -> None:
    reading = agreement_reading(None)

    assert "Not enough labels" in reading
    assert "label a few more cases" in reading


def test_agreement_reading_includes_raw_agreement_when_it_has_it() -> None:
    reading = agreement_reading(0.4, 0.70)

    assert "70% of labelled cases" in reading
    assert "kappa 0.40" in reading


# ---- the summary a report shows -------------------------------------------


def test_calibrate_reports_counts_agreement_kappa_and_a_reading() -> None:
    pairs = (
        [("pass", "pass")] * 20
        + [("pass", "fail")] * 5
        + [("fail", "pass")] * 10
        + [("fail", "fail")] * 15
    )

    result = calibrate(pairs)

    assert isinstance(result, Calibration)
    assert result.labelled == 50
    assert result.agreed == 35
    assert result.raw_agreement == pytest.approx(0.70)
    assert result.kappa == pytest.approx(0.40)
    assert "fair" in result.reading


def test_calibrate_on_nothing_is_honest_about_it() -> None:
    result = calibrate([])

    assert result.labelled == 0
    assert result.agreed == 0
    assert result.raw_agreement is None
    assert result.kappa is None
    assert result.to_dict()["kappa"] is None
