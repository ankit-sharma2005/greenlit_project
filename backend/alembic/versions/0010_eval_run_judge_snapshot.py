"""Snapshot judge profiles when an evaluation run is created.

Revision ID: 0010_eval_run_judge_snapshot
Revises: 0009_chat_preferences_connectors
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_eval_run_judge_snapshot"
down_revision: str | None = "0009_chat_preferences_connectors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("judge_profiles_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Judge profile snapshots are retained; this migration is forward-only."
    )
