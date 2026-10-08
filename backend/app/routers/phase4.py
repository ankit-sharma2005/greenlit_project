from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_roles
from app.models import Project, User
from app.phase4_schemas import MetricCatalogOut
from app.services.metrics import metric_catalog

router = APIRouter(tags=["metrics"])

Member = Annotated[
    User,
    Depends(require_roles("owner", "admin", "engineer", "reviewer", "viewer")),
]


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/metrics",
    response_model=list[MetricCatalogOut],
)
async def get_metric_catalog(
    workspace_id: UUID,
    project_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MetricCatalogOut]:
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return metric_catalog()
