"""The built-in safety sets a run can choose from (spec 8.3).

The catalogue is read-only and ships with the app: it lists the attack
categories and the harmless-request set with their descriptions and real case
counts, so the New Test page can show what a selection actually sends instead
of a hard-coded list. Selecting ids is validated again when the run is created.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models import User
from app.safety.sets import catalogue_payload

router = APIRouter(prefix="/api/v1/safety", tags=["safety"])


@router.get("/sets")
def list_safety_sets(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """Every selectable safety set, with its description and case counts."""
    return catalogue_payload()
