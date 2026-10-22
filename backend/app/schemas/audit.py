"""Audit log schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    event_metadata: dict[str, Any]
    ip_address: str | None
    created_at: datetime


class AuditListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditEventRead]
    total: int
    limit: int
    offset: int
