"""add_connector_column

Revision ID: d7101d15e98a
Revises: 0003_providers
Create Date: 2026-10-22 16:27:48.726435
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7101d15e98a"
down_revision: str | None = "0003_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column("connector", sa.String(length=40), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("providers", "connector")
