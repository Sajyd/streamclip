"""Opt-in tests against the real external services.

They are skipped unless RUN_LIVE_TESTS=1 and the matching credentials are
present, because they need network access and real accounts:

    RUN_LIVE_TESTS=1 S3_BUCKET=... S3_REGION=... \\
    S3_ACCESS_KEY_ID=... S3_SECRET_ACCESS_KEY=... STRIPE_SECRET_KEY=sk_test_... \\
    pytest tests/test_live_integrations.py

Object storage is exercised with whatever identity is supplied; the
least-privilege assertions only make sense with the restricted runtime
identity (scripts/aws-runtime-key.sh). Stripe tests refuse live-mode keys.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import boto3
import httpx
import pytest
from botocore.exceptions import ClientError
from pydantic import SecretStr

from app.billing.gateway import StripeGateway
from app.core.config import Settings
from app.storage.s3 import SHORT_RETENTION_TAG, ObjectStorage, tenant_key, tenant_prefix
from tests.conftest import LIVE_ENV

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1", reason="live tests are opt-in (RUN_LIVE_TESTS=1)"
)


def _error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code"))


# --- Amazon S3 ------------------------------------------------------------------


@pytest.fixture
def live_storage(settings: Settings) -> ObjectStorage:
    required = ("S3_BUCKET", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    missing = [name for name in required if not LIVE_ENV.get(name)]
    if missing:
        pytest.skip(f"missing {', '.join(missing)}")
    return ObjectStorage(
        settings.model_copy(
            update={
                "s3_bucket": LIVE_ENV["S3_BUCKET"],
                "s3_region": LIVE_ENV["S3_REGION"],
                "s3_access_key_id": SecretStr(LIVE_ENV["S3_ACCESS_KEY_ID"] or ""),
                "s3_secret_access_key": SecretStr(LIVE_ENV["S3_SECRET_ACCESS_KEY"] or ""),
            }
        )
    )


def _operator_client() -> Any:
    """S3 client with the operator's own credentials, if they differ from the runtime's."""
    access_key, secret_key = (
        LIVE_ENV.get("AWS_ACCESS_KEY_ID"),
        LIVE_ENV.get("AWS_SECRET_ACCESS_KEY"),
    )
    if not access_key or not secret_key or access_key == LIVE_ENV.get("S3_ACCESS_KEY_ID"):
        return None
    return boto3.client(
        "s3",
        region_name=LIVE_ENV["S3_REGION"],
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


@pytest.fixture
async def tenant(live_storage: ObjectStorage) -> AsyncIterator[uuid.UUID]:
    organization_id = uuid.uuid4()
    yield organization_id
    await live_storage.delete_tenant_objects(organization_id)


async def test_s3_object_lifecycle_through_the_application_client(
    live_storage: ObjectStorage, tenant: uuid.UUID
) -> None:
    await live_storage.check()
    key = tenant_key(tenant, "exports", "live-test.json")
    body = b'{"hello": "streamclip"}'
    assert await live_storage.object_exists(key) is False

    await live_storage.put_object(
        key, body, content_type="application/json; charset=utf-8", short_retention=True
    )
    assert await live_storage.object_exists(key) is True
    head = live_storage._client.head_object(Bucket=live_storage.bucket, Key=key)
    assert head["ServerSideEncryption"] == "AES256"
    assert head["ContentType"] == "application/json; charset=utf-8"
    # The runtime identity may set the expiry tag but not read tags back: it is
    # checked with the operator's credentials when they are available.
    operator = _operator_client()
    if operator is not None:
        tags = operator.get_object_tagging(Bucket=live_storage.bucket, Key=key)
        assert [f"{tag['Key']}={tag['Value']}" for tag in tags["TagSet"]] == [SHORT_RETENTION_TAG]

    # The pre-signed URL works without credentials, forces a download, and
    # nothing is readable without it.
    url = await live_storage.presigned_download_url(key, expires_seconds=60, filename="export.json")
    async with httpx.AsyncClient(timeout=20) as http:
        signed = await http.get(url)
        assert signed.status_code == 200 and signed.content == body
        assert signed.headers["content-disposition"] == 'attachment; filename="export.json"'
        anonymous = await http.get(url.split("?", 1)[0])
        assert anonymous.status_code == 403
        tampered = await http.get(url.replace("live-test.json", "other.json"))
        assert tampered.status_code == 403
        # Plain HTTP is refused by the bucket policy, even with a valid signature.
        insecure = await http.get(url.replace("https://", "http://", 1))
        assert insecure.status_code == 403

    await live_storage.delete_object(key)
    assert await live_storage.object_exists(key) is False
    await live_storage.delete_object(key)  # idempotent


async def test_s3_erasure_removes_exactly_one_tenant(
    live_storage: ObjectStorage, tenant: uuid.UUID
) -> None:
    other = uuid.uuid4()
    try:
        for index in range(3):
            await live_storage.put_object(
                tenant_key(tenant, "clips", f"{index}.bin"), b"x", content_type="video/mp4"
            )
        kept = tenant_key(other, "clips", "kept.bin")
        await live_storage.put_object(kept, b"y", content_type="video/mp4")

        assert await live_storage.delete_tenant_objects(tenant) == 3
        assert await live_storage.delete_tenant_objects(tenant) == 0
        assert await live_storage.object_exists(kept) is True
    finally:
        await live_storage.delete_tenant_objects(other)


async def test_s3_runtime_identity_is_confined_to_application_prefixes(
    live_storage: ObjectStorage,
) -> None:
    client = live_storage._client
    bucket = live_storage.bucket
    denied = {
        "write outside the prefixes": lambda: client.put_object(
            Bucket=bucket, Key="outside.txt", Body=b"x"
        ),
        "read outside the prefixes": lambda: client.get_object(Bucket=bucket, Key="outside.txt"),
        "list the whole bucket": lambda: client.list_objects_v2(Bucket=bucket, MaxKeys=1),
        "list another prefix": lambda: client.list_objects_v2(
            Bucket=bucket, Prefix="terraform/", MaxKeys=1
        ),
        "read the bucket policy": lambda: client.get_bucket_policy(Bucket=bucket),
        "change the lifecycle": lambda: client.delete_bucket_lifecycle(Bucket=bucket),
        "open the bucket": lambda: client.delete_public_access_block(Bucket=bucket),
        "list all buckets": lambda: client.list_buckets(),
    }
    for action, call in denied.items():
        with pytest.raises(ClientError) as caught:
            call()
        assert _error_code(caught.value) in ("AccessDenied", "403"), action


async def test_s3_tenant_prefix_helper_matches_what_is_stored(
    live_storage: ObjectStorage, tenant: uuid.UUID
) -> None:
    key = tenant_key(tenant, "exports", "a.json")
    assert key.startswith(tenant_prefix(tenant))
    await live_storage.put_object(key, b"{}", content_type="application/json")
    listing = live_storage._client.list_objects_v2(
        Bucket=live_storage.bucket, Prefix=tenant_prefix(tenant)
    )
    assert [item["Key"] for item in listing["Contents"]] == [key]


# --- Stripe (test mode only) ------------------------------------------------------


@pytest.fixture
def live_stripe(settings: Settings) -> StripeGateway:
    secret = LIVE_ENV.get("STRIPE_SECRET_KEY")
    if not secret:
        pytest.skip("missing STRIPE_SECRET_KEY")
    if not secret.startswith(("sk_test_", "rk_test_")):
        pytest.fail("Live tests must never run with a live-mode Stripe key")
    return StripeGateway(settings.model_copy(update={"stripe_secret_key": SecretStr(secret)}))


async def test_stripe_subscription_round_trip(live_stripe: StripeGateway) -> None:
    """Customer, Checkout, real subscription on the catalogue price, portal, cancel."""
    client = live_stripe.client
    prices = client.v1.prices.list({"lookup_keys": ["streamclip_starter_monthly"], "active": True})
    if not prices.data:
        pytest.skip("catalogue not synchronised (python -m app.cli stripe-sync)")
    price = prices.data[0]
    assert price.unit_amount == 1900 and price.currency == "eur"
    assert price.recurring is not None and price.recurring.interval == "month"
    assert price.tax_behavior == "inclusive"
    assert price.product == "streamclip_plan_starter"

    organization_id = uuid.uuid4()
    identity = {
        "organization_id": organization_id,
        "email": f"live-test-{organization_id.hex[:8]}@example.com",
        "name": "Live test",
    }
    customer_id = await live_stripe.create_customer(**identity)
    try:
        # Same call again: the idempotency key returns the same customer.
        assert await live_stripe.create_customer(**identity) == customer_id

        checkout_url = await live_stripe.create_checkout_session(
            customer_id=customer_id,
            price_id=price.id,
            organization_id=organization_id,
            plan_code="starter",
            success_url="https://example.com/billing?checkout=success",
            cancel_url="https://example.com/billing?checkout=cancelled",
        )
        assert checkout_url.startswith("https://checkout.stripe.com/")

        method = client.v1.payment_methods.attach("pm_card_visa", {"customer": customer_id})
        created = client.v1.subscriptions.create(
            {
                "customer": customer_id,
                "items": [{"price": price.id}],
                "default_payment_method": method.id,
                "metadata": {"organization_id": str(organization_id)},
            }
        )
        subscription = await live_stripe.retrieve_subscription(created.id)
        # Exactly the fields the billing state machine relies on.
        assert subscription["status"] == "active"
        assert subscription["customer"] == customer_id
        assert subscription["cancel_at_period_end"] is False
        item = subscription["items"]["data"][0]
        assert item["price"]["id"] == price.id
        assert item["price"]["product"] == "streamclip_plan_starter"
        start = datetime.fromtimestamp(item["current_period_start"], UTC)
        end = datetime.fromtimestamp(item["current_period_end"], UTC)
        assert 27 <= (end - start).days <= 31

        invoice = client.v1.invoices.retrieve(created.latest_invoice)  # type: ignore[arg-type]
        assert invoice.status == "paid" and invoice.amount_paid == 1900
        assert invoice.parent is not None
        assert invoice.parent.subscription_details is not None
        assert invoice.parent.subscription_details.subscription == created.id

        portal_url = await live_stripe.create_portal_session(
            customer_id=customer_id,
            return_url="https://example.com/billing",
            configuration_id=None,
        )
        assert portal_url.startswith("https://billing.stripe.com/")

        await live_stripe.cancel_subscription(created.id)
        assert (await live_stripe.retrieve_subscription(created.id))["status"] == "canceled"
        await live_stripe.cancel_subscription(created.id)  # idempotent
    finally:
        client.v1.customers.delete(customer_id)
