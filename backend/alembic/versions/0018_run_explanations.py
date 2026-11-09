"""run_explanations: the analyst's one row per run and input

Revision ID: 0018_run_explanations
Revises: 0017_dataset_drafts
Create Date: 2026-11-09 21:40:00.000000

The analyst explains a finished run. It has no write path to runs, scores,
verdicts, targets, datasets or settings: the only row it ever writes is here,
keyed by the run and a hash of the exact input that was sent, so a repeated
click reuses the answer instead of paying for a second call.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_run_explanations"
down_revision: str | None = "0017_dataset_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the explanation table."""
    op.create_table(
        "run_explanations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("run_id", "input_hash", name="uq_run_explanations_run_input"),
    )
    op.create_index("ix_run_explanations_run_id", "run_explanations", ["run_id"])


def downgrade() -> None:
    """Drop the explanation table."""
    op.drop_index("ix_run_explanations_run_id", table_name="run_explanations")
    op.drop_table("run_explanations")
