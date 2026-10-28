"""judge_profiles (M7)

Revision ID: 0009_judge_profiles
Revises: 0008_runs
Create Date: 2026-10-28 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_judge_profiles"
down_revision: str | None = "0008_runs"
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
        "judge_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "provider_id",
            sa.Uuid(),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column(
            "rubric_version",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'1.0'"),
        ),
        sa.Column(
            "temperature",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("512"),
        ),
        sa.Column(
            "is_selected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        *_timestamps(),
        sa.UniqueConstraint("owner_id", "name", name="uq_judge_profiles_owner_name"),
    )
    op.create_index("ix_judge_profiles_owner_id", "judge_profiles", ["owner_id"])
    op.create_index("ix_judge_profiles_provider_id", "judge_profiles", ["provider_id"])


def downgrade() -> None:
    op.drop_table("judge_profiles")
