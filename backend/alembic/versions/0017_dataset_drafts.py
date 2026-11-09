"""dataset_drafts and draft_items (reviewed, generated datasets)

Revision ID: 0017_dataset_drafts
Revises: 0016_saved_targets
Create Date: 2026-11-09 10:00:00.000000

Generated cases used to be stored straight as a dataset version, so "approve"
meant approving a whole block of unreviewed text. These two tables make the
review explicit: every generated item starts `pending`, a reviewer approves,
rejects or edits it, and publishing copies only the approved items into a new
dataset version with the provenance that produced them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_dataset_drafts"
down_revision: str | None = "0016_saved_targets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the draft and draft-item tables."""
    op.create_table(
        "dataset_drafts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("app_description", sa.String(length=4000), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("kinds", sa.JSON(), nullable=False),
        sa.Column(
            "generator_provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "generator_provider_name",
            sa.String(length=120),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "generated_by_model",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "prompt_version", sa.String(length=40), nullable=False, server_default=sa.text("''")
        ),
        sa.Column("same_as_judge", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default=sa.text("'draft'")
        ),
        sa.Column(
            "published_dataset_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "published_version_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dataset_drafts_owner_id", "dataset_drafts", ["owner_id"])

    op.create_table(
        "draft_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "draft_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("dataset_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("expected_answer", sa.String(length=2000), nullable=False),
        sa.Column("source_passage", sa.String(length=1000), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "generated_by_model",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "generator_provider",
            sa.String(length=120),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "prompt_version", sa.String(length=40), nullable=False, server_default=sa.text("''")
        ),
        sa.Column(
            "reviewer_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_draft_items_draft_id", "draft_items", ["draft_id"])


def downgrade() -> None:
    """Drop the draft tables."""
    op.drop_index("ix_draft_items_draft_id", table_name="draft_items")
    op.drop_table("draft_items")
    op.drop_index("ix_dataset_drafts_owner_id", table_name="dataset_drafts")
    op.drop_table("dataset_drafts")
