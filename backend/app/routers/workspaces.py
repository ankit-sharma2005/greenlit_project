from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_roles, require_workspace_access
from app.models import AuditLog, User, Workspace, WorkspaceMembership
from app.schemas import AuditLogOut, WorkspaceOut

router = APIRouter(tags=["workspaces"])


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Workspace]:
    memberships = await db.execute(
        select(Workspace)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == user.id)
    )
    return list(memberships.scalars().all())


@router.get("/workspaces/{workspace_id}/audit", response_model=list[AuditLogOut])
async def list_audit_logs(
    workspace_id: UUID,
    _: Annotated[WorkspaceMembership, Depends(require_workspace_access)],
    __: Annotated[User, Depends(require_roles("owner", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AuditLog]:
    logs = await db.execute(
        select(AuditLog)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.created_at.desc())
    )
    return list(logs.scalars().all())


@router.get("/workspaces/{workspace_id}/engineer/insights")
async def engineer_insights(
    workspace_id: UUID,
    _: Annotated[WorkspaceMembership, Depends(require_workspace_access)],
    __: Annotated[User, Depends(require_roles("owner", "admin", "engineer"))],
) -> dict[str, object]:
    return {
        "workspace_id": str(workspace_id),
        "status": "insights-ready",
        "checks": ["prompt quality", "retrieval health"],
    }


@router.get("/workspaces/{workspace_id}/viewer/summary")
async def viewer_summary(
    workspace_id: UUID,
    _: Annotated[WorkspaceMembership, Depends(require_workspace_access)],
    __: Annotated[
        User, Depends(require_roles("owner", "admin", "engineer", "reviewer", "viewer"))
    ],
) -> dict[str, str]:
    return {"workspace_id": str(workspace_id), "status": "viewer-access-ok"}
