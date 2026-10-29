"""human_labels (M7 human review and calibration)

Revision ID: 0012_human_labels
Revises: 0011_run_baselines
Create Date: 2026-10-29 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_human_labels"
down_revision: str | None = "0011_run_baselines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "human_labels",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_item_id",
            sa.Uuid(),
            sa.ForeignKey("run_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "reviewer_id",
            "run_item_id",
            name="uq_human_labels_reviewer_item",
        ),
    )
    op.create_index("ix_human_labels_run_id", "human_labels", ["run_id"])
    op.create_index("ix_human_labels_run_item_id", "human_labels", ["run_item_id"])
    op.create_index("ix_human_labels_reviewer_id", "human_labels", ["reviewer_id"])


def downgrade() -> None:
    op.drop_table("human_labels")
