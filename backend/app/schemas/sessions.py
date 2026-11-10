"""Sessions on the Account tab.

One row per signed-in device (a refresh-token family). The response deliberately
carries no token, no hash and no IP address: the id is the family's opaque UUID,
and ``last_activity`` is the newest token's creation time — the product has no
"last used" column, so it is labelled in the UI as last activity, not "last seen".
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SessionRead(BaseModel):
    id: UUID
    device: str
    created_at: datetime
    last_activity: datetime
    current: bool


class SessionsResponse(BaseModel):
    items: list[SessionRead]
    total: int


class RevokedCount(BaseModel):
    revoked: int
