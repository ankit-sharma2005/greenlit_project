"""The demo-app catalog (Settings → Demo apps).

Two endpoints, both cookie-authenticated and read-only against the network:

* ``GET /api/v1/demo-apps`` — the five fixed catalog entries with a health
  probe each. The probe takes its address from the compiled catalog, never from
  the request, so this cannot scan ports or fetch an arbitrary URL (H2).
* ``POST /api/v1/demo-apps/{id}/connect`` — saves the entry as an ordinary
  saved target through the existing service. The private-target allowance is set
  on that one target, whose URL is the catalog's own loopback address, so the
  global guard is untouched (H3). A second call returns the same target.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import SavedTarget, User
from app.schemas.saved_targets import SavedTargetRead
from app.services import demo_catalog
from app.services.audit import record
from app.services.saved_targets import (
    SavedTargetError,
    create_saved_target,
    list_saved_targets,
)

router = APIRouter(prefix="/api/v1/demo-apps", tags=["demo"])


class DemoAppsResponse(BaseModel):
    items: list[dict[str, object]]
    warning: str


class DemoConnectBody(BaseModel):
    """Connect takes an empty body: an address in it is refused, not ignored."""

    model_config = ConfigDict(extra="forbid")


class DemoConnectResponse(BaseModel):
    """The saved target, whether this call created it, and the local-only warning."""

    model_config = ConfigDict(extra="forbid")

    target: SavedTargetRead
    created: bool
    warning: str


@router.get("", response_model=DemoAppsResponse)
def list_demo_apps(
    user: User = Depends(get_current_user),
) -> DemoAppsResponse:
    """The catalog with a status per entry; ``user`` is only the auth check."""
    del user
    return DemoAppsResponse(items=demo_catalog.statuses(), warning=demo_catalog.WARNING)


@router.post("/{app_id}/connect", response_model=DemoConnectResponse, status_code=201)
def connect_demo_app(
    app_id: str,
    request: Request,
    payload: DemoConnectBody | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DemoConnectResponse:
    """Save (or return) this account's target for one catalog entry."""
    entry = demo_catalog.get_entry(app_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Demo app not found.")

    existing = next(
        (target for target in list_saved_targets(db, user.id) if target.name == entry.name),
        None,
    )
    if existing is not None:
        return DemoConnectResponse(
            target=SavedTargetRead.model_validate(existing),
            created=False,
            warning=demo_catalog.WARNING,
        )

    try:
        target: SavedTarget = create_saved_target(
            db,
            owner_id=user.id,
            name=entry.name,
            url=entry.url,
            method=entry.method,
            body_template=entry.body_template,
            answer_path=entry.answer_path,
            context_path=entry.context_path,
            response_format=entry.response_format,
            timeout_seconds=entry.timeout_seconds,
            # Only this catalog entry's own fixed address; the global guard and
            # every other target keep their normal rule.
            allow_private_targets=True,
        )
    except SavedTargetError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    record(
        db,
        "saved_target.create",
        actor_id=user.id,
        target_type="saved_target",
        target_id=str(target.id),
        metadata={"demo_app": entry.id, "connector_type": target.connector_type},
        request=request,
    )
    db.commit()
    db.refresh(target)
    return DemoConnectResponse(
        target=SavedTargetRead.model_validate(target),
        created=True,
        warning=demo_catalog.WARNING,
    )
