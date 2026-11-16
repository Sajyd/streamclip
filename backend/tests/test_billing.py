"""Plans, Checkout, Customer Portal and the Stripe webhook state machine.

The Stripe API is replaced by an in-memory fake, but webhook signatures are
verified by the real SDK code, and events have the real payload shape.
"""

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text

from app.context import AppContext
from app.core import release
from app.models.billing import BillingEvent, Plan, Subscription, UsagePeriod
from app.models.enums import BillingEventStatus, SubscriptionStatus
from app.models.system import AuditLog, Notification
from app.services.entitlements import record_usage
from tests.conftest import WEBHOOK_SECRET
from tests.helpers import API, Account, FakeStripeGateway, error_code, register, signed_event

WEBHOOK = f"{API}/billing/webhooks/stripe"
HOUR_MS = 3_600_000


def _period(days_ago: int = 0) -> tuple[datetime, datetime]:
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(days=days_ago)
    return start, start + timedelta(days=30)


async def _deliver(
    client: httpx.AsyncClient,
    event_type: str,
    obj: dict[str, Any],
    *,
    event_id: str | None = None,
    secret: str = WEBHOOK_SECRET,
    **kwargs: Any,
) -> httpx.Response:
    payload, signature = signed_event(secret, event_type, obj, event_id=event_id, **kwargs)
    return await client.post(WEBHOOK, content=payload, headers={"stripe-signature": signature})


async def _customer(client: httpx.AsyncClient, account: Account, plan: str = "starter") -> str:
    """Go through Checkout creation so the organization gets its Stripe customer."""
    response = await client.post(
        f"{API}/billing/checkout-session", headers=account.headers, json={"plan_code": plan}
    )
    assert response.status_code == 200, response.text
    return f"cus_{account.organization_id.hex[:20]}"


async def _subscribe(
    client: httpx.AsyncClient,
    fake_stripe: FakeStripeGateway,
    account: Account,
    *,
    plan: str = "starter",
    subscription_id: str | None = None,
) -> str:
    customer = await _customer(client, account, plan)
    subscription_id = subscription_id or f"sub_{uuid.uuid4().hex[:12]}"
    start, end = _period()
    subscription = fake_stripe.put_subscription(
        subscription_id, customer=customer, plan_code=plan, period_start=start, period_end=end
    )
    response = await _deliver(client, "customer.subscription.created", subscription)
    assert response.status_code == 200 and response.json() == {"status": "processed"}
    return subscription_id


