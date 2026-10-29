"""ORM models.

Accounts, providers, datasets and runs live here; the remaining evaluation tables arrive
with their milestones. All primary keys are UUIDs generated in Python so SQLite-based
tests behave like Postgres.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_REVIEWER = "reviewer"
ROLES = (ROLE_ADMIN, ROLE_MEMBER, ROLE_REVIEWER)


def utcnow() -> datetime:
    """Timezone-aware current time used by model defaults."""
    return datetime.now(UTC)


class TimestampMixin:
    """created_at / updated_at on every table, as required by the data model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_MEMBER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(TimestampMixin, Base):
    """Opaque refresh tokens, stored hashed, rotating within a family."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), index=True, default=uuid.uuid4, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class PasswordReset(TimestampMixin, Base):
    """Hashed, single-use password reset tokens."""

    __tablename__ = "password_resets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(TimestampMixin, Base):
    """Append-only audit trail."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout_seconds: Mapped[int] = mapped_column(nullable=False, default=30)
    max_retries: Mapped[int] = mapped_column(nullable=False, default=3)
    backoff_factor: Mapped[float] = mapped_column(nullable=False, default=2.0)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(nullable=True, default=None)
    tokens_per_minute: Mapped[int | None] = mapped_column(nullable=True, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    provider_config: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    connector: Mapped[str] = mapped_column(String(40), nullable=False, default="http_endpoint")

    @property
    def is_free_tier(self) -> bool:
        return self.kind in {"openai-compatible", "groq"} and not self.is_premium and self.is_active

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.model_name})"


class Dataset(TimestampMixin, Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_datasets_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
    )

    columns: Mapped[DatasetColumnMapping] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        uselist=False,
    )
    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DatasetColumnMapping(TimestampMixin, Base):
    __tablename__ = "dataset_column_mappings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    input_column: Mapped[str] = mapped_column(String(120), nullable=False)
    output_column: Mapped[str] = mapped_column(String(120), nullable=False)
    id_column: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retrieved_context_column: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latency_ms_column: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tokens_in_column: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tokens_out_column: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    dataset: Mapped[Dataset] = relationship(
        back_populates="columns",
    )


class DatasetVersion(TimestampMixin, Base):
    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
    )
    row_count: Mapped[int] = mapped_column(nullable=False, default=0)
    columns_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("dataset_id", "version_no", name="uq_dataset_versions_dataset_version_no"),
    )

    dataset: Mapped[Dataset] = relationship(
        back_populates="versions",
    )
    items: Mapped[list[DatasetItem]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )


class DatasetItem(TimestampMixin, Base):
    __tablename__ = "dataset_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    row_index: Mapped[int] = mapped_column(nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("dataset_version_id", "row_index", name="uq_dataset_items_version_row"),
    )

    version: Mapped[DatasetVersion] = relationship(
        back_populates="items",
    )


class RunState(enum.StrEnum):
    """Run lifecycle states (spec 8.1); stored as their plain string values."""

    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class RunItemState(enum.StrEnum):
    """Item lifecycle; a failing item never fails the whole run (spec 8.1)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Run(TimestampMixin, Base):
    """One test run: snapshotted settings, lifecycle state and the verdict."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    criteria_profile: Mapped[str] = mapped_column(
        String(60), nullable=False, default="plain_chatbot"
    )
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=RunState.QUEUED.value)
    verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)
    score: Mapped[float | None] = mapped_column(nullable=True)
    verdict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[RunItem]] = relationship(back_populates="run")
    metric_results: Mapped[list[MetricResultRow]] = relationship(back_populates="run")


class RunItem(TimestampMixin, Base):
    """One dataset case executed inside a run."""

    __tablename__ = "run_items"
    __table_args__ = (UniqueConstraint("run_id", "row_index", name="uq_run_items_run_row_index"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    row_index: Mapped[int] = mapped_column(nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RunItemState.QUEUED.value
    )
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_context: Mapped[list[str] | str | None] = mapped_column(JSON, nullable=True)
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship(back_populates="items")


class MetricResultRow(TimestampMixin, Base):
    """One metric score: per run (``run_item_id`` is NULL) or per run item."""

    __tablename__ = "metric_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    run_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("run_items.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instrumented: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight: Mapped[float] = mapped_column(nullable=False, default=0.0)
    threshold: Mapped[float] = mapped_column(nullable=False, default=0.0)
    hard_gate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    run: Mapped[Run] = relationship(back_populates="metric_results")


class JudgeProfile(TimestampMixin, Base):
    """A saved judge configuration: which model grades, and with what limits (M7).

    ``temperature`` is stored rather than hard-coded so the frozen value (0) is
    visible per profile, and ``is_selected`` marks the one profile new runs use
    by default. Deleting a provider keeps the profile (``SET NULL``) so history
    still explains how a run was judged; the worker then reports it as skipped.
    """

    __tablename__ = "judge_profiles"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_judge_profiles_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rubric_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.0)
    max_tokens: Mapped[int] = mapped_column(nullable=False, default=512)
    # Cost guard: grade at most this many cases per run. NULL means every case,
    # which is what an existing profile keeps after the migration.
    max_cases: Mapped[int | None] = mapped_column(nullable=True, default=None)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


__all__ = [
    "AuditEvent",
    "Dataset",
    "DatasetColumnMapping",
    "DatasetItem",
    "DatasetVersion",
    "JudgeProfile",
    "MetricResultRow",
    "PasswordReset",
    "Provider",
    "RefreshToken",
    "Run",
    "RunItem",
    "RunItemState",
    "RunState",
    "User",
]
