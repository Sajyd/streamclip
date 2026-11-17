"""Back-office: role checks, user listing, suspension."""

import argparse
import uuid

import httpx
from sqlalchemy import select, text

from app.cli import _promote_admin
from app.context import AppContext
from app.models.system import AuditLog
from tests.helpers import API, PASSWORD, Account, FakeStripeGateway, error_code, register
from tests.test_billing import _subscribe


async def _set_role(ctx: AppContext, account: Account, role: str) -> None:
    async with ctx.db.system_tx() as session:
        await session.execute(
            text("UPDATE users SET platform_role = :role WHERE id = :id"),
            {"role": role, "id": account.user_id},
        )


async def test_back_office_is_closed_to_regular_users(client: httpx.AsyncClient) -> None:
    account, target = await register(client), await register(client)
    calls = [
        ("GET", f"{API}/admin/users", None),
        ("POST", f"{API}/admin/users/{target.user_id}/suspend", {"reason": "because"}),
        ("POST", f"{API}/admin/users/{target.user_id}/reactivate", None),
    ]
    for method, url, body in calls:
        anonymous = await client.request(method, url, json=body)
        assert anonymous.status_code == 401
        response = await client.request(method, url, json=body, headers=account.headers)
        assert response.status_code == 403 and error_code(response) == "admin_required"
    assert (await client.get(f"{API}/me", headers=target.headers)).status_code == 200


