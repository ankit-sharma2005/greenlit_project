"""Read-only view of the criteria and the decision rules (Settings -> Criteria).

The values come from the engine's own profile and constants, so this endpoint
can never advertise a weight or a threshold the scorer does not use. Editing is
not offered: the profiles are versioned with the app so runs stay comparable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models import User
from app.schemas.criteria import CriteriaOverviewRead
from app.services.criteria_overview import criteria_overview

router = APIRouter(prefix="/api/v1/criteria", tags=["criteria"])


@router.get("", response_model=CriteriaOverviewRead)
def get_criteria(_: User = Depends(get_current_user)) -> CriteriaOverviewRead:
    """The default profile's metrics, thresholds and the ordered decision rules."""
    return CriteriaOverviewRead.model_validate(criteria_overview())
