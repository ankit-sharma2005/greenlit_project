"""saved_targets (the Settings → Connectors shelf)

Revision ID: 0016_saved_targets
Revises: 0015_user_preferences
Create Date: 2026-11-06 09:00:00.000000

The Connectors tab promised saved targets, but a target only existed inside the
run that used it, so the format detected on the New Test page was lost on reload.
This table keeps that shape per owner. It has no column for a header value or a
permission record on purpose: secrets stay encrypted inside a run, and permission
to test a remote app is asked per run by the first-contact check.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_saved_targets"
down_revision: str | None = "0015_user_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table that keeps one row per saved target."""
    op.create_table(
        "saved_targets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "connector_type",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'http_endpoint'"),
        ),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False, server_default=sa.text("'POST'")),
        sa.Column("body_template", sa.Text(), nullable=True),
        sa.Column("header_names", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("answer_path", sa.String(length=300), nullable=True),
        sa.Column("context_path", sa.String(length=300), nullable=True),
        sa.Column("stream_content_path", sa.String(length=300), nullable=True),
        sa.Column(
            "response_format",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'json'"),
        ),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("min_delay_ms", sa.Integer(), nullable=False, server_default=sa.text("500")),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column(
            "allow_private_targets",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("owner_id", "name", name="uq_saved_targets_owner_name"),
    )
    op.create_index("ix_saved_targets_owner_id", "saved_targets", ["owner_id"])


def downgrade() -> None:
    """Drop the shelf; runs keep their own snapshot, so no history is lost."""
    op.drop_index("ix_saved_targets_owner_id", table_name="saved_targets")
    op.drop_table("saved_targets")
