"""runs.last_heartbeat_at (interrupted-run detection)

Revision ID: 0014_run_heartbeat
Revises: 0013_run_operations
Create Date: 2026-11-02 15:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_run_heartbeat"
down_revision: str | None = "0013_run_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the timestamp a running worker touches at every case boundary."""
    op.add_column(
        "runs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "last_heartbeat_at")
