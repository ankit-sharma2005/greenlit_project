"""Read-only criteria overview (Settings -> Criteria)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MetricGroup = Literal["quality", "safety", "operations"]
AppliesWhen = Literal["always", "safety on", "judge configured"]


class CriterionRead(BaseModel):
    """One metric in the weighted score."""

    name: str
    group: MetricGroup
    weight: float
    hard_gate: bool
    # The bar the metric has to clear.
    threshold: float
    # Same bar, only when a failure of this metric is a hard gate.
    gate_threshold: float | None = None
    applies: AppliesWhen


class DecisionRuleRead(BaseModel):
    """One rule of the engine, in the order it is applied."""

    rule: int
    verdict: Literal["GO", "REVIEW", "NO_GO"]
    text: str


class CriteriaTemplateRead(BaseModel):
    key: str
    name: str
    description: str
    criteria_count: int


class CriteriaTemplateRef(BaseModel):
    key: str
    name: str
    description: str


class CriteriaOverviewRead(BaseModel):
    """The default profile the engine uses, with no editable values."""

    template: CriteriaTemplateRef
    review_threshold: float
    go_threshold: float
    criteria: list[CriterionRead] = Field(default_factory=list)
    rules: list[DecisionRuleRead] = Field(default_factory=list)
    not_instrumented_rule: str
    templates: list[CriteriaTemplateRead] = Field(default_factory=list)
    default_template_key: str