async def _overview(client: httpx.AsyncClient, account: Account) -> dict[str, Any]:
    response = await client.get(f"{API}/billing/overview", headers=account.headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


# --- Catalogue -----------------------------------------------------------------


async def test_public_plans_match_the_commercial_offer(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/plans")  # public: no authentication
    assert response.status_code == 200
    body = response.json()
    assert body["vat_rate_percent"] == 20.0
    offer = [
        (plan["code"], plan["price_cents"], plan["included_seconds"] // 3600, plan["purchasable"])
        for plan in body["items"]
    ]
    assert offer == [
        ("free", 0, 1, False),
        ("starter", 1900, 20, True),
        ("creator", 4900, 60, True),
        ("pro", 9900, 150, True),
        ("business", 19900, 400, True),
    ]
    free = body["items"][0]
    assert free["max_clips_per_session"] == 3 and free["currency"] == "eur"


async def test_new_account_starts_on_the_free_plan(client: httpx.AsyncClient) -> None:
    overview = await _overview(client, await register(client))
    assert overview["plan"]["code"] == "free" and overview["is_paid"] is False
    assert overview["quota"] == {
        "included_seconds": 3600,
        "consumed_seconds": 0,
        "remaining_seconds": 3600,
        "used_ratio": 0.0,
        "warning": False,
        "exhausted": False,
    }
    assert overview["billing_test_mode"] is True and overview["has_billing_account"] is False


# --- Checkout and portal -------------------------------------------------------


async def test_checkout_uses_the_catalogue_price_never_a_client_value(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    response = await client.post(
        f"{API}/billing/checkout-session", headers=account.headers, json={"plan_code": "creator"}
    )
    assert response.status_code == 200
    assert response.json()["url"].startswith("https://checkout.stripe.test/")
    call = fake_stripe.checkout_sessions[0]
    assert call["price_id"] == "price_creator" and call["plan_code"] == "creator"
    assert call["organization_id"] == account.organization_id
    assert call["success_url"] == "http://app.test/billing?checkout=success"

    # The client cannot inject a price, an amount or another organization.
    for payload in (
        {"plan_code": "creator", "price_id": "price_free"},
        {"plan_code": "creator", "amount": 1},
        {"plan_code": "creator", "organization_id": str(uuid.uuid4())},
    ):
        tampered = await client.post(
            f"{API}/billing/checkout-session", headers=account.headers, json=payload
        )
        assert tampered.status_code == 422
    for code in ("free", "does_not_exist"):
        refused = await client.post(
            f"{API}/billing/checkout-session", headers=account.headers, json={"plan_code": code}
        )
        assert refused.status_code == 409 and error_code(refused) == "plan_not_purchasable"
    assert len(fake_stripe.checkout_sessions) == 1

    # Starting a checkout grants nothing by itself.
    assert (await _overview(client, account))["plan"]["code"] == "free"
    async with ctx.db.system_tx() as session:
        actions = (await session.execute(select(AuditLog.action))).scalars().all()
    assert "billing.checkout_started" in actions


async def test_real_money_is_not_taken_before_live_processing_ships(
    client: httpx.AsyncClient,
    fake_stripe: FakeStripeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test-mode subscriptions exercise the whole flow; live keys must not sell
    a service that does not exist yet."""
    account = await register(client)
    monkeypatch.setattr(fake_stripe, "livemode", True)

    plans = (await client.get(f"{API}/plans")).json()["items"]
    assert not any(plan["purchasable"] for plan in plans)
    refused = await client.post(
        f"{API}/billing/checkout-session", headers=account.headers, json={"plan_code": "starter"}
    )
    assert refused.status_code == 409 and error_code(refused) == "sales_not_open"
    assert fake_stripe.checkout_sessions == []

    monkeypatch.setattr(release, "LIVE_PROCESSING_AVAILABLE", True)
    plans = (await client.get(f"{API}/plans")).json()["items"]
    assert [plan["code"] for plan in plans if plan["purchasable"]] == [
        "starter",
        "creator",
        "pro",
        "business",
    ]
    accepted = await client.post(
        f"{API}/billing/checkout-session", headers=account.headers, json={"plan_code": "starter"}
    )
    assert accepted.status_code == 200 and len(fake_stripe.checkout_sessions) == 1


async def test_billing_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    for method, path in (
        ("GET", "/billing/overview"),
        ("POST", "/billing/checkout-session"),
        ("POST", "/billing/portal-session"),
    ):
        response = await client.request(method, f"{API}{path}", json={"plan_code": "starter"})
        assert response.status_code == 401, path


async def test_portal_requires_a_billing_account(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway
) -> None:
    account = await register(client)
    response = await client.post(f"{API}/billing/portal-session", headers=account.headers)
    assert response.status_code == 409 and error_code(response) == "no_billing_account"

    customer = await _customer(client, account)
    response = await client.post(f"{API}/billing/portal-session", headers=account.headers)
    assert response.status_code == 200
    assert fake_stripe.portal_sessions[0]["customer_id"] == customer
    assert fake_stripe.portal_sessions[0]["return_url"] == "http://app.test/billing"


async def test_subscribed_organization_cannot_start_a_second_checkout(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway
) -> None:
    account = await register(client)
    await _subscribe(client, fake_stripe, account)
    response = await client.post(
        f"{API}/billing/checkout-session", headers=account.headers, json={"plan_code": "pro"}
    )
    assert response.status_code == 409 and error_code(response) == "already_subscribed"


async def test_billing_reports_unavailable_when_stripe_is_not_configured(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    gateway, ctx.stripe = ctx.stripe, None
    try:
        checkout = await client.post(
            f"{API}/billing/checkout-session", headers=account.headers, json={"plan_code": "pro"}
        )
        plans = (await client.get(f"{API}/plans")).json()["items"]
        overview = await _overview(client, account)
    finally:
        ctx.stripe = gateway
    assert checkout.status_code == 503 and error_code(checkout) == "billing_unavailable"
    assert not any(plan["purchasable"] for plan in plans)  # no dead "subscribe" button
    assert overview["billing_available"] is False


# --- Webhook authentication ----------------------------------------------------


async def test_webhook_rejects_unsigned_forged_and_replayed_events(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    customer = await _customer(client, account)
    start, end = _period()
    subscription = fake_stripe.put_subscription(
        "sub_forged", customer=customer, plan_code="business", period_start=start, period_end=end
    )
    payload, signature = signed_event(WEBHOOK_SECRET, "customer.subscription.created", subscription)

    unsigned = await client.post(WEBHOOK, content=payload)
    wrong_secret = await _deliver(
        client, "customer.subscription.created", subscription, secret="whsec_attacker"
    )
    tampered = await client.post(
        WEBHOOK,
        content=payload.replace(b"sub_forged", b"sub_other!"),
        headers={"stripe-signature": signature},
    )
    replayed = await _deliver(  # valid signature, but older than the tolerance window
        client, "customer.subscription.created", subscription, timestamp=int(time.time()) - 3600
    )
    garbage = await client.post(WEBHOOK, content=payload, headers={"stripe-signature": "nonsense"})
    for response in (unsigned, wrong_secret, tampered, replayed, garbage):
        assert response.status_code == 400 and error_code(response) == "invalid_signature"

    live = await _deliver(client, "customer.subscription.created", subscription, livemode=True)
    assert live.status_code == 400 and error_code(live) == "livemode_mismatch"

    # Nothing was granted and nothing was recorded.
    assert (await _overview(client, account))["plan"]["code"] == "free"
    async with ctx.db.system_tx() as session:
        assert (await session.execute(select(BillingEvent))).first() is None


# --- Subscription lifecycle ----------------------------------------------------


async def test_subscription_webhook_activates_the_paid_plan(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    subscription_id = await _subscribe(client, fake_stripe, account, plan="creator")

    overview = await _overview(client, account)
    assert overview["plan"]["code"] == "creator" and overview["is_paid"] is True
    assert overview["status"] == "active" and overview["payment_failed"] is False
    assert overview["quota"]["included_seconds"] == 60 * 3600
    assert overview["quota"]["consumed_seconds"] == 0

    async with ctx.db.system_tx() as session:
        subscriptions = (
            (
                await session.execute(
                    select(Subscription)
                    .where(Subscription.organization_id == account.organization_id)
                    .order_by(Subscription.created_at)
                )
            )
            .scalars()
            .all()
        )
        event = (await session.execute(select(BillingEvent))).scalar_one()
    free, paid = subscriptions
    assert free.stripe_subscription_id is None and free.ended_at is not None
    assert paid.stripe_subscription_id == subscription_id and paid.ended_at is None
    assert event.status is BillingEventStatus.PROCESSED and event.livemode is False

    notifications = (await client.get(f"{API}/notifications", headers=account.headers)).json()
    assert [item["kind"] for item in notifications["items"]] == ["subscription.activated"]


async def test_duplicate_and_concurrent_deliveries_are_applied_once(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    customer = await _customer(client, account)
    start, end = _period()
    subscription = fake_stripe.put_subscription(
        "sub_dup", customer=customer, plan_code="starter", period_start=start, period_end=end
    )
    first = await _deliver(client, "customer.subscription.created", subscription, event_id="evt_1")
    again = await _deliver(client, "customer.subscription.created", subscription, event_id="evt_1")
    assert first.json() == {"status": "processed"} and again.json() == {"status": "duplicate"}
    assert again.status_code == 200  # acknowledged, so Stripe stops retrying

    # Stripe sends several events for one change (created, updated, checkout
    # completed, invoice paid): together they still produce a single state.
    invoice = {
        "id": "in_1",
        "object": "invoice",
        "parent": {"subscription_details": {"subscription": "sub_dup"}},
    }
    checkout = {
        "id": "cs_1",
        "object": "checkout.session",
        "mode": "subscription",
        "subscription": "sub_dup",
    }
    for event_type, obj in (
        ("customer.subscription.updated", subscription),
        ("checkout.session.completed", checkout),
        ("invoice.paid", invoice),
    ):
        response = await _deliver(client, event_type, obj)
        assert response.json() == {"status": "processed"}, event_type

    async with ctx.db.system_tx() as session:
        current = (
            (await session.execute(select(Subscription).where(Subscription.ended_at.is_(None))))
            .scalars()
            .all()
        )
        periods = (await session.execute(select(UsagePeriod))).scalars().all()
        notifications = (await session.execute(select(Notification.kind))).scalars().all()
    assert len(current) == 1 and current[0].stripe_subscription_id == "sub_dup"
    assert len(periods) == 2  # the Free period and one paid period
    assert notifications == ["subscription.activated"]


async def test_events_for_other_integrations_are_acknowledged_and_ignored(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    start, end = _period()
    foreign = fake_stripe.put_subscription(
        "sub_foreign",
        customer="cus_someone_else",
        plan_code="starter",
        period_start=start,
        period_end=end,
    )
    unknown_customer = await _deliver(client, "customer.subscription.created", foreign)
    unhandled_type = await _deliver(
        client, "customer.created", {"id": "cus_x", "object": "customer"}
    )
    for response in (unknown_customer, unhandled_type):
        assert response.status_code == 200 and response.json() == {"status": "ignored"}
    async with ctx.db.system_tx() as session:
        statuses = (await session.execute(select(BillingEvent.status))).scalars().all()
    assert statuses == [BillingEventStatus.IGNORED] * 2


async def test_failed_processing_answers_5xx_and_succeeds_on_redelivery(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    customer = await _customer(client, account)
    start, end = _period()
    subscription = fake_stripe.put_subscription(
        "sub_retry", customer=customer, plan_code="pro", period_start=start, period_end=end
    )
    fake_stripe.retrieve_failures_to_inject = 1
    transport = httpx.ASGITransport(app=client._transport.app, raise_app_exceptions=False)  # type: ignore[attr-defined]
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as tolerant:
        failed = await _deliver(
            tolerant, "customer.subscription.created", subscription, event_id="evt_retry"
        )
    assert failed.status_code == 500 and error_code(failed) == "internal_error"
    assert "simulated" not in failed.text  # internals are not disclosed
    async with ctx.db.system_tx() as session:
        event = (await session.execute(select(BillingEvent))).scalar_one()
    assert event.status is BillingEventStatus.FAILED and "APIConnectionError" in (event.error or "")
    assert (await _overview(client, account))["plan"]["code"] == "free"

    retried = await _deliver(
        client, "customer.subscription.created", subscription, event_id="evt_retry"
    )
    assert retried.json() == {"status": "processed"}
    async with ctx.db.system_tx() as session:
        event = (await session.execute(select(BillingEvent))).scalar_one()
    assert event.status is BillingEventStatus.PROCESSED and event.attempts == 2
    assert event.error is None
    assert (await _overview(client, account))["plan"]["code"] == "pro"


async def test_renewal_opens_a_new_period_with_a_full_quota(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    subscription_id = await _subscribe(client, fake_stripe, account, plan="starter")
    async with ctx.db.system_tx() as session:
        await record_usage(
            session,
            organization_id=account.organization_id,
            quantity_ms=15 * HOUR_MS,
            idempotency_key="usage-1",
        )
    assert (await _overview(client, account))["quota"]["consumed_seconds"] == 15 * 3600

    customer = f"cus_{account.organization_id.hex[:20]}"
    next_start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=30)
    fake_stripe.put_subscription(
        subscription_id,
        customer=customer,
        plan_code="starter",
        period_start=next_start,
        period_end=next_start + timedelta(days=30),
    )
    invoice = {
        "id": "in_renewal",
        "object": "invoice",
        "parent": {"subscription_details": {"subscription": subscription_id}},
    }
    assert (await _deliver(client, "invoice.paid", invoice)).json() == {"status": "processed"}

    overview = await _overview(client, account)
    assert overview["quota"]["consumed_seconds"] == 0  # unused time is not carried over...
    assert overview["quota"]["included_seconds"] == 20 * 3600
    async with ctx.db.system_tx() as session:
        consumed = (
            (
                await session.execute(
                    select(UsagePeriod.consumed_ms)
                    .where(UsagePeriod.organization_id == account.organization_id)
                    .order_by(UsagePeriod.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert consumed == [0, 15 * HOUR_MS, 0]  # ...and history is kept: free, month 1, month 2


async def test_plan_change_within_a_period_raises_the_quota_but_keeps_consumption(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    subscription_id = await _subscribe(client, fake_stripe, account, plan="starter")
    async with ctx.db.system_tx() as session:
        await record_usage(
            session,
            organization_id=account.organization_id,
            quantity_ms=20 * HOUR_MS,
            idempotency_key="usage-all",
        )
    assert (await _overview(client, account))["quota"]["exhausted"] is True

    current = fake_stripe.subscriptions[subscription_id]
    item = current["items"]["data"][0]
    item["price"] = {"id": "price_pro", "product": "prod_pro"}  # same period, higher plan
    assert (await _deliver(client, "customer.subscription.updated", current)).status_code == 200
    overview = await _overview(client, account)
    assert overview["plan"]["code"] == "pro"
    assert overview["quota"]["included_seconds"] == 150 * 3600
    assert overview["quota"]["consumed_seconds"] == 20 * 3600
    assert overview["quota"]["exhausted"] is False

    # Moving down inside the same period never removes time already paid for.
    item["price"] = {"id": "price_starter", "product": "prod_starter"}
    assert (await _deliver(client, "customer.subscription.updated", current)).status_code == 200
    overview = await _overview(client, account)
    assert overview["plan"]["code"] == "starter"
    assert overview["quota"]["included_seconds"] == 150 * 3600


async def test_payment_failure_keeps_access_during_retries_then_recovers(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway
) -> None:
    account = await register(client)
    subscription_id = await _subscribe(client, fake_stripe, account, plan="creator")
    invoice = {
        "id": "in_fail",
        "object": "invoice",
        "parent": {"subscription_details": {"subscription": subscription_id}},
    }

    fake_stripe.subscriptions[subscription_id]["status"] = "past_due"
    for _ in range(2):  # Stripe retries the charge: one notification, not two
        assert (await _deliver(client, "invoice.payment_failed", invoice)).status_code == 200
    overview = await _overview(client, account)
    assert overview["plan"]["code"] == "creator" and overview["status"] == "past_due"
    assert overview["payment_failed"] is True
    kinds = [
        item["kind"]
        for item in (await client.get(f"{API}/notifications", headers=account.headers)).json()[
            "items"
        ]
    ]
    assert kinds.count("subscription.payment_failed") == 1

    fake_stripe.subscriptions[subscription_id]["status"] = "active"
    assert (await _deliver(client, "invoice.paid", invoice)).status_code == 200
    overview = await _overview(client, account)
    assert overview["status"] == "active" and overview["payment_failed"] is False


async def test_scheduled_cancellation_then_end_returns_to_the_free_plan(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    subscription_id = await _subscribe(client, fake_stripe, account, plan="pro")
    remote = fake_stripe.subscriptions[subscription_id]

    remote["cancel_at_period_end"] = True
    assert (await _deliver(client, "customer.subscription.updated", remote)).status_code == 200
    overview = await _overview(client, account)
    assert overview["plan"]["code"] == "pro" and overview["cancel_at_period_end"] is True

    remote["status"] = "canceled"
    remote["canceled_at"] = int(time.time())
    assert (await _deliver(client, "customer.subscription.deleted", remote)).status_code == 200
    overview = await _overview(client, account)
    assert overview["plan"]["code"] == "free" and overview["is_paid"] is False
    assert overview["quota"]["included_seconds"] == 3600
    assert overview["cancel_at_period_end"] is False

    # A late, out-of-order event about the dead subscription changes nothing:
    # the current state is always re-read from Stripe.
    late = await _deliver(client, "customer.subscription.updated", {**remote, "status": "active"})
    assert late.status_code == 200
    assert (await _overview(client, account))["plan"]["code"] == "free"

    async with ctx.db.system_tx() as session:
        rows = (
            await session.execute(
                select(Subscription.status, Subscription.ended_at.is_(None))
                .where(Subscription.organization_id == account.organization_id)
                .order_by(Subscription.created_at)
            )
        ).all()
    assert [(status, current) for status, current in rows] == [
        (SubscriptionStatus.ACTIVE, False),  # initial Free
        (SubscriptionStatus.CANCELED, False),  # the paid subscription
        (SubscriptionStatus.ACTIVE, True),  # Free again
    ]
    kinds = [
        item["kind"]
        for item in (await client.get(f"{API}/notifications", headers=account.headers)).json()[
            "items"
        ]
    ]
    assert kinds == ["subscription.ended", "subscription.activated"]

    # The customer may subscribe again later.
    await _subscribe(client, fake_stripe, account, plan="starter")
    assert (await _overview(client, account))["plan"]["code"] == "starter"


async def test_unpaid_subscription_loses_access_and_can_be_reinstated(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway
) -> None:
    account = await register(client)
    subscription_id = await _subscribe(client, fake_stripe, account, plan="creator")
    remote = fake_stripe.subscriptions[subscription_id]

    remote["status"] = "unpaid"
    assert (await _deliver(client, "customer.subscription.updated", remote)).status_code == 200
    assert (await _overview(client, account))["plan"]["code"] == "free"

    remote["status"] = "active"
    assert (await _deliver(client, "customer.subscription.updated", remote)).status_code == 200
    overview = await _overview(client, account)
    assert overview["plan"]["code"] == "creator" and overview["is_paid"] is True


async def test_incomplete_first_payment_grants_nothing(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway
) -> None:
    account = await register(client)
    customer = await _customer(client, account)
    start, end = _period()
    pending = fake_stripe.put_subscription(
        "sub_incomplete",
        customer=customer,
        plan_code="business",
        status="incomplete",
        period_start=start,
        period_end=end,
    )
    assert (await _deliver(client, "customer.subscription.created", pending)).status_code == 200
    assert (await _overview(client, account))["plan"]["code"] == "free"


async def test_disputes_and_refunds_are_attributed_and_audited(
    client: httpx.AsyncClient, fake_stripe: FakeStripeGateway, ctx: AppContext
) -> None:
    account = await register(client)
    customer = await _customer(client, account)
    fake_stripe.charges["ch_1"] = customer
    dispute = {
        "id": "dp_1",
        "object": "dispute",
        "charge": "ch_1",
        "amount": 4900,
        "reason": "fraudulent",
    }
    refund = {"id": "ch_1", "object": "charge", "customer": customer, "amount_refunded": 4900}
    assert (await _deliver(client, "charge.dispute.created", dispute)).status_code == 200
    assert (await _deliver(client, "charge.refunded", refund)).status_code == 200
    async with ctx.db.system_tx() as session:
        entries = (
            await session.execute(
                select(AuditLog.action, AuditLog.organization_id, AuditLog.target_id)
                .where(AuditLog.action.like("billing.charge.%"))
                .order_by(AuditLog.occurred_at)
            )
        ).all()
    assert [tuple(entry) for entry in entries] == [
        ("billing.charge.dispute.created", account.organization_id, "ch_1"),
        ("billing.charge.refunded", account.organization_id, "ch_1"),
    ]


async def test_plan_catalogue_changes_apply_without_code_change(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """Prices and quotas live in the database (back-office configurable)."""
    async with ctx.db.system_tx() as session:
        plan = (await session.execute(select(Plan).where(Plan.code == "starter"))).scalar_one()
        original = (plan.price_cents, plan.included_seconds)
        plan.price_cents, plan.included_seconds = 2400, 25 * 3600
    try:
        items = (await client.get(f"{API}/plans")).json()["items"]
        starter = next(item for item in items if item["code"] == "starter")
        assert (starter["price_cents"], starter["included_seconds"]) == (2400, 25 * 3600)
    finally:
        async with ctx.db.system_tx() as session:
            await session.execute(
                text(
                    "UPDATE plans SET price_cents = :p, included_seconds = :s"
                    " WHERE code = 'starter'"
                ),
                {"p": original[0], "s": original[1]},
            )
