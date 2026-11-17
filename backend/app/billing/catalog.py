"""Idempotent provisioning of the Stripe account from the plans table.

Running it twice changes nothing. It creates or updates, for the Stripe
account the configured key belongs to:

* one Product per paid plan (stable id `streamclip_plan_<code>`);
* one monthly Price per plan, tax-inclusive, addressed by a lookup key. When
  a plan's amount changes, a new Price is created and takes over the lookup
  key; the former Price is archived (existing subscribers keep it);
* the Customer Portal configuration (plan changes, cancellation, invoices);
* the webhook endpoint, subscribed only to the events the application handles.
"""

from dataclasses import dataclass, field
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.service import HANDLED_EVENTS, PORTAL_CONFIGURATION_SETTING
from app.models.billing import Plan
from app.models.system import PlatformSetting

MANAGED_FLAG = "streamclip_managed"


@dataclass(slots=True)
class CatalogSyncResult:
    account_id: str = ""
    livemode: bool = False
    plans: dict[str, dict[str, str]] = field(default_factory=dict)
    portal_configuration_id: str = ""
    webhook_endpoint_id: str | None = None
    # Only set when the endpoint was created now: Stripe reveals it once.
    webhook_secret: str | None = None
    actions: list[str] = field(default_factory=list)


def product_id_for(plan_code: str) -> str:
    return f"streamclip_plan_{plan_code}"


def lookup_key_for(plan_code: str) -> str:
    return f"streamclip_{plan_code}_monthly"


def _sync_product(client: stripe.StripeClient, plan: Plan, result: CatalogSyncResult) -> str:
    product_id = product_id_for(plan.code)
    name = f"STREAMCLIP {plan.name}"
    description = plan.description or None
    # Stripe's parameter types are deeply nested TypedDicts; these payloads are
    # built dynamically, so they are passed as plain mappings.
    wanted: Any = {
        "name": name,
        "metadata": {MANAGED_FLAG: "true", "plan_code": plan.code},
    }
    if description:
        wanted["description"] = description
    try:
        product = client.v1.products.retrieve(product_id)
    except stripe.InvalidRequestError as exc:
        if exc.code != "resource_missing":
            raise
        creation: Any = {"id": product_id, **wanted}
        client.v1.products.create(creation)
        result.actions.append(f"created product {product_id}")
        return product_id
    if product.name != name or (product.description or None) != description or not product.active:
        # An empty string clears the description on Stripe's side.
        update: Any = {**wanted, "description": description or "", "active": True}
        client.v1.products.update(product_id, update)
        result.actions.append(f"updated product {product_id}")
    return product_id


def _sync_price(
    client: stripe.StripeClient, plan: Plan, product_id: str, result: CatalogSyncResult
) -> str:
    lookup_key = lookup_key_for(plan.code)
    existing = client.v1.prices.list({"lookup_keys": [lookup_key], "active": True, "limit": 1}).data
    current = existing[0] if existing else None
    if (
        current is not None
        and current.unit_amount == plan.price_cents
        and current.currency == plan.currency
        and current.recurring is not None
        and current.recurring.interval == "month"
        and current.recurring.interval_count == 1
        and current.tax_behavior == "inclusive"
        and current.product == product_id
    ):
        return current.id
    price = client.v1.prices.create(
        {
            "product": product_id,
            "currency": plan.currency,
            "unit_amount": plan.price_cents,
            "recurring": {"interval": "month", "interval_count": 1},
            # Catalogue prices are displayed tax-inclusive (TTC).
            "tax_behavior": "inclusive",
            "lookup_key": lookup_key,
            "transfer_lookup_key": True,
            "nickname": f"{plan.name} mensuel",
            "metadata": {MANAGED_FLAG: "true", "plan_code": plan.code},
        }
    )
    result.actions.append(f"created price {price.id} for {plan.code}")
    if current is not None:
        client.v1.prices.update(current.id, {"active": False})
        result.actions.append(f"archived price {current.id}")
    return price.id


def _is_managed(metadata: Any) -> bool:
    """True for objects this module created. Stripe objects are not dicts:
    their content is read through `to_dict()`."""
    if metadata is None:
        return False
    values = metadata if isinstance(metadata, dict) else metadata.to_dict()
    return bool(values.get(MANAGED_FLAG) == "true")


