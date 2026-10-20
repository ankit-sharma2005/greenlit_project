"""Flag legacy duplicate names and enforce workspace-scoped uniqueness.

Revision ID: 0008_unique_workspace_names
Revises: 0007_provider_test_model
Create Date: 2026-10-09
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0008_unique_workspace_names"
down_revision: str | None = "0007_provider_test_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_names(table_name: str, name_limit: int = 120) -> None:
    bind = op.get_bind()
    table = sa.table(
        table_name,
        sa.column("id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    rows = bind.execute(
        sa.select(table.c.id, table.c.workspace_id, table.c.name, table.c.created_at)
    ).mappings()
    grouped: dict[tuple[UUID, str], list[dict[str, object]]] = defaultdict(list)
    for result_row in rows:
        grouped[
            (
                result_row["workspace_id"],
                str(result_row["name"]).strip().casefold(),
            )
        ].append(dict(result_row))

    canonical_rows: dict[tuple[UUID, str], dict[str, object]] = {}
    for key, matching_rows in grouped.items():
        matching_rows.sort(
            key=lambda row: (
                row["created_at"] or datetime.min,
                str(row["id"]),
            )
        )
        canonical_rows[key] = dict(matching_rows[0])
    used_names: dict[UUID, set[str]] = defaultdict(set)
    for (workspace_id, _), canonical_row in canonical_rows.items():
        used_names[workspace_id].add(str(canonical_row["name"]).strip().casefold())

    updates = sa.table(
        table_name,
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("name_key", sa.String()),
        sa.column("original_name", sa.String()),
        sa.column("duplicate_of", sa.Uuid()),
    )
    for (workspace_id, name_key), matching_rows in grouped.items():
        canonical_id = canonical_rows[(workspace_id, name_key)]["id"]
        for duplicate_row in matching_rows[1:]:
            original_name = str(duplicate_row["name"])
            suffix = f" [duplicate {str(duplicate_row['id'])[:8]}]"
            name = original_name[: name_limit - len(suffix)] + suffix
            attempt = 1
            while name.strip().casefold() in used_names[workspace_id]:
                attempt += 1
                suffix = f" [duplicate {str(duplicate_row['id'])[:8]}-{attempt}]"
                name = original_name[: name_limit - len(suffix)] + suffix
            used_names[workspace_id].add(name.strip().casefold())
            bind.execute(
                updates.update()
                .where(updates.c.id == duplicate_row["id"])
                .values(
                    name=name,
                    name_key=name.strip().casefold(),
                    original_name=original_name,
                    duplicate_of=canonical_id,
                )
            )
    for (_, name_key), canonical_row in canonical_rows.items():
        original_name = str(canonical_row["name"])
        bind.execute(
            updates.update()
            .where(updates.c.id == canonical_row["id"])
            .values(
                name=original_name,
                name_key=name_key,
                original_name=None,
                duplicate_of=None,
            )
        )


def upgrade() -> None:
    for table_name in ("projects", "provider_configs"):
        op.add_column(table_name, sa.Column("name_key", sa.String(240), nullable=True))
        op.add_column(table_name, sa.Column("original_name", sa.String(120)))
        op.add_column(table_name, sa.Column("duplicate_of", sa.Uuid()))
        _backfill_names(table_name)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("name_key", nullable=False)
    op.create_index(
        "uq_projects_workspace_name_key",
        "projects",
        ["workspace_id", "name_key"],
        unique=True,
    )
    op.create_index(
        "uq_provider_configs_workspace_name_key",
        "provider_configs",
        ["workspace_id", "name_key"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ("projects", "provider_configs"):
        table = sa.table(
            table_name,
            sa.column("id", sa.Uuid()),
            sa.column("name", sa.String()),
            sa.column("original_name", sa.String()),
            sa.column("duplicate_of", sa.Uuid()),
        )
        for row in bind.execute(
            sa.select(table.c.id, table.c.original_name).where(
                table.c.duplicate_of.is_not(None)
            )
        ).mappings():
            bind.execute(
                table.update()
                .where(table.c.id == row["id"])
                .values(name=row["original_name"])
            )
    op.drop_index(
        "uq_provider_configs_workspace_name_key", table_name="provider_configs"
    )
    op.drop_index("uq_projects_workspace_name_key", table_name="projects")
    for table_name in ("projects", "provider_configs"):
        op.drop_column(table_name, "duplicate_of")
        op.drop_column(table_name, "original_name")
        op.drop_column(table_name, "name_key")
