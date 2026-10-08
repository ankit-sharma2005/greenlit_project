from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AttackCategory = Literal[
    "prompt_injection",
    "indirect_prompt_injection",
    "jailbreak",
    "system_prompt_leak",
    "pii_leakage",
    "unsafe_tool_use",
    "harmful_content",
    "over_refusal",
]


class AttackPackItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: AttackCategory
    prompt: str = Field(min_length=1, max_length=20000)
    source: Literal["direct", "retrieved_document", "tool_output", "multi_turn"]
    mutation: str | None = None
    tags: list[str] = Field(default_factory=list)


class SafetyMetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float = Field(ge=0, le=1)
    category: str


class GuardrailAblationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guardrails_on: float = Field(ge=0, le=1)
    guardrails_off: float = Field(ge=0, le=1)
    uplift: float = Field(ge=-1, le=1)
    direction: Literal["positive", "negative", "neutral"]


class SafetySummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attack_success_rate: float = Field(ge=0, le=1)
    asr_by_category: dict[str, float] = Field(default_factory=dict)
    leak_rate: float = Field(ge=0, le=1)
    canary_leak_rate: float = Field(ge=0, le=1)
    system_prompt_leak_rate: float = Field(ge=0, le=1)
    over_refusal_rate: float = Field(ge=0, le=1)
    unsafe_tool_call_rate: float = Field(ge=0, le=1)
    guardrail_uplift: float = Field(ge=-1, le=1)
    categories: list[SafetyMetricValue] = Field(default_factory=list)
