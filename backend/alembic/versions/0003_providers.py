"""Provider configurations for LLM gateway.

Revision ID: 0003_providers
Revises: 0002_accounts
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_providers"
down_revision: str | None = "0002_accounts"
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
        "providers",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("api_key_encrypted", sa.String(length=512), nullable=True),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column(
            "backoff_factor",
            sa.Float(),
            nullable=False,
            server_default=sa.text("2.0"),
        ),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True),
        sa.Column("tokens_per_minute", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
    )
    op.create_index("ix_providers_name", "providers", ["name"], unique=True)


def downgrade() -> None:
    op.drop_table("providers")
