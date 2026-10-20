"""Add owner-scoped chat, workspace preferences, and connector names.

Revision ID: 0009_chat_preferences_connectors
Revises: 0008_unique_workspace_names
Create Date: 2026-10-11
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0009_chat_preferences_connectors"
down_revision: str | None = "0008_unique_workspace_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("connector_profiles") as batch_op:
        batch_op.add_column(sa.Column("provider_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column("display_name", sa.String(length=120), nullable=True)
        )
        batch_op.add_column(sa.Column("name_key", sa.String(length=240), nullable=True))
        batch_op.create_foreign_key(
            "fk_connector_profiles_provider_id",
            "provider_configs",
            ["provider_id"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    connector_table = sa.table(
        "connector_profiles",
        sa.column("id", sa.Uuid()),
        sa.column("project_id", sa.Uuid()),
        sa.column("entry_point_type", sa.String()),
        sa.column("settings", sa.JSON()),
        sa.column("provider_id", sa.Uuid()),
        sa.column("model", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("name_key", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    used_names: dict[UUID, set[str]] = {}
    rows = bind.execute(
        sa.select(
            connector_table.c.id,
            connector_table.c.project_id,
            connector_table.c.entry_point_type,
            connector_table.c.settings,
        ).order_by(connector_table.c.created_at, connector_table.c.id)
    ).mappings()
    for row in rows:
        settings = row["settings"] if isinstance(row["settings"], dict) else {}
        project_id = row["project_id"]
        names = used_names.setdefault(project_id, set())
        display_name = str(
            settings.get("_display_name") or row["entry_point_type"]
        ).strip()[:120]
        name_key = display_name.casefold()
        if name_key in names:
            suffix = f" [duplicate {str(row['id'])[:8]}]"
            display_name = display_name[: 120 - len(suffix)] + suffix
            name_key = display_name.casefold()
        names.add(name_key)
        try:
            provider_id = UUID(str(settings["provider_id"]))
        except (KeyError, ValueError):
            provider_id = None
        model = settings.get("model")
        bind.execute(
            connector_table.update()
            .where(connector_table.c.id == row["id"])
            .values(
                provider_id=provider_id,
                model=str(model)[:200] if model is not None else None,
                display_name=display_name,
                name_key=name_key,
            )
        )

    with op.batch_alter_table("connector_profiles") as batch_op:
        batch_op.alter_column("display_name", nullable=False)
        batch_op.alter_column("name_key", nullable=False)
    op.create_index(
        "uq_connector_profiles_project_name_key",
        "connector_profiles",
        ["project_id", "name_key"],
        unique=True,
    )

    op.create_table(
        "workspace_user_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("default_provider_id", sa.Uuid(), nullable=True),
        sa.Column("active_project_id", sa.Uuid(), nullable=True),
        sa.Column(
            "last_page",
            sa.String(length=80),
            server_default="overview",
            nullable=False,
        ),
        sa.Column("last_entry_point", sa.String(length=40), nullable=True),
        sa.Column("last_column_mapping", sa.JSON(), nullable=True),
        sa.Column(
            "memory_message_count", sa.Integer(), server_default="20", nullable=False
        ),
        sa.Column(
            "memory_token_budget", sa.Integer(), server_default="6000", nullable=False
        ),
        sa.Column(
            "chat_retention_days", sa.Integer(), server_default="30", nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["default_provider_id"], ["provider_configs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["active_project_id"], ["projects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("user_id", "workspace_id"),
    )

    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column(
            "title", sa.String(length=200), server_default="New chat", nullable=False
        ),
        sa.Column(
            "summary", sa.String(length=20000), server_default="", nullable=False
        ),
        sa.Column(
            "summary_message_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_conversations_owner_id", "chat_conversations", ["owner_id"]
    )
    op.create_index(
        "ix_chat_conversations_workspace_id",
        "chat_conversations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_chat_conversations_project_id", "chat_conversations", ["project_id"]
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.String(length=40000), nullable=False),
        sa.Column(
            "context_sent",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("trace", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_conversations_project_id", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_workspace_id", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_owner_id", table_name="chat_conversations")
    op.drop_table("chat_conversations")
    op.drop_table("workspace_user_preferences")
    op.drop_index(
        "uq_connector_profiles_project_name_key", table_name="connector_profiles"
    )
    with op.batch_alter_table("connector_profiles") as batch_op:
        batch_op.drop_constraint(
            "fk_connector_profiles_provider_id", type_="foreignkey"
        )
        batch_op.drop_column("name_key")
        batch_op.drop_column("display_name")
        batch_op.drop_column("model")
        batch_op.drop_column("provider_id")
