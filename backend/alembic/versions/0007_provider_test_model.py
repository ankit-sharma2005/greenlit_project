"""Add a configurable provider connection-test model.

Revision ID: 0007_provider_test_model
Revises: 0006_comparison_regression
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_provider_test_model"
down_revision: str | None = "0006_comparison_regression"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("provider_configs", sa.Column("test_model", sa.String(length=200)))


def downgrade() -> None:
    op.drop_column("provider_configs", "test_model")
