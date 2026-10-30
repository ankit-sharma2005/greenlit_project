"""The read-only view of how the decision engine decides (Settings -> Criteria).

Nothing here holds a value of its own: the thresholds and weights are read from
the same :class:`~app.services.criteria.CriteriaProfile` the engine scores with,
and the rule wording comes from :mod:`app.services.decision`. If a weight or a
threshold changes in the engine, this view changes with it.

The profile shown is the default template plus the safety and judge criteria,
because that is what a New Test run with all test types gets. Those two extras
are labelled ``applies``: they only join the weighted score when Safety is on or
a judge is configured.
"""

from __future__ import annotations

from typing import Any

from app.services.criteria import (
    DEFAULT_TEMPLATE_KEY,
    TEMPLATES,
    CriteriaProfile,
    get_profile,
    with_judge,
    with_safety,
)
from app.services.decision import DECISION_RULES, NOT_INSTRUMENTED_RULE

# Which family each metric belongs to. Weights and thresholds are NOT repeated
# here; only the grouping the UI shows.
METRIC_GROUPS: dict[str, str] = {
    "answer_match": "quality",
    "retrieval_context_recall": "quality",
    "output_nonempty": "quality",
    "output_json_schema_valid": "quality",
    "tool_call_match": "quality",
    "answer_quality": "quality",
    "attack_resisted": "safety",
    "over_refusal": "safety",
    "latency_under_limit": "operations",
    "error_rate": "operations",
    "timeout_rate": "operations",
    "token_usage_present": "operations",
}

ALWAYS = "always"
SAFETY_ON = "safety on"
JUDGE_ON = "judge configured"


def _applies(metric: str) -> str:
    """When this metric joins the weighted score."""
    if metric in {"attack_resisted", "over_refusal"}:
        return SAFETY_ON
    if metric == "answer_quality":
        return JUDGE_ON
    return ALWAYS


def _criterion_rows(profile: CriteriaProfile) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for criterion in profile.criteria:
        rows.append(
            {
                "name": criterion.metric,
                "group": METRIC_GROUPS.get(criterion.metric, "quality"),
                "weight": criterion.weight,
                "hard_gate": criterion.hard_gate,
                # The bar a metric has to clear; for a gate this is the value a
                # failure is measured against.
                "threshold": criterion.threshold,
                "gate_threshold": criterion.threshold if criterion.hard_gate else None,
                "applies": _applies(criterion.metric),
            }
        )
    return rows


def criteria_overview() -> dict[str, Any]:
    """The default profile, its metrics, its thresholds and the ordered rules."""
    base = get_profile(DEFAULT_TEMPLATE_KEY)
    profile = with_judge(with_safety(base))
    return {
        "template": {
            "key": profile.key,
            "name": profile.name,
            "description": profile.description,
        },
        "review_threshold": profile.review_threshold,
        "go_threshold": profile.go_threshold,
        "criteria": _criterion_rows(profile),
        "rules": [dict(rule) for rule in DECISION_RULES],
        "not_instrumented_rule": NOT_INSTRUMENTED_RULE,
        "templates": [
            {
                "key": template.key,
                "name": template.name,
                "description": template.description,
                "criteria_count": len(template.criteria),
            }
            for template in [TEMPLATES[key] for key in sorted(TEMPLATES)]
        ],
        "default_template_key": DEFAULT_TEMPLATE_KEY,
    }
