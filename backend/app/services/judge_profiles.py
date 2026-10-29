"""Judge profiles: which model grades a run, saved and selected (M7).

A profile is the *configuration* of the judge (provider, model, rubric version,
temperature, max tokens); the scoring itself stays in :mod:`app.services.judge`.
Following the dataset and audit convention, these functions take an open session
and only flush: the caller owns the transaction.

Temperature is always the frozen ``JUDGE_TEMPERATURE`` (0): acceptance criterion 8
requires the same inputs to reproduce the same verdict, so an editable
temperature would quietly break reproducibility. ``max_tokens`` is editable
because it only bounds the reply length.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import JudgeProfile, Provider
from app.services.judge import (
    JUDGE_MAX_TOKENS,
    JUDGE_RUBRIC_VERSION,
    JUDGE_TEMPERATURE,
    judge_model_warning,
)


class JudgeProfileError(ValueError):
    """A judge profile cannot be created or selected; ``status`` maps to HTTP."""

    def __init__(self, message: str, *, status: int = 400, code: str = "bad_request") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def create_judge_profile(
    session: Session,
    *,
    owner_id: uuid.UUID,
    name: str,
    provider_id: uuid.UUID | None,
    model: str | None = None,
    max_tokens: int = JUDGE_MAX_TOKENS,
    max_cases: int | None = None,
) -> JudgeProfile:
    """Create one profile for the owner; the first profile is selected at once."""
    cleaned = name.strip()
    if not cleaned:
        raise JudgeProfileError("Give the judge profile a name, for example 'Local judge'.")
    duplicate = session.scalar(
        select(JudgeProfile).where(
            JudgeProfile.owner_id == owner_id,
            func.lower(JudgeProfile.name) == cleaned.lower(),
        )
    )
    if duplicate is not None:
        raise JudgeProfileError(
            f"A judge profile called '{cleaned}' already exists.", status=409, code="duplicate_name"
        )
    provider = _provider(session, provider_id)
    profile = JudgeProfile(
        owner_id=owner_id,
        name=cleaned,
        provider_id=provider.id if provider is not None else None,
        model=(model or "").strip() or (provider.model_name if provider is not None else None),
        rubric_version=JUDGE_RUBRIC_VERSION,
        temperature=JUDGE_TEMPERATURE,
        max_tokens=max_tokens,
        max_cases=max_cases,
        # The first profile becomes the default, so a run is judged as soon as
        # the user saves one instead of needing a second click.
        is_selected=selected_judge_profile(session, owner_id) is None,
    )
    session.add(profile)
    session.flush()
    return profile


def list_judge_profiles(session: Session, owner_id: uuid.UUID) -> list[JudgeProfile]:
    """The owner's profiles, oldest first."""
    rows = session.scalars(
        select(JudgeProfile)
        .where(JudgeProfile.owner_id == owner_id)
        .order_by(JudgeProfile.created_at)
    ).all()
    return list(rows)


def get_judge_profile(
    session: Session, profile_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> JudgeProfile | None:
    """One profile; with ``owner_id`` somebody else's profile reads as missing."""
    profile = session.get(JudgeProfile, profile_id)
    if profile is None:
        return None
    if owner_id is not None and profile.owner_id != owner_id:
        return None
    return profile


def selected_judge_profile(session: Session, owner_id: uuid.UUID) -> JudgeProfile | None:
    """The owner's selected profile, if any (used as the default for new runs)."""
    return session.scalar(
        select(JudgeProfile)
        .where(JudgeProfile.owner_id == owner_id, JudgeProfile.is_selected.is_(True))
        .order_by(JudgeProfile.created_at)
    )


def select_judge_profile(session: Session, profile: JudgeProfile) -> JudgeProfile:
    """Make this profile the owner's default and clear the previous one."""
    for other in list_judge_profiles(session, profile.owner_id):
        other.is_selected = other.id == profile.id
        session.add(other)
    session.flush()
    return profile


def delete_judge_profile(session: Session, profile: JudgeProfile) -> None:
    """Remove one profile; a selected profile leaves the owner with none selected."""
    session.delete(profile)
    session.flush()


def judge_warnings(
    session: Session, *, provider_id: uuid.UUID | None, model: str | None
) -> list[str]:
    """Self-grading warnings for a judge choice (spec 8.2).

    The app under test is not known when the profile is saved: any saved,
    active provider could be the one a run sends its questions to, so a judge
    whose model matches one of them is flagged by name. The text itself comes
    from :func:`app.services.judge.judge_model_warning`, so the worker and the
    API say the same thing.
    """
    chosen = (model or "").strip()
    if not chosen:
        return []
    warnings: list[str] = []
    providers = session.scalars(
        select(Provider).where(Provider.is_active.is_(True)).order_by(Provider.created_at)
    ).all()
    for provider in providers:
        warning = judge_model_warning(provider.model_name, chosen)
        if warning is None:
            continue
        named = f"{warning} Saved provider: {provider.name}."
        if provider.id != provider_id:
            named += " Pick a different judge model for an independent score."
        if named not in warnings:
            warnings.append(named)
    return warnings


def effective_model(profile: JudgeProfile, provider: Provider | None) -> str | None:
    """The model the worker will ask for: the profile's, else the provider's."""
    chosen = (profile.model or "").strip()
    if chosen:
        return chosen
    return provider.model_name if provider is not None else None


def _provider(session: Session, provider_id: uuid.UUID | None) -> Provider | None:
    if provider_id is None:
        return None
    provider = session.get(Provider, provider_id)
    if provider is None:
        raise JudgeProfileError(
            "That provider was not found. Pick one in Settings > Providers.",
            status=404,
            code="not_found",
        )
    return provider
