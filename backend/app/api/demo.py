"""One-click demo: seed the golden dataset and name the demo targets (spec 10).

``POST /api/v1/demo/load`` is everything the button needs in one call: it stores
and approves the 12-case helpdesk dataset for this account (idempotent) and
returns the two demo URLs the runs should point at. The runs themselves go
through the normal ``/runs`` endpoints, so the demo uses the same code path as
any other test.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services.datasets import DatasetError
from app.services.demo import DEMO_DATASET_NAME, load_demo_dataset

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

_DATASET_STATUS_BY_CODE = {
    "unsupported_format": 400,
    "missing_columns": 400,
    "duplicate_name": 409,
}


class DemoLoadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dataset_id: uuid.UUID
    dataset_version_id: uuid.UUID
    good_url: str
    broken_url: str


@router.post("/load", response_model=DemoLoadResponse)
def load_demo(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DemoLoadResponse:
    """Create (or reuse) the demo dataset and report the demo targets."""
    try:
        dataset, version = load_demo_dataset(db, user)
        db.commit()
    except DatasetError as exc:
        db.rollback()
        raise HTTPException(
            status_code=_DATASET_STATUS_BY_CODE.get(exc.code, 400),
            detail=exc.message,
        ) from exc

    settings = get_settings()
    return DemoLoadResponse(
        name=DEMO_DATASET_NAME,
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        good_url=settings.demo_app_url,
        broken_url=settings.demo_app_broken_url,
    )
