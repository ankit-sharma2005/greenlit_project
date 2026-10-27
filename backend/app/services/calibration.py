"""Calibration: does the judge agree with the humans? (M7, spec 8.5)

Reviewers label cases (approve, reject, or edit the score). Those labels are
compared with what the judge said, and the result is reported as raw agreement
plus **Cohen's kappa**::

    k = (po - pe) / (1 - pe)

``po`` is how often the two raters agreed; ``pe`` is how often they would agree
by chance alone. So kappa 0 is chance-level agreement and 1 is perfect
agreement, whatever the label mix. Raw agreement alone would flatter a judge on
a lopsided set (if 90% of cases pass, always saying "pass" scores 0.90), which
is exactly what kappa corrects for.

Everything here is a pure function of already-collected labels: no I/O, no model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Labels are compared as categories, so any hashable label works; in practice
# they are "pass" / "fail" from a score bucket, or a reviewer's own label.
LabelPair = tuple[str, str]

DEFAULT_PASS_THRESHOLD = 0.60
MIN_LABELS_FOR_KAPPA = 2

# Landis and Koch's bands, used for the plain-language reading only.
_KAPPA_BANDS: tuple[tuple[float, str], ...] = (
    (0.0, "worse than chance"),
    (0.20, "slight"),
    (0.40, "fair"),
    (0.60, "moderate"),
    (0.80, "substantial"),
    (1.00, "almost perfect"),
)


@dataclass(frozen=True)
class Calibration:
    """The calibration summary a report shows for one judged run."""

    labelled: int
    agreed: int
    raw_agreement: float | None
    kappa: float | None
    reading: str

    def to_dict(self) -> dict[str, object]:
        return {
            "labelled": self.labelled,
            "agreed": self.agreed,
            "raw_agreement": (None if self.raw_agreement is None else round(self.raw_agreement, 4)),
            "kappa": None if self.kappa is None else round(self.kappa, 4),
            "reading": self.reading,
        }


def pass_fail(score: float | None, threshold: float = DEFAULT_PASS_THRESHOLD) -> str:
    """Bucket a score the way a reviewer's approve/reject would land."""
    if score is None:
        return "unscored"
    return "pass" if score >= threshold else "fail"


def label_pairs(
    judge_labels: Sequence[str | None],
    human_labels: Sequence[str | None],
) -> list[LabelPair]:
    """Pair up the labels that both sides actually produced, in order.

    Cases without both labels cannot be compared and are skipped, so a partly
    reviewed run still calibrates on what it has.
    """
    pairs: list[LabelPair] = []
    for judge_label, human_label in zip(judge_labels, human_labels, strict=False):
        if judge_label is None or human_label is None:
            continue
        pairs.append((judge_label, human_label))
    return pairs


def raw_agreement(pairs: Sequence[LabelPair]) -> float | None:
    """Share of paired labels that match (``po``); None when there is nothing."""
    if not pairs:
        return None
    agreed = sum(1 for judge_label, human_label in pairs if judge_label == human_label)
    return agreed / len(pairs)


def cohen_kappa(pairs: Sequence[LabelPair]) -> float | None:
    """Cohen's kappa for two raters over categories.

    Returns None when kappa is undefined rather than inventing a number: no
    labels at all, only one category in play, or perfect expected agreement
    (``pe`` of 1 means the raters could not disagree by chance, so the
    denominator vanishes).
    """
    if not pairs:
        return None
    total = len(pairs)
    categories = {label for pair in pairs for label in pair}
    if len(categories) < MIN_LABELS_FOR_KAPPA:
        return None
    observed = sum(1 for judge_label, human_label in pairs if judge_label == human_label) / total
    expected = 0.0
    for category in categories:
        judge_share = sum(1 for judge_label, _ in pairs if judge_label == category) / total
        human_share = sum(1 for _, human_label in pairs if human_label == category) / total
        expected += judge_share * human_share
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def agreement_reading(kappa: float | None, agreement: float | None = None) -> str:
    """A one-sentence, plain-language reading of a kappa value."""
    if kappa is None:
        return (
            "Not enough labels to read agreement yet: label a few more cases before "
            "trusting the judge's scores."
        )
    band = next(name for limit, name in _KAPPA_BANDS if kappa <= limit)
    prefix = ""
    if agreement is not None:
        prefix = f"Judge and reviewers agreed on {agreement * 100:.0f}% of labelled cases; "
    return (
        f"{prefix}kappa {kappa:.2f} is {band} agreement beyond chance (0 is chance, 1 is perfect)."
    )


def calibrate(pairs: Sequence[LabelPair]) -> Calibration:
    """Everything a report needs about judge-versus-human agreement."""
    agreement = raw_agreement(pairs)
    kappa = cohen_kappa(pairs)
    return Calibration(
        labelled=len(pairs),
        agreed=sum(1 for judge_label, human_label in pairs if judge_label == human_label),
        raw_agreement=agreement,
        kappa=kappa,
        reading=agreement_reading(kappa, agreement),
    )
