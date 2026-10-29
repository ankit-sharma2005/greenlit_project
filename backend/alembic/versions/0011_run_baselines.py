"""run_baselines (spec 8.5)

Revision ID: 0011_run_baselines
Revises: 0010_judge_max_cases
Create Date: 2026-10-29 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_run_baselines"
down_revision: str | None = "0010_judge_max_cases"
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
        "run_baselines",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dataset_version_id",
            sa.Uuid(),
            sa.ForeignKey("dataset_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "metric_tolerance",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.05"),
        ),
        sa.Column(
            "case_tolerance",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "owner_id",
            "dataset_version_id",
            name="uq_run_baselines_owner_version",
        ),
    )
    op.create_index("ix_run_baselines_owner_id", "run_baselines", ["owner_id"])
    op.create_index("ix_run_baselines_run_id", "run_baselines", ["run_id"])
    op.create_index(
        "ix_run_baselines_dataset_version_id", "run_baselines", ["dataset_version_id"]
    )


def downgrade() -> None:
    op.drop_table("run_baselines")
