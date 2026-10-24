"""runs, run_items and metric_results (M6a)

Revision ID: 0008_runs
Revises: 0007_providers_is_premium
Create Date: 2026-10-24 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_runs"
down_revision: str | None = "0007_providers_is_premium"
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
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
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
            "criteria_profile",
            sa.String(length=60),
            nullable=False,
            server_default=sa.text("'plain_chatbot'"),
        ),
        sa.Column(
            "settings_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "state",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("verdict", sa.String(length=10), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("verdict_reason", sa.Text(), nullable=True),
        sa.Column(
            "is_partial",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_runs_owner_id", "runs", ["owner_id"])
    op.create_index("ix_runs_dataset_id", "runs", ["dataset_id"])
    op.create_index("ix_runs_dataset_version_id", "runs", ["dataset_version_id"])

    op.create_table(
        "run_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "state",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("retrieved_context", sa.JSON(), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("run_id", "row_index", name="uq_run_items_run_row_index"),
    )
    op.create_index("ix_run_items_run_id", "run_items", ["run_id"])

    op.create_table(
        "metric_results",
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
            nullable=True,
        ),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "instrumented",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("weight", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("threshold", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("hard_gate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("details", sa.JSON(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_metric_results_run_id", "metric_results", ["run_id"])
    op.create_index("ix_metric_results_run_item_id", "metric_results", ["run_item_id"])


def downgrade() -> None:
    op.drop_table("metric_results")
    op.drop_table("run_items")
    op.drop_table("runs")
