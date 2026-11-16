"""In-memory fakes for external services, and small test helpers."""

import hashlib
import hmac
import itertools
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import stripe

from app.billing.gateway import StripeGateway
from app.core.config import Settings
from app.email.mailer import OutgoingEmail

API = "/api/v1"
PASSWORD = "a-long-test-passphrase"
_counter = itertools.count(1)


# --- E-mail --------------------------------------------------------------------


class CapturingMailer:
    def __init__(self) -> None:
        self.enabled = True
        self.outbox: list[OutgoingEmail] = []
        self.failures_to_inject = 0

    def reset(self) -> None:
        self.enabled = True
        self.outbox.clear()
        self.failures_to_inject = 0

    async def send(self, message: OutgoingEmail) -> None:
        if self.failures_to_inject > 0:
            self.failures_to_inject -= 1
            raise ConnectionError("simulated SMTP outage")
        self.outbox.append(message)

    def last_token(self, to: str) -> str:
        """Extract the single-use token from the latest e-mail sent to `to`."""
        for message in reversed(self.outbox):
            if message.to == to:
                match = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", message.text)
                if match:
                    return match.group(1)
        raise AssertionError(f"No e-mail with a token was sent to {to}")


# --- Object storage ------------------------------------------------------------


class FakeStorage:
    bucket = "test-bucket"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.short_retention: set[str] = set()

    def reset(self) -> None:
        self.objects.clear()
        self.short_retention.clear()

    async def check(self) -> None:
        return None

    async def put_object(
        self, key: str, body: bytes, *, content_type: str, short_retention: bool = False
    ) -> None:
        self.objects[key] = body
        if short_retention:
            self.short_retention.add(key)

    async def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)
        self.short_retention.discard(key)

    async def object_exists(self, key: str) -> bool:
        return key in self.objects

    async def delete_tenant_objects(self, organization_id: uuid.UUID) -> int:
        prefix = f"tenants/{organization_id}/"
        keys = [key for key in self.objects if key.startswith(prefix)]
        for key in keys:
            del self.objects[key]
        return len(keys)

    async def presigned_download_url(
        self, key: str, *, expires_seconds: int = 300, filename: str | None = None
    ) -> str:
        return f"https://storage.test/{key}?expires={expires_seconds}"


# --- Stripe --------------------------------------------------------------------


class FakeStripeGateway(StripeGateway):
    """Real signature verification, in-memory API objects."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.charges: dict[str, str] = {}
        self.checkout_sessions: list[dict[str, Any]] = []
        self.portal_sessions: list[dict[str, Any]] = []
        self.canceled: list[str] = []
        self.retrieve_failures_to_inject = 0

    def reset(self) -> None:
        self.subscriptions.clear()
        self.charges.clear()
        self.checkout_sessions.clear()
        self.portal_sessions.clear()
        self.canceled.clear()
        self.retrieve_failures_to_inject = 0

    async def create_customer(self, *, organization_id: uuid.UUID, email: str, name: str) -> str:
        # Deterministic per organization, like the real idempotency key.
        return f"cus_{organization_id.hex[:20]}"

    async def create_checkout_session(self, **kwargs: Any) -> str:
        self.checkout_sessions.append(kwargs)
        return f"https://checkout.stripe.test/c/pay/{len(self.checkout_sessions)}"

    async def create_portal_session(self, **kwargs: Any) -> str:
        self.portal_sessions.append(kwargs)
        return f"https://billing.stripe.test/p/session/{len(self.portal_sessions)}"

    async def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        if self.retrieve_failures_to_inject > 0:
            self.retrieve_failures_to_inject -= 1
            raise stripe.APIConnectionError("simulated Stripe outage")
        return self.subscriptions[subscription_id]

    async def charge_customer_id(self, charge_id: str) -> str | None:
        return self.charges.get(charge_id)

    async def cancel_subscription(self, subscription_id: str) -> None:
        self.canceled.append(subscription_id)

    def put_subscription(
        self,
        subscription_id: str,
        *,
        customer: str,
        plan_code: str,
        status: str = "active",
        period_start: datetime,
        period_end: datetime,
        cancel_at_period_end: bool = False,
        canceled_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Set what the (fake) Stripe API currently returns for a subscription."""
        subscription = {
            "id": subscription_id,
            "object": "subscription",
            "customer": customer,
            "status": status,
            "cancel_at_period_end": cancel_at_period_end,
            "cancel_at": None,
            "canceled_at": int(canceled_at.timestamp()) if canceled_at else None,
            "items": {
                "object": "list",
                "data": [
                    {
                        "id": f"si_{subscription_id}",
                        "current_period_start": int(period_start.timestamp()),
                        "current_period_end": int(period_end.timestamp()),
                        "price": {
                            "id": f"price_{plan_code}",
                            "product": f"prod_{plan_code}",
                        },
                    }
                ],
            },
        }
        self.subscriptions[subscription_id] = subscription
        return subscription


def signed_event(
    secret: str,
    event_type: str,
    obj: dict[str, Any],
    *,
    event_id: str | None = None,
    livemode: bool = False,
    timestamp: int | None = None,
) -> tuple[bytes, str]:
    """Build a webhook body and its `Stripe-Signature` header, as Stripe does."""
    payload = json.dumps(
        {
            "id": event_id or f"evt_{uuid.uuid4().hex}",
            "object": "event",
            "api_version": stripe.api_version,
            "created": int(time.time()),
            "livemode": livemode,
            "type": event_type,
            "data": {"object": obj},
        }
    ).encode()
    signed_at = timestamp or int(time.time())
    signature = hmac.new(
        secret.encode(), f"{signed_at}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return payload, f"t={signed_at},v1={signature}"


# --- Accounts ------------------------------------------------------------------


@dataclass
class Account:
    email: str
    password: str
    user_id: uuid.UUID
    session_id: uuid.UUID
    access_token: str
    refresh_token: str
    organization_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_counter)}-{uuid.uuid4().hex[:6]}@example.com"


async def register(
    client: httpx.AsyncClient, *, email: str | None = None, password: str = PASSWORD
) -> Account:
    email = email or unique_email()
    response = await client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, "display_name": "Test", "accept_terms": True},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    account = Account(
        email=body["user"]["email"],
        password=password,
        user_id=uuid.UUID(body["user"]["id"]),
        session_id=uuid.UUID(body["tokens"]["session_id"]),
        access_token=body["tokens"]["access_token"],
        refresh_token=body["tokens"]["refresh_token"],
    )
    me = await client.get(f"{API}/me", headers=account.headers)
    assert me.status_code == 200, me.text
    account.organization_id = uuid.UUID(me.json()["organization"]["id"])
    return account


def error_code(response: httpx.Response) -> str:
    return str(response.json()["error"]["code"])


def utcnow() -> datetime:
    return datetime.now(UTC)
