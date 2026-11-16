"""Thin wrapper around the Stripe API.

The SDK's synchronous client is used from worker threads: its default HTTP
transport is thread-safe and independent of the event loop, which matters in
serverless runtimes. Card data never touches this application: payments
happen on Stripe-hosted Checkout and Customer Portal pages.
"""

import asyncio
import secrets
import string
import uuid
from typing import Any

import stripe

from app.core.config import Settings

SUBSCRIPTION_EXPAND = ["items.data.price"]


class StripeGateway:
    def __init__(self, settings: Settings) -> None:
        if settings.stripe_secret_key is None:
            raise ValueError("Stripe is not configured")
        # The API version is pinned by the SDK release (see uv.lock): upgrading
        # the API is an explicit dependency bump, never a silent change.
        self.client = stripe.StripeClient(
            settings.stripe_secret_key.get_secret_value(), max_network_retries=2
        )
        self._webhook_secret = (
            settings.stripe_webhook_secret.get_secret_value()
            if settings.stripe_webhook_secret
            else None
        )
        self.livemode = bool(settings.stripe_livemode)

    # --- Webhooks ---------------------------------------------------------
    def construct_event(self, payload: bytes, signature: str | None) -> stripe.Event:
        """Verify the signature (HMAC + timestamp tolerance) and parse the event."""
        if self._webhook_secret is None:
            raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")
        return self.client.construct_event(payload, signature, self._webhook_secret)

    # --- Customers --------------------------------------------------------
    async def create_customer(self, *, organization_id: uuid.UUID, email: str, name: str) -> str:
        customer = await asyncio.to_thread(
            self.client.v1.customers.create,
            {
                "email": email,
                "name": name,
                "preferred_locales": ["fr"],
                "metadata": {"organization_id": str(organization_id)},
            },
            # A retried request (timeout, double click) returns the same customer.
            {"idempotency_key": f"streamclip-customer-{organization_id}"},
        )
        return customer.id

    # --- Checkout and portal ----------------------------------------------
    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        organization_id: uuid.UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
        metadata = {"organization_id": str(organization_id), "plan_code": plan_code}
        session = await asyncio.to_thread(
            self.client.v1.checkout.sessions.create,
            {
                "mode": "subscription",
                "customer": customer_id,
                "client_reference_id": str(organization_id),
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "locale": "fr",
                "billing_address_collection": "required",
                "customer_update": {"address": "auto", "name": "auto"},
                "tax_id_collection": {"enabled": True},
                "metadata": metadata,
                "subscription_data": {"metadata": metadata},
                "integration_identifier": f"streamclip_subscribe_{suffix}",
            },
        )
        if not session.url:
            raise RuntimeError("Stripe returned a Checkout Session without URL")
        return session.url

    async def create_portal_session(
        self, *, customer_id: str, return_url: str, configuration_id: str | None
    ) -> str:
        params: Any = {"customer": customer_id, "return_url": return_url, "locale": "fr"}
        if configuration_id:
            params["configuration"] = configuration_id
        session = await asyncio.to_thread(self.client.v1.billing_portal.sessions.create, params)
        return session.url

    # --- Subscriptions ----------------------------------------------------
    async def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        subscription = await asyncio.to_thread(
            self.client.v1.subscriptions.retrieve,
            subscription_id,
            {"expand": SUBSCRIPTION_EXPAND},
        )
        return subscription.to_dict()

    async def charge_customer_id(self, charge_id: str) -> str | None:
        """Customer behind a charge (used to attribute disputes and fraud warnings)."""
        charge = await asyncio.to_thread(self.client.v1.charges.retrieve, charge_id)
        customer = charge.customer
        return customer if isinstance(customer, str) or customer is None else customer.id

    async def cancel_subscription(self, subscription_id: str) -> None:
        try:
            await asyncio.to_thread(self.client.v1.subscriptions.cancel, subscription_id)
        except stripe.InvalidRequestError as exc:
            if exc.code != "resource_missing":
                raise
