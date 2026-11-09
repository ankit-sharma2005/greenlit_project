"""Account preference schemas.

Only the keys the UI can actually change are accepted; anything else is a
validation error, so a client cannot store arbitrary payloads on the account.

The three model roles are optional: a role is stored only when the user has
chosen a provider and a model for it, and an unset role is left out of the
response entirely, so an account that never touched them still reads as the
one-key document older clients expect.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Theme = Literal["dark", "light", "system"]
THEMES: tuple[Theme, ...] = ("dark", "light", "system")
DEFAULT_THEME: Theme = "dark"

#: The three roles a model can be chosen for.
MODEL_ROLES: tuple[str, ...] = ("judge", "target", "generator")


class ModelChoice(BaseModel):
    """One role's provider and model. The provider's key is never part of this."""

    model_config = ConfigDict(extra="forbid")

    provider_id: UUID
    model: str = Field(min_length=1, max_length=200)


class Preferences(BaseModel):
    """The whole preference document; a PATCH replaces it.

    `theme` is required (it is what every client has always sent); the model
    roles are optional and absent when unset.
    """

    model_config = ConfigDict(extra="forbid")

    theme: Theme
    judge: ModelChoice | None = None
    target: ModelChoice | None = None
    generator: ModelChoice | None = None
