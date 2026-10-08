from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="owner", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    memberships: Mapped[list[WorkspaceMembership]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="user")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    memberships: Mapped[list[WorkspaceMembership]] = relationship(
        back_populates="workspace"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="workspace")


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(50), default="viewer", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    user: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    user: Mapped[User | None] = relationship(back_populates="audit_logs")
    workspace: Mapped[Workspace | None] = relationship(back_populates="audit_logs")


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(String(2000))
    rpm: Mapped[int] = mapped_column(default=10, nullable=False)
    rpd: Mapped[int] = mapped_column(default=500, nullable=False)
    max_input_tokens: Mapped[int] = mapped_column(default=8192, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(default=2048, nullable=False)
    fallback_provider_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class ConnectorProfile(Base):
    __tablename__ = "connector_profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=False
    )
    entry_point_type: Mapped[str] = mapped_column(String(40), nullable=False)
    settings: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    encrypted_credentials: Mapped[str | None] = mapped_column(String(8000))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    access_level: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class AppVersion(Base):
    __tablename__ = "app_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=False
    )
    connector_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("connector_profiles.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    access_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class JudgeProfile(Base):
    __tablename__ = "judge_profiles"
    __table_args__ = (UniqueConstraint("project_id", "role"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_configs.id"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    temperature: Mapped[float] = mapped_column(default=0.0, nullable=False)
    rubric_prompt: Mapped[str] = mapped_column(
        String(10000), default="", nullable=False
    )
    rubric_version: Mapped[int] = mapped_column(default=1, nullable=False)


class ProjectVerdictCriteria(Base):
    __tablename__ = "project_verdict_criteria"

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), primary_key=True
    )
    criteria: Mapped[dict[str, object]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class ConnectorTest(Base):
    __tablename__ = "connector_tests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    entry_point_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("datasets.id"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    split_strategy: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DatasetItem(Base):
    __tablename__ = "dataset_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_versions.id"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(nullable=False)
    input_text: Mapped[str] = mapped_column(String(20_000), nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(String(20_000))
    reference_context: Mapped[str | None] = mapped_column(String(20_000))
    category: Mapped[str] = mapped_column(String(40), default="normal", nullable=False)
    provenance: Mapped[str] = mapped_column(String(30), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    regression_critical: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    split: Mapped[str] = mapped_column(String(10), default="dev", nullable=False)
    data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=False
    )
    app_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_versions.id"), nullable=False
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_versions.id"), nullable=False
    )
    split: Mapped[str] = mapped_column(String(10), default="all", nullable=False)
    criteria_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    total_items: Mapped[int] = mapped_column(default=0, nullable=False)
    completed_items: Mapped[int] = mapped_column(default=0, nullable=False)
    failed_items: Mapped[int] = mapped_column(default=0, nullable=False)
    pause_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    pause_reason: Mapped[str | None] = mapped_column(String(40))
    celery_task_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class ProjectBaseline(Base):
    __tablename__ = "project_baselines"

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), primary_key=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_runs.id"), unique=True, nullable=False
    )
    approved_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class EvalRunItem(Base):
    __tablename__ = "eval_run_items"
    __table_args__ = (UniqueConstraint("run_id", "dataset_item_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_runs.id"), index=True, nullable=False
    )
    dataset_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_items.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    output: Mapped[str | None] = mapped_column(String(20_000))
    trace: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    scores: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    error: Mapped[str | None] = mapped_column(String(2000))
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class JudgeMetricCache(Base):
    __tablename__ = "judge_metric_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
