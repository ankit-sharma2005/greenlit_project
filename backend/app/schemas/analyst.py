"""Schemas for the analyst (PART 2): the preview, the request and the stored answer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

ExplanationStatus = Literal["ok", "rejected", "error", "none"]


class ExplanationPreview(BaseModel):
    """Exactly the text that would be sent, so the user can read it first."""

    input: str
    input_hash: str
    provider_id: UUID
    provider_name: str
    model: str
    prompt_version: str
    provider_is_local: bool


class ExplanationRequest(BaseModel):
    """`confirm_remote` is the extra step for a provider that leaves this machine."""

    model_config = ConfigDict(extra="forbid")

    confirm_remote: bool = False


class ExplanationRead(BaseModel):
    """The stored explanation, or a neutral message when there is none."""

    status: ExplanationStatus
    text: str = ""
    message: str = ""
    model: str | None = None
    provider_name: str | None = None
    prompt_version: str | None = None
    created_at: datetime | None = None
    input_hash: str | None = None
