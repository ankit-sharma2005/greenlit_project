"""Add provider, project, connector, and judge profile records.

Revision ID: 0002_phase2
Revises: 0001_initial
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app import models as _models  # noqa: F401
from app.db import Base

revision: str = "0002_phase2"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    phase2_table_names = (
        "provider_configs",
        "projects",
        "connector_profiles",
        "app_versions",
        "judge_profiles",
        "connector_tests",
    )
    existing_tables = set(sa.inspect(bind).get_table_names())
    if existing_tables.intersection(phase2_table_names):
        # Repair databases where prior startup created metadata before Alembic ran.
        phase2_tables = [
            Base.metadata.tables[table_name] for table_name in phase2_table_names
        ]
        Base.metadata.create_all(bind=bind, tables=phase2_tables, checkfirst=True)
        return

    op.create_table(
        "provider_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=40), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("api_key_encrypted", sa.String(length=2000), nullable=True),
        sa.Column("rpm", sa.Integer(), nullable=False),
        sa.Column("rpd", sa.Integer(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("fallback_provider_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_configs_workspace_id", "provider_configs", ["workspace_id"]
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])

    op.create_table(
        "connector_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("entry_point_type", sa.String(length=40), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("encrypted_credentials", sa.String(length=8000), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("access_level", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connector_profiles_project_id", "connector_profiles", ["project_id"]
    )

    op.create_table(
        "app_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("connector_profile_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("access_level", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["connector_profile_id"], ["connector_profiles.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_versions_project_id", "app_versions", ["project_id"])

    op.create_table(
        "judge_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("rubric_prompt", sa.String(length=10000), nullable=False),
        sa.Column("rubric_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["provider_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "role"),
    )
    op.create_index("ix_judge_profiles_project_id", "judge_profiles", ["project_id"])

    op.create_table(
        "connector_tests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entry_point_type", sa.String(length=40), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connector_tests_workspace_id", "connector_tests", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_connector_tests_workspace_id", table_name="connector_tests")
    op.drop_table("connector_tests")
    op.drop_index("ix_judge_profiles_project_id", table_name="judge_profiles")
    op.drop_table("judge_profiles")
    op.drop_index("ix_app_versions_project_id", table_name="app_versions")
    op.drop_table("app_versions")
    op.drop_index("ix_connector_profiles_project_id", table_name="connector_profiles")
    op.drop_table("connector_profiles")
    op.drop_index("ix_projects_workspace_id", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_provider_configs_workspace_id", table_name="provider_configs")
    op.drop_table("provider_configs")
