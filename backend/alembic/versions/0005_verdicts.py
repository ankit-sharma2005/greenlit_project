"""Add project verdict criteria and immutable run criteria snapshots.

Revision ID: 0005_verdicts
Revises: 0004_metrics
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_verdicts"
down_revision: str | None = "0004_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_verdict_criteria",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.add_column(
        "eval_runs",
        sa.Column(
            "criteria_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.alter_column("eval_runs", "criteria_snapshot", server_default=None)


def downgrade() -> None:
    op.drop_column("eval_runs", "criteria_snapshot")
    op.drop_table("project_verdict_criteria")