def _sync_portal(
    client: stripe.StripeClient,
    plans: list[tuple[Plan, str, str]],
    app_url: str,
    result: CatalogSyncResult,
) -> str:
    features: Any = {
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "customer_update": {
            "enabled": True,
            "allowed_updates": ["email", "name", "address", "tax_id"],
        },
        "subscription_cancel": {
            "enabled": True,
            # The paid period stays usable until its end; no refund computation.
            "mode": "at_period_end",
            "cancellation_reason": {
                "enabled": True,
                "options": [
                    "too_expensive",
                    "missing_features",
                    "unused",
                    "switched_service",
                    "other",
                ],
            },
        },
        "subscription_update": {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "products": [
                {"product": product_id, "prices": [price_id]} for _, product_id, price_id in plans
            ],
            # Upgrade: starts a new billing period now, charged immediately with
            # credit for the unused part of the old plan. The quota therefore
            # always matches a fully paid period.
            "proration_behavior": "always_invoice",
            "billing_cycle_anchor": "now",
            # Downgrade: takes effect at the end of the period already paid.
            "schedule_at_period_end": {"conditions": [{"type": "decreasing_item_amount"}]},
        },
    }
    params: Any = {
        "name": "STREAMCLIP",
        "features": features,
        "default_return_url": f"{app_url.rstrip('/')}/billing",
        "business_profile": {"headline": "Gérez votre abonnement STREAMCLIP"},
        "metadata": {MANAGED_FLAG: "true"},
    }
    managed = [
        configuration
        for configuration in client.v1.billing_portal.configurations.list({"limit": 100}).data
        if configuration.active and _is_managed(configuration.metadata)
    ]
    if managed:
        configuration_id = managed[0].id
        client.v1.billing_portal.configurations.update(configuration_id, params)
        result.actions.append(f"updated portal configuration {configuration_id}")
        return configuration_id
    created = client.v1.billing_portal.configurations.create(params)
    result.actions.append(f"created portal configuration {created.id}")
    return created.id


def _sync_webhook(
    client: stripe.StripeClient, url: str, rotate: bool, result: CatalogSyncResult
) -> None:
    events: Any = sorted(HANDLED_EVENTS)
    api_version: Any = stripe.api_version
    for endpoint in client.v1.webhook_endpoints.list({"limit": 100}).data:
        if endpoint.url != url:
            continue
        if not rotate:
            client.v1.webhook_endpoints.update(
                endpoint.id, {"enabled_events": events, "disabled": False}
            )
            result.webhook_endpoint_id = endpoint.id
            result.actions.append(f"updated webhook endpoint {endpoint.id}")
            return
        client.v1.webhook_endpoints.delete(endpoint.id)
        result.actions.append(f"deleted webhook endpoint {endpoint.id} (rotation)")
    created = client.v1.webhook_endpoints.create(
        {
            "url": url,
            "enabled_events": events,
            # Pinned: events keep this shape even if the account default changes.
            "api_version": api_version,
            "description": "STREAMCLIP - subscription lifecycle",
            "metadata": {MANAGED_FLAG: "true"},
        }
    )
    result.webhook_endpoint_id = created.id
    result.webhook_secret = created.secret
    result.actions.append(f"created webhook endpoint {created.id}")


async def sync_catalog(
    session: AsyncSession,
    client: stripe.StripeClient,
    *,
    app_url: str,
    livemode: bool,
    webhook_url: str | None = None,
    rotate_webhook_secret: bool = False,
) -> CatalogSyncResult:
    """Synchronise Stripe with the plans table (run inside a system transaction).

    The Stripe calls are synchronous: this is an operator command, not a
    request path.
    """
    result = CatalogSyncResult()
    account = client.v1.accounts.retrieve_current()
    result.account_id = account.id
    result.livemode = livemode

    plans = (
        await session.execute(
            select(Plan)
            .where(Plan.is_active.is_(True), Plan.price_cents > 0)
            .order_by(Plan.sort_order)
        )
    ).scalars()
    synced: list[tuple[Plan, str, str]] = []
    for plan in plans:
        product_id = _sync_product(client, plan, result)
        price_id = _sync_price(client, plan, product_id, result)
        plan.stripe_product_id, plan.stripe_price_id = product_id, price_id
        synced.append((plan, product_id, price_id))
        result.plans[plan.code] = {"product": product_id, "price": price_id}
    if not synced:
        raise RuntimeError("No paid plan found: run the database migrations first")

    result.portal_configuration_id = _sync_portal(client, synced, app_url, result)
    setting = await session.get(PlatformSetting, PORTAL_CONFIGURATION_SETTING)
    if setting is None:
        session.add(
            PlatformSetting(
                key=PORTAL_CONFIGURATION_SETTING, value={"id": result.portal_configuration_id}
            )
        )
    else:
        setting.value = {"id": result.portal_configuration_id}

    if webhook_url:
        _sync_webhook(client, webhook_url, rotate_webhook_secret, result)
    await session.flush()
    return result
