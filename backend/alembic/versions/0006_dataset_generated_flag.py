"""dataset_generated_flag

Revision ID: 0006_generated_flag
Revises: 0005_dataset_approval
Create Date: 2026-10-23 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_generated_flag"
down_revision: str | None = "0005_dataset_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_versions",
        sa.Column(
            "generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("dataset_versions", "generated")
