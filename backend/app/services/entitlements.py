"""Plans, subscriptions, billing periods and the processing-time quota.

The quota is enforced here, on the server, from the database. Nothing sent by
a browser is ever trusted to decide what a tenant may consume.
"""

import calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Plan, Subscription, UsagePeriod, UsageRecord
from app.models.enums import NotificationSeverity, SubscriptionStatus, UsageKind
from app.services.notifications import notify

FREE_PLAN_CODE = "free"
QUOTA_WARNING_RATIO = 0.8

# Stripe statuses that keep paid features available. `past_due` stays entitled
# while Stripe retries the payment; `unpaid`/`canceled` fall back to Free.
ENTITLED_STATUSES = frozenset(
    {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE}
)


def add_months(moment: datetime, months: int) -> datetime:
    """Same day next month(s), clamped to the month's length (Jan 31 -> Feb 28)."""
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    included_ms: int
    consumed_ms: int
    period_start: datetime
    period_end: datetime

    @property
    def remaining_ms(self) -> int:
        return max(self.included_ms - self.consumed_ms, 0)

    @property
    def used_ratio(self) -> float:
        if self.included_ms <= 0:
            return 1.0
        return min(self.consumed_ms / self.included_ms, 1.0)

    @property
    def warning(self) -> bool:
        return self.used_ratio >= QUOTA_WARNING_RATIO

    @property
    def exhausted(self) -> bool:
        return self.consumed_ms >= self.included_ms


@dataclass(frozen=True, slots=True)
class Entitlement:
    plan: Plan
    subscription: Subscription
    quota: QuotaSnapshot


def _snapshot(period: UsagePeriod) -> QuotaSnapshot:
    return QuotaSnapshot(
        included_ms=period.included_ms,
        consumed_ms=period.consumed_ms,
        period_start=period.period_start,
        period_end=period.period_end,
    )


async def get_plan_by_code(session: AsyncSession, code: str) -> Plan | None:
    return (await session.execute(select(Plan).where(Plan.code == code))).scalar_one_or_none()


async def list_public_plans(session: AsyncSession) -> list[Plan]:
    result = await session.execute(
        select(Plan)
        .where(Plan.is_public.is_(True), Plan.is_active.is_(True))
        .order_by(Plan.sort_order, Plan.price_cents)
    )
    return list(result.scalars())


async def current_subscription(
    session: AsyncSession, organization_id: uuid.UUID, *, for_update: bool = False
) -> Subscription | None:
    statement = select(Subscription).where(
        Subscription.organization_id == organization_id, Subscription.ended_at.is_(None)
    )
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def ensure_usage_period(
    session: AsyncSession, subscription: Subscription, plan: Plan
) -> UsagePeriod:
    """Return the quota ledger of the subscription's current billing period,
    creating it on first use. A new period always starts with a full quota:
    unused time is not carried over."""
    await session.execute(
        insert(UsagePeriod)
        .values(
            organization_id=subscription.organization_id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            included_ms=plan.included_seconds * 1000,
        )
        .on_conflict_do_nothing(index_elements=["organization_id", "period_start"])
    )
    period = (
        await session.execute(
            select(UsagePeriod)
            .where(
                UsagePeriod.organization_id == subscription.organization_id,
                UsagePeriod.period_start == subscription.current_period_start,
            )
            .with_for_update()
        )
    ).scalar_one()
    return period


async def start_free_subscription(
    session: AsyncSession, organization_id: uuid.UUID, now: datetime
) -> Subscription:
    plan = await get_plan_by_code(session, FREE_PLAN_CODE)
    if plan is None:
        raise RuntimeError("The 'free' plan is missing: run the database migrations")
    subscription = Subscription(
        organization_id=organization_id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE,
        current_period_start=now,
        current_period_end=add_months(now, 1),
    )
    session.add(subscription)
    await session.flush()
    await ensure_usage_period(session, subscription, plan)
    return subscription


