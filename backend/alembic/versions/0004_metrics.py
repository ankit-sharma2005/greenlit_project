"""Persist metric scores and judge cache.

Revision ID: 0004_metrics
Revises: 0003_phase3
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_metrics"
down_revision: str | None = "0003_phase3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_run_items",
        sa.Column(
            "scores",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    with op.batch_alter_table("eval_run_items") as batch_op:
        batch_op.alter_column("scores", server_default=None)
    op.create_table(
        "judge_metric_cache",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("cache_key"),
    )


def downgrade() -> None:
    op.drop_table("judge_metric_cache")
    op.drop_column("eval_run_items", "scores")
