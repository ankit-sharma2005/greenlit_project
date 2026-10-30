"""runs.operations (per-run operations metrics)

Revision ID: 0013_run_operations
Revises: 0012_human_labels
Create Date: 2026-10-30 13:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_run_operations"
down_revision: str | None = "0012_human_labels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the JSON block the worker fills in when a run finishes."""
    op.add_column("runs", sa.Column("operations", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "operations")