async def refresh_billing_period(
    session: AsyncSession, organization_id: uuid.UUID, now: datetime
) -> None:
    """Roll a Free subscription into its next monthly period when due.

    Paid subscriptions are never rolled locally: their periods come from
    Stripe (webhooks), which stays the source of truth for what was paid.
    Requires a system transaction (tenants cannot write billing tables).
    """
    subscription = await current_subscription(session, organization_id, for_update=True)
    if subscription is None:
        await start_free_subscription(session, organization_id, now)
        return
    if subscription.stripe_subscription_id is not None or now < subscription.current_period_end:
        return
    start, end = subscription.current_period_start, subscription.current_period_end
    while end <= now:
        start, end = end, add_months(end, 1)
    subscription.current_period_start, subscription.current_period_end = start, end
    await session.flush()
    plan = await session.get_one(Plan, subscription.plan_id)
    await ensure_usage_period(session, subscription, plan)


async def get_entitlement(session: AsyncSession, organization_id: uuid.UUID) -> Entitlement:
    """Read-only view of the organization's plan and quota (tenant-safe)."""
    row = (
        await session.execute(
            select(Subscription, Plan, UsagePeriod)
            .join(Plan, Plan.id == Subscription.plan_id)
            .join(
                UsagePeriod,
                (UsagePeriod.organization_id == Subscription.organization_id)
                & (UsagePeriod.period_start == Subscription.current_period_start),
            )
            .where(Subscription.organization_id == organization_id, Subscription.ended_at.is_(None))
        )
    ).one_or_none()
    if row is None:
        raise LookupError(f"Organization {organization_id} has no current subscription")
    subscription, plan, period = row
    return Entitlement(plan=plan, subscription=subscription, quota=_snapshot(period))


async def record_usage(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    quantity_ms: int,
    idempotency_key: str,
    kind: UsageKind = UsageKind.LIVE_PROCESSING,
    stream_session_id: uuid.UUID | None = None,
    media_start_ms: int | None = None,
    media_end_ms: int | None = None,
) -> QuotaSnapshot:
    """Charge processed live time against the current period (system tx).

    Idempotent: replaying the same `idempotency_key` (a retried task, a
    duplicated message) charges nothing. Only media that was actually
    processed may be recorded here, never idle or disconnected time.
    """
    if kind is UsageKind.LIVE_PROCESSING and quantity_ms <= 0:
        raise ValueError("quantity_ms must be positive")
    subscription = await current_subscription(session, organization_id)
    if subscription is None:
        raise LookupError(f"Organization {organization_id} has no current subscription")
    plan = await session.get_one(Plan, subscription.plan_id)
    # Row lock: concurrent usage events for one tenant are applied one by one.
    period = await ensure_usage_period(session, subscription, plan)

    inserted = (
        await session.execute(
            insert(UsageRecord)
            .values(
                organization_id=organization_id,
                usage_period_id=period.id,
                stream_session_id=stream_session_id,
                kind=kind,
                quantity_ms=quantity_ms,
                media_start_ms=media_start_ms,
                media_end_ms=media_end_ms,
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(UsageRecord.id)
        )
    ).scalar_one_or_none()
    if inserted is None:
        return _snapshot(period)

    period.consumed_ms = max(period.consumed_ms + quantity_ms, 0)
    snapshot = _snapshot(period)
    now = datetime.now(UTC)
    if snapshot.exhausted and period.exhausted_at is None:
        period.exhausted_at = now
        await notify(
            session,
            organization_id=organization_id,
            kind="quota.exhausted",
            severity=NotificationSeverity.ERROR,
            title="Quota mensuel épuisé",
            body=(
                "Votre temps de live inclus est entièrement consommé. Le traitement "
                "s'arrête jusqu'au prochain renouvellement ou au passage à une offre supérieure."
            ),
            dedupe_key=f"quota-exhausted:{period.id}",
        )
    if snapshot.warning and period.warning_sent_at is None:
        period.warning_sent_at = now
        if not snapshot.exhausted:
            await notify(
                session,
                organization_id=organization_id,
                kind="quota.warning",
                severity=NotificationSeverity.WARNING,
                title="80 % de votre quota consommé",
                body="Vous avez utilisé plus de 80 % du temps de live inclus dans votre offre.",
                dedupe_key=f"quota-warning:{period.id}",
            )
    await session.flush()
    return snapshot
