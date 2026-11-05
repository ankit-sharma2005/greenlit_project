"""users.preferences (account-scoped UI preferences)

Revision ID: 0015_user_preferences
Revises: 0014_run_heartbeat
Create Date: 2026-11-05 10:00:00.000000

The theme used to live only in the browser's localStorage, which every account
on the same browser shared. Storing it on the account keeps two signed-in users
isolated and restores the choice on another device. The column is non-null with
an empty-object default so existing rows keep working (the API fills in the
default theme when a key is missing).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_user_preferences"
down_revision: str | None = "0014_run_heartbeat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the JSON column that holds a user's UI preferences."""
    op.add_column(
        "users",
        sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
