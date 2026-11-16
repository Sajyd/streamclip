"""Plans, subscriptions, usage metering and cost attribution."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    READ,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    access,
    enum_type,
    json_column,
)
from app.models.enums import BillingEventStatus, CostCategory, SubscriptionStatus, UsageKind


class Plan(Base, IdMixin, TimestampMixin):
    """Commercial offer. Prices and quotas live here (not in code) so they can
    be changed from the back-office; Stripe prices are linked by id."""

    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("price_cents >= 0", name="price_non_negative"),
        CheckConstraint("included_seconds >= 0", name="included_non_negative"),
        access(rls=None, app=READ),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    # Tax-inclusive (TTC) monthly price in the smallest currency unit.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="eur")
    included_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_clips_per_session: Mapped[int | None] = mapped_column(Integer)
    max_concurrent_streams: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    clip_retention_days: Mapped[int | None] = mapped_column(Integer)
    features: Mapped[dict[str, Any]] = json_column()
    stripe_product_id: Mapped[str | None] = mapped_column(String(64))
    stripe_price_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Subscription(Base, IdMixin, TimestampMixin, TenantMixin):
    """Local mirror of the tenant's plan. Stripe is the source of truth for
    paid plans and updates this row through webhooks; the Free plan has no
    Stripe subscription."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        # At most one current subscription per tenant.
        Index(
            "uq_subscriptions_current",
            "organization_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        access(rls="tenant", app=READ),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_type(SubscriptionStatus, "status"), nullable=False, default=SubscriptionStatus.ACTIVE
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Ordering guard: ignore webhook events older than the last one applied.
    stripe_event_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsagePeriod(Base, IdMixin, CreatedAtMixin, TenantMixin):
    """Quota ledger header for one billing period. Unused time is not carried over."""

    __tablename__ = "usage_periods"
    __table_args__ = (
        UniqueConstraint("organization_id", "period_start"),
        CheckConstraint("period_end > period_start", name="period_ordered"),
        CheckConstraint("consumed_ms >= 0 AND included_ms >= 0", name="non_negative"),
        access(rls="tenant", app=READ),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    included_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consumed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    warning_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exhausted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageRecord(Base, IdMixin, CreatedAtMixin, TenantMixin):
    """Append-only consumption event. `idempotency_key` makes double metering
    impossible: replaying the same media range inserts nothing."""

    __tablename__ = "usage_records"
    __table_args__ = (access(rls="tenant", app=READ),)

    usage_period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("usage_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Soft reference: usage history outlives the purge of a live session.
    stream_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    kind: Mapped[UsageKind] = mapped_column(enum_type(UsageKind, "kind"), nullable=False)
    quantity_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_start_ms: Mapped[int | None] = mapped_column(BigInteger)
    media_end_ms: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    details: Mapped[dict[str, Any]] = json_column()


class BillingEvent(Base, IdMixin):
    """Processed payment-provider webhooks. The unique event id makes webhook
    handling idempotent; only minimal fields are kept (no customer PII)."""

    __tablename__ = "billing_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"), access(rls=None))

    provider: Mapped[str] = mapped_column(String(16), nullable=False, server_default="stripe")
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    object_id: Mapped[str | None] = mapped_column(String(128))
    livemode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[BillingEventStatus] = mapped_column(
        enum_type(BillingEventStatus, "status"), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    error: Mapped[str | None] = mapped_column(String(1000))
    event_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CostRecord(Base, IdMixin, CreatedAtMixin):
    """Attributable infrastructure / AI spend (internal, never tenant-visible).

    organization_id and stream_session_id are soft references so that cost
    history survives account deletion in pseudonymous form.
    """

    __tablename__ = "cost_records"
    __table_args__ = (
        Index("ix_cost_records_org_time", "organization_id", "occurred_at"),
        access(rls=None),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    stream_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    category: Mapped[CostCategory] = mapped_column(
        enum_type(CostCategory, "category"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    resource: Mapped[str] = mapped_column(String(96), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    unit_cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    pricing_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    details: Mapped[dict[str, Any]] = json_column()
