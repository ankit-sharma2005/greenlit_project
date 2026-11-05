"""Account preference schemas.

Only the keys the UI can actually change are accepted; anything else is a
validation error, so a client cannot store arbitrary payloads on the account.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Theme = Literal["dark", "light", "system"]
THEMES: tuple[Theme, ...] = ("dark", "light", "system")
DEFAULT_THEME: Theme = "dark"


class Preferences(BaseModel):
    """The whole preference document; a PATCH replaces it."""

    model_config = ConfigDict(extra="forbid")

    theme: Theme
