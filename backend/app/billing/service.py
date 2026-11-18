"""Subscriptions: Checkout, Customer Portal and Stripe webhook processing.

Stripe is the source of truth for what a customer pays. This module mirrors
it into `subscriptions` / `usage_periods`, and every entitlement decision is
then taken from that local mirror (fast, and available if Stripe is down).

Webhooks are the only path that grants a paid plan. The Checkout success page
grants nothing: a browser redirect can be forged, replayed or never happen.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import stripe
import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.billing.gateway import StripeGateway
from app.context import AppContext
from app.core import release
from app.core.errors import AppError, ConflictError, PermissionDeniedError, ServiceUnavailableError
from app.models.billing import BillingEvent, Plan, Subscription
from app.models.enums import (
    ActorType,
    BillingEventStatus,
    NotificationSeverity,
    SubscriptionStatus,
)
from app.models.identity import Organization, User
from app.models.system import PlatformSetting
from app.security import rate_limit as limits
from app.services.audit import RequestMeta, audit, audit_independent
from app.services.auth import Principal
from app.services.entitlements import (
    ENTITLED_STATUSES,
    current_subscription,
    ensure_usage_period,
    get_plan_by_code,
    start_free_subscription,
)
from app.services.notifications import notify

log = structlog.get_logger(__name__)

PORTAL_CONFIGURATION_SETTING = "stripe.portal_configuration_id"

SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    }
)
CHECKOUT_EVENTS = frozenset(
    {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
)
INVOICE_EVENTS = frozenset({"invoice.paid", "invoice.payment_failed"})
RISK_EVENTS = frozenset(
    {"charge.dispute.created", "charge.refunded", "radar.early_fraud_warning.created"}
)
# The webhook endpoint subscribes to exactly these: nothing we do not act on.
HANDLED_EVENTS = SUBSCRIPTION_EVENTS | CHECKOUT_EVENTS | INVOICE_EVENTS | RISK_EVENTS


class UnknownCustomerError(Exception):
    """The event concerns a Stripe customer this application does not know."""


def sales_open(ctx: AppContext) -> bool:
    """Whether a paid plan may be bought right now.

    No real money is taken for a service that is not delivered yet: until the
    live pipeline ships, subscriptions can only be bought in Stripe test mode.
    """
    return ctx.stripe is not None and (release.LIVE_PROCESSING_AVAILABLE or not ctx.stripe.livemode)


def _require_stripe(ctx: AppContext) -> StripeGateway:
    if ctx.stripe is None:
        raise ServiceUnavailableError(
            "Le paiement n'est pas encore activé sur cette plateforme.",
            code="billing_unavailable",
        )
    return ctx.stripe


def _require_manager(principal: Principal) -> None:
    if not principal.can_manage_organization:
        raise PermissionDeniedError(
            "Seul un administrateur de l'espace peut gérer l'abonnement.",
            code="insufficient_role",
        )


def _timestamp(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if value else None


def _object_id(value: Any) -> str | None:
    """Stripe fields are either an id or an expanded object."""
    if value is None or isinstance(value, str):
        return value
    return value.get("id") if isinstance(value, dict) else getattr(value, "id", None)


# --- Checkout and portal -----------------------------------------------------


async def _ensure_customer(ctx: AppContext, gateway: StripeGateway, principal: Principal) -> str:
    async with ctx.db.system_tx() as session:
        organization = await session.get_one(Organization, principal.organization_id)
        user = await session.get_one(User, principal.user_id)
    if organization.stripe_customer_id:
        return organization.stripe_customer_id
    customer_id = await gateway.create_customer(
        organization_id=organization.id,
        email=organization.billing_email or user.email,
        name=organization.name,
    )
    async with ctx.db.system_tx() as session:
        await session.execute(
            update(Organization)
            .where(Organization.id == organization.id, Organization.stripe_customer_id.is_(None))
            .values(stripe_customer_id=customer_id)
        )
        stored = await session.execute(
            select(Organization.stripe_customer_id).where(Organization.id == organization.id)
        )
        return str(stored.scalar_one())


async def create_checkout(
    ctx: AppContext, principal: Principal, *, plan_code: str, meta: RequestMeta
) -> str:
    """Return the URL of a Stripe-hosted Checkout page for `plan_code`."""
    gateway = _require_stripe(ctx)
    _require_manager(principal)
    if not sales_open(ctx):
        raise ConflictError(
            "Les offres payantes ouvriront en même temps que le traitement des lives.",
            code="sales_not_open",
        )
    await ctx.rate_limiter.check(limits.CHECKOUT_PER_ORG, str(principal.organization_id))

    async with ctx.db.system_tx() as session:
        plan = await get_plan_by_code(session, plan_code)
        subscription = await current_subscription(session, principal.organization_id)
    # The price comes from our catalogue: the client only names a plan.
    if plan is None or not plan.is_active or plan.price_cents <= 0 or not plan.stripe_price_id:
        raise ConflictError(
            "Cette offre n'est pas disponible à l'achat.", code="plan_not_purchasable"
        )
    if subscription is not None and subscription.stripe_subscription_id is not None:
        raise ConflictError(
            "Vous avez déjà un abonnement. Modifiez-le depuis l'espace de facturation.",
            code="already_subscribed",
        )

    customer_id = await _ensure_customer(ctx, gateway, principal)
    base_url = ctx.settings.public_app_url.rstrip("/")
    url = await gateway.create_checkout_session(
        customer_id=customer_id,
        price_id=plan.stripe_price_id,
        organization_id=principal.organization_id,
        plan_code=plan.code,
        success_url=f"{base_url}/billing?checkout=success",
        cancel_url=f"{base_url}/billing?checkout=canceled",
    )
    await audit_independent(
        ctx.db,
        "billing.checkout_started",
        meta=meta,
        actor_user_id=principal.user_id,
        organization_id=principal.organization_id,
        details={"plan": plan.code},
    )
    return url


async def create_portal(ctx: AppContext, principal: Principal, *, meta: RequestMeta) -> str:
    """Return the URL of the Stripe Customer Portal (plan changes, payment
    method, invoices, cancellation)."""
    gateway = _require_stripe(ctx)
    _require_manager(principal)
    async with ctx.db.system_tx() as session:
        organization = await session.get_one(Organization, principal.organization_id)
        setting = await session.get(PlatformSetting, PORTAL_CONFIGURATION_SETTING)
    if not organization.stripe_customer_id:
        raise ConflictError(
            "Aucun moyen de paiement n'est encore associé à cet espace.", code="no_billing_account"
        )
    url = await gateway.create_portal_session(
        customer_id=organization.stripe_customer_id,
        return_url=f"{ctx.settings.public_app_url.rstrip('/')}/billing",
        configuration_id=(setting.value.get("id") if setting else None),
    )
    await audit_independent(
        ctx.db,
        "billing.portal_opened",
        meta=meta,
        actor_user_id=principal.user_id,
        organization_id=principal.organization_id,
    )
    return url


# --- Subscription mirror -----------------------------------------------------


async def sync_subscription(
    ctx: AppContext,
    gateway: StripeGateway,
    subscription_id: str,
    *,
    event_created: datetime,
    payment_event: str | None = None,
    invoice_id: str | None = None,
) -> None:
    """Make the local mirror match Stripe's current view of one subscription.

    The subscription is re-read from the API instead of trusting the event
    payload: webhooks can arrive late, twice or out of order, and applying the
    latest state is correct in every one of those cases.
    """
    remote = await gateway.retrieve_subscription(subscription_id)
    customer_id = _object_id(remote.get("customer"))
    items = remote["items"]["data"]
    if len(items) != 1:
        raise RuntimeError(f"Subscription {subscription_id} has {len(items)} items, expected 1")
    item = items[0]
    product_id = _object_id(item["price"].get("product"))
    status = SubscriptionStatus(remote["status"])
    period_start = _timestamp(item["current_period_start"])
    period_end = _timestamp(item["current_period_end"])
    if period_start is None or period_end is None:
        raise RuntimeError(f"Subscription {subscription_id} has no billing period")
    now = datetime.now(UTC)

    async with ctx.db.system_tx() as session:
        # Row lock on the organization: events for one tenant apply one by one.
        organization = (
            await session.execute(
                select(Organization)
                .where(Organization.stripe_customer_id == customer_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if organization is None:
            raise UnknownCustomerError(f"No organization for Stripe customer {customer_id}")
        # Mapped through the product: it stays stable when a price is replaced,
        # so customers on a former price keep resolving to their plan.
        plan = (
            await session.execute(select(Plan).where(Plan.stripe_product_id == product_id))
        ).scalar_one_or_none()
        if plan is None:
            raise RuntimeError(f"No plan is linked to Stripe product {product_id}")

        mirror = (
            await session.execute(
                select(Subscription)
                .where(Subscription.stripe_subscription_id == subscription_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        current = await current_subscription(session, organization.id, for_update=True)

        if status in ENTITLED_STATUSES:
            created = mirror is None or mirror.ended_at is not None
            if current is not None and (mirror is None or current.id != mirror.id):
                # Close the Free (or stale) subscription this one replaces.
                current.ended_at = now
                await session.flush()
            if mirror is None:
                mirror = Subscription(
                    organization_id=organization.id,
                    plan_id=plan.id,
                    stripe_subscription_id=subscription_id,
                    status=status,
                    current_period_start=period_start,
                    current_period_end=period_end,
                )
                session.add(mirror)
            mirror.ended_at = None
            mirror.plan_id = plan.id
            mirror.status = status
            mirror.current_period_start = period_start
            mirror.current_period_end = period_end
            mirror.cancel_at_period_end = bool(
                remote.get("cancel_at_period_end") or remote.get("cancel_at")
            )
            mirror.canceled_at = _timestamp(remote.get("canceled_at"))
            mirror.stripe_event_created_at = event_created
            if payment_event == "failed":
                mirror.payment_failed_at = now
            elif payment_event == "paid" or status is SubscriptionStatus.ACTIVE:
                mirror.payment_failed_at = None
            await session.flush()

            # A new billing period gets a fresh quota. Within a period a plan
            # change may raise the quota but never takes paid time away.
            period = await ensure_usage_period(session, mirror, plan)
            period.subscription_id = mirror.id
            period.period_end = period_end
            if period.plan_id != plan.id:
                period.plan_id = plan.id
                period.included_ms = max(period.included_ms, plan.included_seconds * 1000)
                if period.consumed_ms < period.included_ms:
                    period.exhausted_at = None
            if period.consumed_ms < period.included_ms:
                # OBS may still be publishing. Resume that live on the spot
                # that is still up — the user does not restart the stream.
                from app.services.ingest import reopen_quota_paused_session
                from app.services.ingest_nodes import cancel_idle_termination, get_dedicated_node

                node = await get_dedicated_node(session, organization.id)
                if node is not None:
                    resumed = await reopen_quota_paused_session(
                        session,
                        organization_id=organization.id,
                        ingest_node_id=node.id,
                    )
                    if resumed is not None:
                        await cancel_idle_termination(
                            session, organization_id=organization.id, node_id=node.id
                        )

            if created:
                await notify(
                    session,
                    organization_id=organization.id,
                    kind="subscription.activated",
                    severity=NotificationSeverity.SUCCESS,
                    title=f"Offre {plan.name} activée",
                    body="Votre abonnement est actif. Merci !",
                    dedupe_key=f"subscription-activated:{subscription_id}:{period_start.isoformat()}",
                )
            if payment_event == "failed":
                await notify(
                    session,
                    organization_id=organization.id,
                    kind="subscription.payment_failed",
                    severity=NotificationSeverity.ERROR,
                    title="Échec du paiement de votre abonnement",
                    body=(
                        "Le prélèvement a échoué. Mettez à jour votre moyen de paiement "
                        "depuis l'espace de facturation pour conserver votre offre."
                    ),
                    dedupe_key=f"payment-failed:{invoice_id or subscription_id}",
                )
        elif mirror is not None:
            was_current = mirror.ended_at is None
            mirror.status = status
            mirror.canceled_at = _timestamp(remote.get("canceled_at")) or mirror.canceled_at
            mirror.stripe_event_created_at = event_created
            if was_current:
                mirror.ended_at = now
                await session.flush()
                # Paid access is over: the organization returns to the Free plan.
                await start_free_subscription(session, organization.id, now)
                await notify(
                    session,
                    organization_id=organization.id,
                    kind="subscription.ended",
                    severity=NotificationSeverity.WARNING,
                    title="Votre abonnement a pris fin",
                    body="Votre espace est repassé sur l'offre Free.",
                    dedupe_key=f"subscription-ended:{subscription_id}",
                )
        # else: never-activated subscription (first payment pending): nothing to grant.

        audit(
            session,
            "billing.subscription_synced",
            actor_type=ActorType.WEBHOOK,
            organization_id=organization.id,
            target_type="stripe_subscription",
            target_id=subscription_id,
            details={"status": status.value, "plan": plan.code, "payment_event": payment_event},
        )


async def _record_risk_event(
    ctx: AppContext, gateway: StripeGateway, event_type: str, obj: dict[str, Any]
) -> None:
    """Disputes, refunds and fraud warnings: attribute them to the tenant and
    leave an audit entry plus an alert-level log line for the operators."""
    if event_type == "charge.refunded":
        customer_id = _object_id(obj.get("customer"))
        charge_id = obj.get("id")
    else:
        charge_id = _object_id(obj.get("charge"))
        customer_id = await gateway.charge_customer_id(charge_id) if charge_id else None
    async with ctx.db.system_tx() as session:
        organization_id = None
        if customer_id:
            organization_id = (
                await session.execute(
                    select(Organization.id).where(Organization.stripe_customer_id == customer_id)
                )
            ).scalar_one_or_none()
        audit(
            session,
            f"billing.{event_type}",
            actor_type=ActorType.WEBHOOK,
            organization_id=organization_id,
            target_type="stripe_charge",
            target_id=charge_id,
            details={
                "stripe_object": obj.get("id"),
                "amount": obj.get("amount_refunded") or obj.get("amount"),
                "reason": obj.get("reason") or obj.get("fraud_type"),
            },
        )
    log.warning(
        "billing_risk_event",
        event_type=event_type,
        organization_id=str(organization_id) if organization_id else None,
        stripe_object=obj.get("id"),
    )


async def _dispatch(
    ctx: AppContext,
    gateway: StripeGateway,
    event_type: str,
    obj: dict[str, Any],
    event_created: datetime,
) -> None:
    if event_type in SUBSCRIPTION_EVENTS:
        await sync_subscription(ctx, gateway, obj["id"], event_created=event_created)
    elif event_type in CHECKOUT_EVENTS:
        subscription_id = _object_id(obj.get("subscription"))
        if obj.get("mode") == "subscription" and subscription_id:
            await sync_subscription(ctx, gateway, subscription_id, event_created=event_created)
    elif event_type in INVOICE_EVENTS:
        details = (obj.get("parent") or {}).get("subscription_details") or {}
        subscription_id = _object_id(details.get("subscription"))
        if subscription_id:
            await sync_subscription(
                ctx,
                gateway,
                subscription_id,
                event_created=event_created,
                payment_event="paid" if event_type == "invoice.paid" else "failed",
                invoice_id=obj.get("id"),
            )
    elif event_type in RISK_EVENTS:
        await _record_risk_event(ctx, gateway, event_type, obj)


async def _set_event_status(
    ctx: AppContext, event_id: str, status: BillingEventStatus, error: str | None = None
) -> None:
    async with ctx.db.system_tx() as session:
        await session.execute(
            update(BillingEvent)
            .where(BillingEvent.provider == "stripe", BillingEvent.event_id == event_id)
            .values(
                status=status,
                error=error[:1000] if error else None,
                processed_at=datetime.now(UTC) if status is not BillingEventStatus.FAILED else None,
            )
        )


async def handle_webhook(ctx: AppContext, payload: bytes, signature: str | None) -> str:
    """Verify, deduplicate and apply one Stripe event.

    Returns "processed", "ignored" or "duplicate". Raises on failure so that
    the endpoint answers 5xx and Stripe redelivers the event later.
    """
    gateway = _require_stripe(ctx)
    invalid = AppError("Signature invalide.", code="invalid_signature", status_code=400)
    if not signature:
        raise invalid
    try:
        event = gateway.construct_event(payload, signature)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise invalid from exc
    if bool(event.livemode) != gateway.livemode:
        raise AppError("Mode Stripe inattendu.", code="livemode_mismatch", status_code=400)

    data = event.to_dict()
    event_id, event_type = str(data["id"]), str(data["type"])
    obj: dict[str, Any] = data["data"]["object"]
    event_created = _timestamp(data["created"]) or datetime.now(UTC)

    async with ctx.db.system_tx() as session:
        inserted = (
            await session.execute(
                insert(BillingEvent)
                .values(
                    id=uuid.uuid4(),
                    provider="stripe",
                    event_id=event_id,
                    event_type=event_type,
                    object_id=obj.get("id"),
                    livemode=bool(event.livemode),
                    status=BillingEventStatus.RECEIVED,
                    event_created_at=event_created,
                )
                .on_conflict_do_nothing(index_elements=["provider", "event_id"])
                .returning(BillingEvent.id)
            )
        ).scalar_one_or_none()
        if inserted is None:
            existing = (
                await session.execute(
                    select(BillingEvent)
                    .where(BillingEvent.provider == "stripe", BillingEvent.event_id == event_id)
                    .with_for_update()
                )
            ).scalar_one()
            if existing.status in (BillingEventStatus.PROCESSED, BillingEventStatus.IGNORED):
                return "duplicate"
            existing.attempts += 1  # a previous delivery failed: process it again

    if event_type not in HANDLED_EVENTS:
        await _set_event_status(ctx, event_id, BillingEventStatus.IGNORED)
        return "ignored"
    try:
        await _dispatch(ctx, gateway, event_type, obj, event_created)
    except UnknownCustomerError as exc:
        # Not ours (another integration on the same Stripe account): retrying is useless.
        await _set_event_status(ctx, event_id, BillingEventStatus.IGNORED, str(exc))
        log.warning("stripe_event_unknown_customer", event_id=event_id, event_type=event_type)
        return "ignored"
    except Exception as exc:
        await _set_event_status(
            ctx, event_id, BillingEventStatus.FAILED, f"{type(exc).__name__}: {exc}"
        )
        log.error("stripe_event_failed", event_id=event_id, event_type=event_type, exc_info=exc)
        raise
    await _set_event_status(ctx, event_id, BillingEventStatus.PROCESSED)
    log.info("stripe_event_processed", event_id=event_id, event_type=event_type)
    return "processed"
