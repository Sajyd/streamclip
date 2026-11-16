"""Infrastructure tables: durable task queue, rate limiting, audit, notifications."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    access,
    enum_type,
    json_column,
)
from app.models.enums import ActorType, AuditOutcome, NotificationSeverity, TaskStatus


class Task(Base, IdMixin, TimestampMixin):
    """Durable job queue stored in PostgreSQL.

    Enqueued in the same transaction as the business change (outbox), claimed
    with FOR UPDATE SKIP LOCKED, protected by a lease so that a crashed worker
    never loses a task, and deduplicated by `idempotency_key`.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        Index(
            "ix_tasks_claim",
            "queue",
            "priority",
            "run_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_tasks_lease", "locked_until", postgresql_where=text("status = 'running'")),
        access(rls=None),
    )

    queue: Mapped[str] = mapped_column(String(32), nullable=False, server_default="default")
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = json_column()
    status: Mapped[TaskStatus] = mapped_column(
        enum_type(TaskStatus, "status"), nullable=False, default=TaskStatus.QUEUED
    )
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    # Soft reference used for attribution and fair scheduling.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerNode(Base, IdMixin, CreatedAtMixin):
    """Heartbeat of each worker process (back-office: worker status)."""

    __tablename__ = "worker_nodes"
    __table_args__ = (access(rls=None),)

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    queues: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    stats: Mapped[dict[str, Any]] = json_column()


class RateLimitCounter(Base):
    """Fixed-window counters. UNLOGGED: losing them in a crash is harmless and
    avoids write-ahead-log overhead."""

    __tablename__ = "rate_limit_counters"
    __table_args__ = ({"prefixes": ["UNLOGGED"], **access(rls=None)},)

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class AuditLog(Base, IdMixin):
    """Security and administration journal (append-only for application roles).

    Soft references only: entries survive account deletion without PII
    (IP and user agent are cleared after the retention period).
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_time", "organization_id", "occurred_at"),
        Index("ix_audit_logs_actor_time", "actor_user_id", "occurred_at"),
        access(rls=None),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    actor_type: Mapped[ActorType] = mapped_column(
        enum_type(ActorType, "actor_type"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    outcome: Mapped[AuditOutcome] = mapped_column(
        enum_type(AuditOutcome, "outcome"), nullable=False
    )
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = json_column()


class Notification(Base, IdMixin, CreatedAtMixin, TenantMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        # One notification per (tenant, dedupe key): e.g. the 80 % quota warning.
        UniqueConstraint("organization_id", "dedupe_key"),
        Index("ix_notifications_org_created", "organization_id", "created_at"),
        access(rls="tenant", app=("SELECT", "UPDATE"), app_update_columns=("read_at",)),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[NotificationSeverity] = mapped_column(
        enum_type(NotificationSeverity, "severity"),
        nullable=False,
        default=NotificationSeverity.INFO,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False, server_default="")
    data: Mapped[dict[str, Any]] = json_column()
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformSetting(Base, TimestampMixin):
    """Back-office editable configuration (VAT rate, analysis defaults...)."""

    __tablename__ = "platform_settings"
    __table_args__ = (access(rls=None),)

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[dict[str, Any]] = json_column()
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
