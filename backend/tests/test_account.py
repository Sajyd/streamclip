"""Profile, organization, personal-data export and account erasure (GDPR)."""

import json
import uuid
from typing import Any

import httpx
from sqlalchemy import select, text

from app.context import AppContext
from app.models.system import AuditLog
from tests.helpers import (
    API,
    PASSWORD,
    Account,
    FakeStorage,
    FakeStripeGateway,
    error_code,
    register,
)
from tests.test_billing import _subscribe


def _walk_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {key for value in node.values() for key in _walk_keys(value)}
    if isinstance(node, list):
        return {key for item in node for key in _walk_keys(item)}
    return set()


async def _export(
    client: httpx.AsyncClient, storage: FakeStorage, account: Account
) -> dict[str, Any]:
    response = await client.post(f"{API}/account/exports", headers=account.headers)
    assert response.status_code == 202, response.text
    key = f"tenants/{account.organization_id}/exports/{response.json()['items'][0]['id']}.json"
    return dict(json.loads(storage.objects[key]))


# --- Profile and organization --------------------------------------------------


async def test_profile_update_validates_and_audits(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    response = await client.patch(
        f"{API}/me",
        headers=account.headers,
        json={"display_name": "  Léa  ", "locale": "en", "timezone": "America/Montreal"},
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["display_name"], body["locale"], body["timezone"]) == (
        "Léa",
        "en",
        "America/Montreal",
    )
    # Partial update: untouched fields keep their value.
    response = await client.patch(f"{API}/me", headers=account.headers, json={"locale": "fr"})
    assert response.json()["display_name"] == "Léa" and response.json()["locale"] == "fr"

    for invalid in (
        {"timezone": "Mars/Olympus"},
        {"locale": "xx"},
        {"email": "other@example.com"},  # not editable here
        {"platform_role": "admin"},  # privilege escalation attempt
        {"email_verified": True},
    ):
        response = await client.patch(f"{API}/me", headers=account.headers, json=invalid)
        assert response.status_code == 422, invalid
    me = (await client.get(f"{API}/me", headers=account.headers)).json()
    assert me["user"]["platform_role"] == "user" and me["user"]["email"] == account.email

    async with ctx.db.system_tx() as session:
        details = (
            (
                await session.execute(
                    select(AuditLog.details).where(AuditLog.action == "account.profile_updated")
                )
            )
            .scalars()
            .all()
        )
    assert details[0] == {"fields": ["display_name", "locale", "timezone"]}


async def test_organization_rename(client: httpx.AsyncClient, ctx: AppContext) -> None:
    account = await register(client)
    response = await client.patch(
        f"{API}/organization", headers=account.headers, json={"name": "Studio Léa"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": str(account.organization_id),
        "name": "Studio Léa",
        "role": "owner",
    }
    me = (await client.get(f"{API}/me", headers=account.headers)).json()
    assert me["organization"]["name"] == "Studio Léa"
    empty = await client.patch(f"{API}/organization", headers=account.headers, json={"name": ""})
    assert empty.status_code == 422

    # A plain member cannot rename the organization.
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE memberships SET role = 'member'"))
    denied = await client.patch(
        f"{API}/organization", headers=account.headers, json={"name": "Nope"}
    )
    assert denied.status_code == 403 and error_code(denied) == "insufficient_role"


# --- Data export ---------------------------------------------------------------


async def test_export_contains_the_callers_data_without_secrets_or_other_tenants(
    client: httpx.AsyncClient, ctx: AppContext, storage: FakeStorage
) -> None:
    alice, bob = await register(client), await register(client)
    await client.patch(f"{API}/organization", headers=bob.headers, json={"name": "Bob Corp"})

    document = await _export(client, storage, alice)
    data = document["data"]
    assert document["user_id"] == str(alice.user_id)
    assert [row["email"] for row in data["users"]] == [alice.email]
    assert [row["id"] for row in data["organizations"]] == [str(alice.organization_id)]
    for table in ("memberships", "subscriptions", "usage_periods", "auth_sessions", "audit_logs"):
        assert data[table], table
    assert data["auth_sessions"][0]["ip"] == "203.0.113.10"

    # No credential material, in any table.
    forbidden = {
        "password_hash",
        "token_hash",
        "key_hash",
        "access_token_encrypted",
        "refresh_token_encrypted",
    }
    assert _walk_keys(document).isdisjoint(forbidden)
    serialized = json.dumps(document)
    assert "argon2" not in serialized and alice.refresh_token not in serialized
    # Nothing belonging to the other tenant.
    for needle in (bob.email, str(bob.user_id), str(bob.organization_id), "Bob Corp"):
        assert needle not in serialized

    # Stored privately under the tenant's own prefix; listed and downloadable.
    assert all(
        key.startswith(f"tenants/{alice.organization_id}/exports/") for key in storage.objects
    )
    # Flagged for the bucket's expiry rule: removed even if the cleanup never runs.
    assert storage.short_retention == set(storage.objects)
    listing = (await client.get(f"{API}/account/exports", headers=alice.headers)).json()["items"]
    assert len(listing) == 1 and listing[0]["status"] == "available"
    assert listing[0]["size_bytes"] > 100 and listing[0]["expires_at"] is not None
    url = await client.get(
        f"{API}/account/exports/{listing[0]['id']}/download-url", headers=alice.headers
    )
    assert url.status_code == 200 and "expires=300" in url.json()["url"]


async def test_export_is_rate_limited_and_requires_storage(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    statuses = [
        (await client.post(f"{API}/account/exports", headers=account.headers)).status_code
        for _ in range(6)
    ]
    assert statuses == [202] * 5 + [429]

    other = await register(client)
    saved, ctx.storage = ctx.storage, None
    try:
        response = await client.post(f"{API}/account/exports", headers=other.headers)
        meta = (await client.get(f"{API}/meta")).json()
    finally:
        ctx.storage = saved
    assert response.status_code == 503 and error_code(response) == "storage_unavailable"
    assert meta["capabilities"]["storage"] is False


async def test_expired_export_cannot_be_downloaded(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    created = await client.post(f"{API}/account/exports", headers=account.headers)
    export_id = created.json()["items"][0]["id"]
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE storage_assets SET expires_at = now() - interval '1 s'"))
    response = await client.get(
        f"{API}/account/exports/{export_id}/download-url", headers=account.headers
    )
    assert response.status_code == 409 and error_code(response) == "export_not_available"


# --- Erasure -------------------------------------------------------------------


async def test_account_deletion_requires_the_password(client: httpx.AsyncClient) -> None:
    account = await register(client)
    response = await client.post(
        f"{API}/account/delete", headers=account.headers, json={"password": "wrong-password"}
    )
    assert response.status_code == 403 and error_code(response) == "invalid_current_password"
    assert (await client.get(f"{API}/me", headers=account.headers)).status_code == 200


async def test_account_deletion_erases_everything_and_only_that_account(
    client: httpx.AsyncClient,
    ctx: AppContext,
    storage: FakeStorage,
    fake_stripe: FakeStripeGateway,
) -> None:
    alice, bob = await register(client), await register(client)
    subscription_id = await _subscribe(client, fake_stripe, alice, plan="creator")
    await _export(client, storage, alice)
    await _export(client, storage, bob)

    response = await client.post(
        f"{API}/account/delete", headers=alice.headers, json={"password": PASSWORD}
    )
    assert response.status_code == 202, response.text

    # Access stops immediately, on every path.
    assert (await client.get(f"{API}/me", headers=alice.headers)).status_code == 401
    refresh = await client.post(f"{API}/auth/refresh", json={"refresh_token": alice.refresh_token})
    assert refresh.status_code == 401
    login = await client.post(
        f"{API}/auth/login", json={"email": alice.email, "password": PASSWORD}
    )
    assert login.status_code == 401

    # The paid subscription was cancelled at Stripe and stored files are gone.
    assert fake_stripe.canceled == [subscription_id]
    assert not any(str(alice.organization_id) in key for key in storage.objects)
    assert any(str(bob.organization_id) in key for key in storage.objects)

    async with ctx.db.system_tx() as session:
        leftovers: dict[str, int] = {}
        for table in ctx_tables():
            for column in ("organization_id", "user_id"):
                exists = (
                    await session.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'"
                            " AND table_name = :t AND column_name = :c"
                        ),
                        {"t": table, "c": column},
                    )
                ).first()
                if exists and table != "audit_logs":
                    owner = alice.organization_id if column == "organization_id" else alice.user_id
                    count = (
                        await session.execute(
                            text(f"SELECT count(*) FROM {table} WHERE {column} = :owner"),
                            {"owner": owner},
                        )
                    ).scalar_one()
                    if count:
                        leftovers[f"{table}.{column}"] = count
        users = (await session.execute(text("SELECT email FROM users"))).scalars().all()
        organizations = (
            (await session.execute(text("SELECT id FROM organizations"))).scalars().all()
        )
        trail = (
            await session.execute(
                select(AuditLog.action, AuditLog.ip, AuditLog.user_agent).where(
                    (AuditLog.organization_id == alice.organization_id)
                    | (AuditLog.actor_user_id == alice.user_id)
                )
            )
        ).all()
        bob_trail_ips = (
            (
                await session.execute(
                    select(AuditLog.ip).where(AuditLog.actor_user_id == bob.user_id)
                )
            )
            .scalars()
            .all()
        )
    assert leftovers == {}
    assert users == [bob.email] and organizations == [bob.organization_id]
    # The audit trail survives, stripped of network identifiers.
    actions = {action for action, _, _ in trail}
    assert {"auth.register", "account.deletion_requested", "account.erased"} <= actions
    assert all(ip is None and agent is None for _, ip, agent in trail)
    assert all(ip is not None for ip in bob_trail_ips)

    # Bob is untouched, and the address can be registered again.
    assert (await client.get(f"{API}/me", headers=bob.headers)).status_code == 200
    again = await register(client, email=alice.email)
    assert again.user_id != alice.user_id


async def test_erasure_is_retried_until_stripe_cancellation_succeeds(
    client: httpx.AsyncClient, ctx: AppContext, fake_stripe: FakeStripeGateway
) -> None:
    account = await register(client)
    await _subscribe(client, fake_stripe, account)

    async def failing_cancel(subscription_id: str) -> None:
        raise ConnectionError("stripe unreachable")

    original = fake_stripe.cancel_subscription
    fake_stripe.cancel_subscription = failing_cancel  # type: ignore[method-assign]
    try:
        response = await client.post(
            f"{API}/account/delete", headers=account.headers, json={"password": PASSWORD}
        )
    finally:
        fake_stripe.cancel_subscription = original  # type: ignore[method-assign]
    # The account is closed at once even though the erasure could not finish...
    assert response.status_code == 202
    assert (await client.get(f"{API}/me", headers=account.headers)).status_code == 401
    login = await client.post(
        f"{API}/auth/login", json={"email": account.email, "password": PASSWORD}
    )
    assert login.status_code == 401 and error_code(login) == "invalid_credentials"
    async with ctx.db.system_tx() as session:
        status = (
            await session.execute(text("SELECT status FROM tasks WHERE kind = 'account.delete'"))
        ).scalar_one()
        assert status == "queued"  # ...nothing was deleted while billing is still active
        assert (await session.execute(text("SELECT count(*) FROM organizations"))).scalar_one() == 1
        await session.execute(text("UPDATE tasks SET run_at = now()"))

    from app.tasks.queue import run_due_tasks

    assert (await run_due_tasks(ctx, worker="retry"))["succeeded"] == 1
    async with ctx.db.system_tx() as session:
        assert (await session.execute(text("SELECT count(*) FROM organizations"))).scalar_one() == 0
        assert (await session.execute(text("SELECT count(*) FROM users"))).scalar_one() == 0


def ctx_tables() -> list[str]:
    from app.models import Base

    return sorted(Base.metadata.tables)


async def test_unknown_export_id_is_not_found(client: httpx.AsyncClient) -> None:
    account = await register(client)
    response = await client.get(
        f"{API}/account/exports/{uuid.uuid4()}/download-url", headers=account.headers
    )
    assert response.status_code == 404 and error_code(response) == "export_not_found"
