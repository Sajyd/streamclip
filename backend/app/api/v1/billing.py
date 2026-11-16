"""Plans, subscription overview, Checkout, Customer Portal and Stripe webhooks."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, status

from app.api.deps import Ctx, CurrentPrincipal, Meta
from app.billing import service as billing_service
from app.models.billing import Plan
from app.models.identity import Organization
from app.schemas.api import (
    BillingOverview,
    CheckoutRequest,
    PlanList,
    PlanOut,
    QuotaOut,
    UrlResponse,
)
from app.services.entitlements import (
    get_entitlement,
    list_public_plans,
    refresh_billing_period,
)

router = APIRouter(tags=["billing"])


def plan_out(plan: Plan, *, sales_open: bool) -> PlanOut:
    highlights = plan.features.get("highlights", [])
    return PlanOut(
        code=plan.code,
        name=plan.name,
        description=plan.description,
        price_cents=plan.price_cents,
        currency=plan.currency,
        included_seconds=plan.included_seconds,
        max_clips_per_session=plan.max_clips_per_session,
        max_concurrent_streams=plan.max_concurrent_streams,
        clip_retention_days=plan.clip_retention_days,
        features=[str(item) for item in highlights] if isinstance(highlights, list) else [],
        purchasable=sales_open and plan.price_cents > 0 and bool(plan.stripe_price_id),
    )


@router.get("/plans", response_model=PlanList)
async def list_plans(ctx: Ctx) -> PlanList:
    """Public catalogue. Prices and quotas come from the database, so the
    pricing page can never disagree with what is actually sold."""
    async with ctx.db.system_tx() as session:
        plans = await list_public_plans(session)
    return PlanList(
        items=[plan_out(plan, sales_open=billing_service.sales_open(ctx)) for plan in plans],
        vat_rate_percent=ctx.settings.vat_rate_percent,
    )


@router.get("/billing/overview", response_model=BillingOverview)
async def billing_overview(principal: CurrentPrincipal, ctx: Ctx) -> BillingOverview:
    async with ctx.db.system_tx() as session:
        await refresh_billing_period(session, principal.organization_id, datetime.now(UTC))
    async with ctx.db.tenant_tx(principal.tenant) as session:
        entitlement = await get_entitlement(session, principal.organization_id)
        organization = await session.get_one(Organization, principal.organization_id)
    subscription, quota = entitlement.subscription, entitlement.quota
    return BillingOverview(
        plan=plan_out(entitlement.plan, sales_open=billing_service.sales_open(ctx)),
        status=subscription.status.value,
        is_paid=subscription.stripe_subscription_id is not None,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        payment_failed=subscription.payment_failed_at is not None,
        quota=QuotaOut(
            included_seconds=quota.included_ms // 1000,
            consumed_seconds=quota.consumed_ms // 1000,
            remaining_seconds=quota.remaining_ms // 1000,
            used_ratio=round(quota.used_ratio, 4),
            warning=quota.warning,
            exhausted=quota.exhausted,
        ),
        has_billing_account=organization.stripe_customer_id is not None,
        can_manage=principal.can_manage_organization,
        billing_available=ctx.stripe is not None,
        billing_test_mode=ctx.stripe is not None and not ctx.stripe.livemode,
    )


@router.post("/billing/checkout-session", response_model=UrlResponse)
async def create_checkout_session(
    body: CheckoutRequest, principal: CurrentPrincipal, ctx: Ctx, meta: Meta
) -> UrlResponse:
    return UrlResponse(
        url=await billing_service.create_checkout(
            ctx, principal, plan_code=body.plan_code, meta=meta
        )
    )


@router.post("/billing/portal-session", response_model=UrlResponse)
async def create_portal_session(principal: CurrentPrincipal, ctx: Ctx, meta: Meta) -> UrlResponse:
    return UrlResponse(url=await billing_service.create_portal(ctx, principal, meta=meta))


@router.post("/billing/webhooks/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, ctx: Ctx) -> dict[str, str]:
    """Called by Stripe. Authenticated by the signature over the raw body,
    which is why the body is read as bytes and never re-serialised."""
    outcome = await billing_service.handle_webhook(
        ctx, await request.body(), request.headers.get("stripe-signature")
    )
    return {"status": outcome}
