"""Account preference schemas.

Only the keys the UI can actually change are accepted; anything else is a
validation error, so a client cannot store arbitrary payloads on the account.

The three model roles are optional: a role is stored only when the user has
chosen a provider and a model for it, and an unset role is left out of the
response entirely, so an account that never touched them still reads as the
one-key document older clients expect.

The same rule holds for the remaining fields: an unset entry point, test-type
list, time zone or answer-length choice is absent, never null, so a document
that only ever held a theme is unchanged on the wire.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

Theme = Literal["dark", "light", "system"]
THEMES: tuple[Theme, ...] = ("dark", "light", "system")
DEFAULT_THEME: Theme = "dark"

#: The roles a model can be chosen for. `analyst` explains a finished run.
MODEL_ROLES: tuple[str, ...] = ("judge", "target", "generator", "analyst")

#: The entry points a New Test form can start from. Kept in step with
#: `app.schemas.runs.EntryPoint`; a stored value outside this tuple is ignored.
EntryPointDefault = Literal["http_endpoint", "prompt_app", "upload_outputs", "mcp_server"]
ENTRY_POINTS: tuple[str, ...] = ("http_endpoint", "prompt_app", "upload_outputs", "mcp_server")

DefaultTestType = Literal["quality", "safety", "operations"]
TEST_TYPE_CHOICES: tuple[str, ...] = ("quality", "safety", "operations")

#: The one possible answer for a time zone that the tz database cannot resolve.
TIME_ZONE_ERROR = "Unknown time zone. Use an IANA name such as Europe/Berlin."


def known_time_zone(value: str) -> bool:
    """True when `value` is an IANA zone this machine can resolve.

    The tz database is the only authority here: a made-up name like
    `Mars/Olympus` is rejected rather than stored and silently ignored later.
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


class ModelChoice(BaseModel):
    """One role's provider and model. The provider's key is never part of this."""

    model_config = ConfigDict(extra="forbid")

    provider_id: UUID
    model: str = Field(min_length=1, max_length=200)


class Preferences(BaseModel):
    """The whole preference document; a PATCH replaces the keys it carries.

    `theme` is required (it is what every client has always sent); every other
    field is optional and absent from the response when unset.
    """

    model_config = ConfigDict(extra="forbid")

    theme: Theme
    #: Which New Test form to open on, and which test types to tick in it.
    entry_point: EntryPointDefault | None = None
    test_types: list[DefaultTestType] | None = Field(default=None, max_length=3)
    #: An IANA name, e.g. "Europe/Berlin"; dates in the UI are rendered in it.
    time_zone: str | None = Field(default=None, max_length=64)
    #: Off truncates long answers in the run view, with a "Show more" control.
    show_full_answers: bool | None = None
    judge: ModelChoice | None = None
    target: ModelChoice | None = None
    generator: ModelChoice | None = None
    analyst: ModelChoice | None = None

    @field_validator("time_zone")
    @classmethod
    def _the_zone_must_exist(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not known_time_zone(value):
            raise ValueError(TIME_ZONE_ERROR)
        return value

    @field_validator("test_types")
    @classmethod
    def _each_type_once(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(set(value)) != len(value):
            raise ValueError("List each test type once.")
        return value