async def test_role_is_read_from_the_database_on_every_request(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    await _set_role(ctx, account, "admin")
    # Same access token as before the promotion: no stale role is cached in it.
    assert (await client.get(f"{API}/admin/users", headers=account.headers)).status_code == 200
    await _set_role(ctx, account, "user")
    assert (await client.get(f"{API}/admin/users", headers=account.headers)).status_code == 403


async def test_support_can_read_but_not_change(client: httpx.AsyncClient, ctx: AppContext) -> None:
    support, target = await register(client), await register(client)
    await _set_role(ctx, support, "support")
    assert (await client.get(f"{API}/admin/users", headers=support.headers)).status_code == 200
    response = await client.post(
        f"{API}/admin/users/{target.user_id}/suspend",
        headers=support.headers,
        json={"reason": "not allowed"},
    )
    assert response.status_code == 403 and error_code(response) == "admin_required"


async def test_admin_lists_users_with_plan_search_and_pagination(
    client: httpx.AsyncClient, ctx: AppContext, fake_stripe: FakeStripeGateway
) -> None:
    admin = await register(client, email="root@example.com")
    await _set_role(ctx, admin, "admin")
    accounts = [await register(client, email=f"creator{i}@example.com") for i in range(4)]
    await _subscribe(client, fake_stripe, accounts[0], plan="pro")

    listing = (await client.get(f"{API}/admin/users", headers=admin.headers)).json()
    assert [item["email"] for item in listing["items"]] == [
        "creator3@example.com",
        "creator2@example.com",
        "creator1@example.com",
        "creator0@example.com",
        "root@example.com",
    ]  # newest first
    assert listing["next_cursor"] is None
    plans = {item["email"]: item["plan_code"] for item in listing["items"]}
    assert plans["creator0@example.com"] == "pro" and plans["creator1@example.com"] == "free"
    assert "password_hash" not in str(listing)

    page1 = (await client.get(f"{API}/admin/users?limit=2", headers=admin.headers)).json()
    page2 = (
        await client.get(
            f"{API}/admin/users?limit=2&cursor={page1['next_cursor']}", headers=admin.headers
        )
    ).json()
    assert [item["email"] for item in page1["items"] + page2["items"]] == [
        "creator3@example.com",
        "creator2@example.com",
        "creator1@example.com",
        "creator0@example.com",
    ]
    found = (await client.get(f"{API}/admin/users?search=ROOT", headers=admin.headers)).json()
    assert [item["email"] for item in found["items"]] == ["root@example.com"]
    # LIKE wildcards in the search are literal characters, not patterns.
    wildcard = (await client.get(f"{API}/admin/users?search=%25", headers=admin.headers)).json()
    assert wildcard["items"] == []
    assert (
        await client.get(f"{API}/admin/users?limit=500", headers=admin.headers)
    ).status_code == 422


async def test_suspension_takes_effect_immediately_and_is_reversible(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    admin, target = await register(client), await register(client)
    await _set_role(ctx, admin, "admin")

    response = await client.post(
        f"{API}/admin/users/{target.user_id}/suspend",
        headers=admin.headers,
        json={"reason": "Fraude au paiement"},
    )
    assert response.status_code == 204
    assert (await client.get(f"{API}/me", headers=target.headers)).status_code == 401
    refresh = await client.post(f"{API}/auth/refresh", json={"refresh_token": target.refresh_token})
    assert refresh.status_code == 401
    login = await client.post(
        f"{API}/auth/login", json={"email": target.email, "password": PASSWORD}
    )
    assert login.status_code == 403 and error_code(login) == "account_suspended"
    again = await client.post(
        f"{API}/admin/users/{target.user_id}/suspend",
        headers=admin.headers,
        json={"reason": "twice"},
    )
    assert again.status_code == 409 and error_code(again) == "user_not_active"

    response = await client.post(
        f"{API}/admin/users/{target.user_id}/reactivate", headers=admin.headers
    )
    assert response.status_code == 204
    login = await client.post(
        f"{API}/auth/login", json={"email": target.email, "password": PASSWORD}
    )
    assert login.status_code == 200

    async with ctx.db.system_tx() as session:
        entries = (
            await session.execute(
                select(
                    AuditLog.action,
                    AuditLog.actor_type,
                    AuditLog.actor_user_id,
                    AuditLog.target_id,
                    AuditLog.details,
                )
                .where(AuditLog.action.like("admin.%"))
                .order_by(AuditLog.occurred_at)
            )
        ).all()
    assert [(e.action, e.actor_type.value, e.actor_user_id, e.target_id) for e in entries] == [
        ("admin.user_suspended", "admin", admin.user_id, str(target.user_id)),
        ("admin.user_reactivated", "admin", admin.user_id, str(target.user_id)),
    ]
    assert entries[0].details == {"reason": "Fraude au paiement"}


async def test_suspension_guards(client: httpx.AsyncClient, ctx: AppContext) -> None:
    admin, other_admin = await register(client), await register(client)
    await _set_role(ctx, admin, "admin")
    await _set_role(ctx, other_admin, "admin")
    cases = [
        (admin.user_id, 409, "cannot_suspend_self"),
        (other_admin.user_id, 409, "cannot_suspend_admin"),
        (uuid.uuid4(), 404, "user_not_found"),
    ]
    for user_id, status, code in cases:
        response = await client.post(
            f"{API}/admin/users/{user_id}/suspend", headers=admin.headers, json={"reason": "test"}
        )
        assert (response.status_code, error_code(response)) == (status, code)
    missing_reason = await client.post(
        f"{API}/admin/users/{other_admin.user_id}/suspend", headers=admin.headers, json={}
    )
    assert missing_reason.status_code == 422
    not_suspended = await client.post(
        f"{API}/admin/users/{other_admin.user_id}/reactivate", headers=admin.headers
    )
    assert not_suspended.status_code == 409 and error_code(not_suspended) == "user_not_suspended"


async def test_first_admin_is_granted_from_the_command_line(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    assert (await client.get(f"{API}/admin/users", headers=account.headers)).status_code == 403
    assert await _promote_admin(ctx, argparse.Namespace(email="nobody@example.com")) == 1
    assert await _promote_admin(ctx, argparse.Namespace(email=account.email.upper())) == 0
    assert (await client.get(f"{API}/admin/users", headers=account.headers)).status_code == 200
    async with ctx.db.system_tx() as session:
        entry = (
            await session.execute(select(AuditLog).where(AuditLog.action == "admin.role_granted"))
        ).scalar_one()
    assert entry.actor_type.value == "system" and entry.target_id == str(account.user_id)


async def test_admin_analytics_and_directory_endpoints(
    client: httpx.AsyncClient, ctx: AppContext, fake_stripe: FakeStripeGateway
) -> None:
    admin = await register(client, email="ops@example.com")
    await _set_role(ctx, admin, "admin")
    creator = await register(client, email="streamer@example.com")
    await _subscribe(client, fake_stripe, creator, plan="pro")

    for period in ("day", "week", "month", "year"):
        analytics = await client.get(
            f"{API}/admin/analytics?period={period}", headers=admin.headers
        )
        assert analytics.status_code == 200
        body = analytics.json()
        assert body["period"] == period
        assert body["totals"]["users_total"] >= 2
        assert body["totals"]["mrr_cents"] >= 9900
        assert isinstance(body["series"], list) and len(body["series"]) >= 1

    subscriptions = (
        await client.get(f"{API}/admin/subscriptions", headers=admin.headers)
    ).json()
    assert subscriptions["summary"]["mrr_cents"] >= 9900
    assert subscriptions["summary"]["paying_subscribers"] >= 1
    assert any(item["plan_code"] == "pro" for item in subscriptions["items"])

    lives = await client.get(f"{API}/admin/lives", headers=admin.headers)
    clips = await client.get(f"{API}/admin/clips", headers=admin.headers)
    exports = await client.get(f"{API}/admin/exports", headers=admin.headers)
    assert lives.status_code == 200 and "items" in lives.json()
    assert clips.status_code == 200 and "items" in clips.json()
    assert exports.status_code == 200 and "items" in exports.json()

    forbidden = await client.get(f"{API}/admin/analytics", headers=creator.headers)
    assert forbidden.status_code == 403 and error_code(forbidden) == "admin_required"
