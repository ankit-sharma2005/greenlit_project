"""providers_is_premium

The M2 provider model gained ``is_premium`` but no migration was written for it
(SQLite-based tests build tables from the models, so the drift never surfaced).
This adds the missing column.

Revision ID: 0007_providers_is_premium
Revises: 0006_generated_flag
Create Date: 2026-10-23 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_providers_is_premium"
down_revision: str | None = "0006_generated_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column(
            "is_premium",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("providers", "is_premium")
