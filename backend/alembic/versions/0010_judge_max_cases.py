"""judge_profiles.max_cases (M7 cost guard)

Revision ID: 0010_judge_max_cases
Revises: 0009_judge_profiles
Create Date: 2026-10-29 12:00:00.000000

A judge grades every answered case by default, which can be expensive on a large
dataset. The cap is nullable on purpose: NULL means "all cases", so every profile
saved before this migration keeps its behaviour instead of silently grading less.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_judge_max_cases"
down_revision: str | None = "0009_judge_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("judge_profiles", sa.Column("max_cases", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("judge_profiles", "max_cases")
