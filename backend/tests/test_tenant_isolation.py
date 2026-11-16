"""Tenant isolation: the database itself must keep organizations apart.

Two layers are verified:
* structure - the live schema (built by the migrations) matches what every
  model declares: row-level security, policies and the application role's
  privileges. A new table cannot ship without isolation.
* behaviour - with real rows of two tenants, statements *without any WHERE
  clause* only ever reach the caller's organization.
"""

import asyncio
import uuid
from typing import Any

import httpx
import psycopg.errors
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.context import AppContext
from app.core.config import Settings
from app.db.engine import Database, TenantContext
from app.models import APP_ROLE, Base
from app.services.notifications import notify
from tests.helpers import API, Account, error_code, register

PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def _tenant(account: Account) -> TenantContext:
    return TenantContext(organization_id=account.organization_id, user_id=account.user_id)


async def _as_tenant(
    ctx: AppContext, account: Account, sql: str, params: dict[str, Any] | None = None
) -> list[Any]:
    async with ctx.db.tenant_tx(_tenant(account)) as session:
        result = await session.execute(text(sql), params or {})
        return list(result.all()) if result.returns_rows else [result.rowcount]


async def _denied(ctx: AppContext, account: Account, sql: str, **params: Any) -> None:
    """Assert PostgreSQL refuses the statement for the tenant role (SQLSTATE 42501)."""
    with pytest.raises(DBAPIError) as caught:
        await _as_tenant(ctx, account, sql, params)
    assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege), caught.value


# --- Structure -----------------------------------------------------------------


async def test_application_role_is_unprivileged(ctx: AppContext) -> None:
    async with ctx.db.system_tx() as session:
        role = (
            await session.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolcanlogin,"
                    " rolinherit, rolreplication FROM pg_roles WHERE rolname = :role"
                ),
                {"role": APP_ROLE},
            )
        ).one()
        memberships = (
            await session.execute(
                text(
                    "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member"
                    " WHERE r.rolname = :role"
                ),
                {"role": APP_ROLE},
            )
        ).scalar_one()
    assert tuple(role) == (False, False, False, False, False, False, False)
    assert memberships == 0  # it belongs to no other role it could switch to


async def test_row_level_security_matches_model_declarations(ctx: AppContext) -> None:
    async with ctx.db.system_tx() as session:
        rls = {
            name: (enabled, forced)
            for name, enabled, forced in await session.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
                    " WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
                )
            )
        }
        policies: dict[str, list[Any]] = {}
        for row in await session.execute(
            text(
                "SELECT tablename, policyname, permissive, roles, cmd, qual, with_check"
                " FROM pg_policies WHERE schemaname = 'public'"
            )
        ):
            policies.setdefault(row.tablename, []).append(row)

    assert set(rls) - {"alembic_version"} == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        mode = table.info["rls"]
        enabled, _forced = rls[name]
        if mode is None:
            assert not enabled and name not in policies, name
            continue
        assert enabled, f"{name} declares rls={mode!r} but row-level security is off"
        assert len(policies[name]) == 1, name
        policy = policies[name][0]
        column = "organization_id" if mode == "tenant" else "id"
        setting = "NULLIF(current_setting('app.current_org_id'::text, true), ''::text)"
        expected = f"({column} = ({setting})::uuid)"
        assert policy.policyname == "tenant_isolation"
        assert policy.permissive == "PERMISSIVE" and policy.cmd == "ALL"
        assert list(policy.roles) == [APP_ROLE]
        # Same predicate for reading (USING) and writing (WITH CHECK).
        assert policy.qual == expected, (name, policy.qual)
        assert policy.with_check == expected, (name, policy.with_check)


async def test_every_table_holding_tenant_data_is_isolated_or_unreachable() -> None:
    """A table with an organization_id column must either be under row-level
    security or grant nothing at all to the tenant-scoped role."""
    for name, table in Base.metadata.tables.items():
        info = table.info
        if "organization_id" in table.c or name == "organizations":
            assert info["rls"] is not None or info["app"] == (), name
        if info["rls"] is None:
            assert set(info["app"]) <= {"SELECT"}, name


async def test_application_role_privileges_match_model_declarations(ctx: AppContext) -> None:
    async with ctx.db.system_tx() as session:
        for name, table in Base.metadata.tables.items():
            declared: tuple[str, ...] = table.info["app"]
            update_columns: tuple[str, ...] | None = table.info["app_update_columns"]
            for privilege in PRIVILEGES:
                granted = (
                    await session.execute(
                        text("SELECT has_table_privilege(:role, :table, :privilege)"),
                        {"role": APP_ROLE, "table": f"public.{name}", "privilege": privilege},
                    )
                ).scalar_one()
                whole_table = privilege in declared and not (
                    privilege == "UPDATE" and update_columns
                )
                assert granted is whole_table, (name, privilege, granted)
            updatable = {
                column
                for (column,) in await session.execute(
                    text(
                        "SELECT attname FROM pg_attribute"
                        " WHERE attrelid = CAST(:table AS regclass) AND attnum > 0"
                        " AND NOT attisdropped"
                        " AND has_column_privilege(:role, attrelid, attnum, 'UPDATE')"
                    ),
                    {"role": APP_ROLE, "table": f"public.{name}"},
                )
            }
            if "UPDATE" not in declared:
                assert updatable == set(), name
            elif update_columns:
                assert updatable == set(update_columns), name
            else:
                assert updatable == set(table.c.keys()), name
        other = (
            await session.execute(
                text("SELECT has_table_privilege(:role, 'public.alembic_version', 'SELECT')"),
                {"role": APP_ROLE},
            )
        ).scalar_one()
        public_grants = (
            await session.execute(
                text(
                    "SELECT count(*) FROM information_schema.table_privileges"
                    " WHERE table_schema = 'public' AND grantee = 'PUBLIC'"
                )
            )
        ).scalar_one()
    assert other is False
    assert public_grants == 0


# --- Behaviour -----------------------------------------------------------------


async def test_transactions_run_under_the_expected_role(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    alice = await register(client)
    async with ctx.db.system_tx() as session:
        system_user = (await session.execute(text("SELECT current_user"))).scalar_one()
    rows = await _as_tenant(
        ctx,
        alice,
        "SELECT current_user, session_user, current_setting('app.current_org_id'),"
        " current_setting('app.current_user_id')",
    )
    assert system_user != APP_ROLE
    assert tuple(rows[0]) == (APP_ROLE, system_user, str(alice.organization_id), str(alice.user_id))


async def test_unfiltered_queries_only_see_the_callers_organization(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    alice, bob = await register(client), await register(client)
    async with ctx.db.system_tx() as session:
        for account in (alice, bob):
            await notify(session, organization_id=account.organization_id, kind="t", title="hello")
            await session.execute(
                text(
                    "INSERT INTO storage_assets"
                    " (id, organization_id, kind, status, bucket, key, content_type)"
                    " VALUES (:id, :org, 'data_export', 'available', 'b', :key, 'application/json')"
                ),
                {"id": uuid.uuid4(), "org": account.organization_id, "key": f"k/{account.email}"},
            )

    # Deliberately no WHERE clause: isolation must not depend on the query.
    populated = (
        "memberships",
        "subscriptions",
        "usage_periods",
        "notifications",
        "organization_settings",
        "storage_assets",
    )
    for account in (alice, bob):
        organizations = await _as_tenant(ctx, account, "SELECT id FROM organizations")
        assert [row.id for row in organizations] == [account.organization_id]
        for table in populated:
            rows = await _as_tenant(ctx, account, f"SELECT organization_id FROM {table}")
            assert [row.organization_id for row in rows] == [account.organization_id], table

    # Sanity check: the data of both tenants really is there.
    async with ctx.db.system_tx() as session:
        for table in ("organizations", *populated):
            total = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert total == 2, table


async def test_cross_tenant_writes_are_impossible(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    alice, bob = await register(client), await register(client)
    async with ctx.db.system_tx() as session:
        await notify(session, organization_id=bob.organization_id, kind="t", title="for bob")

    # Unfiltered UPDATEs touch the caller's rows only.
    assert await _as_tenant(ctx, alice, "UPDATE organizations SET name = 'pwned'") == [1]
    assert await _as_tenant(ctx, alice, "UPDATE notifications SET read_at = now()") == [0]
    assert await _as_tenant(
        ctx, alice, "UPDATE organization_settings SET context_buffer_seconds = 120"
    ) == [1]
    async with ctx.db.system_tx() as session:
        names = {
            row.id: row.name
            for row in await session.execute(text("SELECT id, name FROM organizations"))
        }
        unread = (
            await session.execute(text("SELECT count(*) FROM notifications WHERE read_at IS NULL"))
        ).scalar_one()
        buffers = {
            row.organization_id: row.context_buffer_seconds
            for row in await session.execute(
                text("SELECT organization_id, context_buffer_seconds FROM organization_settings")
            )
        }
    assert names[alice.organization_id] == "pwned" and names[bob.organization_id] != "pwned"
    assert unread == 1
    assert buffers == {alice.organization_id: 120, bob.organization_id: 90}

    # A row cannot be moved into (or created in) another organization.
    await _denied(
        ctx,
        alice,
        "UPDATE organization_settings SET organization_id = :other",
        other=bob.organization_id,
    )
    # Columns and tables outside the role's grants are refused outright.
    await _denied(ctx, alice, "UPDATE organizations SET stripe_customer_id = 'cus_stolen'")
    await _denied(ctx, alice, "UPDATE organizations SET owner_user_id = :user", user=alice.user_id)
    await _denied(ctx, alice, "DELETE FROM organizations")
    await _denied(ctx, alice, "DELETE FROM notifications")
    await _denied(
        ctx,
        alice,
        "INSERT INTO notifications (id, organization_id, kind, severity, title)"
        " VALUES (gen_random_uuid(), :org, 'x', 'info', 'spoofed')",
        org=bob.organization_id,
    )
    await _denied(
        ctx,
        alice,
        "UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE code = 'business')",
    )
    await _denied(ctx, alice, "UPDATE usage_periods SET consumed_ms = 0")
    await _denied(ctx, alice, "UPDATE plans SET price_cents = 0")


@pytest.mark.parametrize(
    "table",
    [
        "users",
        "auth_sessions",
        "refresh_tokens",
        "auth_tokens",
        "user_settings",
        "tasks",
        "audit_logs",
        "billing_events",
        "cost_records",
        "platform_settings",
        "rate_limit_counters",
        "social_accounts",
        "alembic_version",
    ],
)
async def test_sensitive_tables_are_out_of_reach_of_the_tenant_role(
    ctx: AppContext, client: httpx.AsyncClient, table: str
) -> None:
    alice = await register(client)
    await _denied(ctx, alice, f"SELECT * FROM {table}")


async def test_missing_or_empty_tenant_setting_matches_nothing(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    """Fail closed: the role without an organization sees no row at all."""
    await register(client)
    for setup in (
        [],  # setting never defined
        ["SELECT set_config('app.current_org_id', '', true)"],  # defined but empty
    ):
        async with ctx.db.engine.connect() as connection:
            await connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
            for statement in setup:
                await connection.execute(text(statement))
            for table in ("organizations", "memberships", "subscriptions", "usage_periods"):
                count = (
                    await connection.execute(text(f"SELECT count(*) FROM {table}"))
                ).scalar_one()
                assert count == 0, (table, setup)
            await connection.rollback()

    # A malformed value is an error, never a match.
    async with ctx.db.engine.connect() as connection:
        await connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
        await connection.execute(
            text("SELECT set_config('app.current_org_id', 'not-a-uuid', true)")
        )
        with pytest.raises(DBAPIError) as caught:
            await connection.execute(text("SELECT count(*) FROM organizations"))
        assert isinstance(caught.value.orig, psycopg.errors.InvalidTextRepresentation)
        await connection.rollback()


async def test_tenant_scope_never_leaks_to_the_next_user_of_a_pooled_connection(
    settings: Settings, ctx: AppContext, client: httpx.AsyncClient
) -> None:
    alice = await register(client)
    # A single-connection pool: every transaction below reuses the same backend.
    single = Database(settings.model_copy(update={"db_pool_size": 1, "db_max_overflow": 0}))
    probe = text(
        "SELECT pg_backend_pid(), current_user,"
        " coalesce(current_setting('app.current_org_id', true), '')"
    )
    try:
        async with single.system_tx() as session:
            pid, owner, _ = (await session.execute(probe)).one()

        async with single.tenant_tx(_tenant(alice)) as session:
            assert tuple((await session.execute(probe)).one()) == (
                pid,
                APP_ROLE,
                str(alice.organization_id),
            )
        async with single.system_tx() as session:  # after COMMIT
            assert tuple((await session.execute(probe)).one()) == (pid, owner, "")

        with pytest.raises(RuntimeError, match="boom"):
            async with single.tenant_tx(_tenant(alice)) as session:
                await session.execute(probe)
                raise RuntimeError("boom")
        async with single.system_tx() as session:  # after ROLLBACK
            assert tuple((await session.execute(probe)).one()) == (pid, owner, "")

        with pytest.raises(DBAPIError):
            async with single.tenant_tx(_tenant(alice)) as session:
                await session.execute(text("SELECT * FROM users"))  # denied: aborts the tx
        async with single.system_tx() as session:  # after a failed statement
            assert tuple((await session.execute(probe)).one()) == (pid, owner, "")
            assert (await session.execute(text("SELECT count(*) FROM users"))).scalar_one() == 1
    finally:
        await single.dispose()


async def test_concurrent_tenants_never_observe_each_other(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    accounts = [await register(client) for _ in range(4)]

    async def observe(account: Account) -> set[uuid.UUID]:
        seen: set[uuid.UUID] = set()
        for _ in range(15):
            rows = await _as_tenant(ctx, account, "SELECT id FROM organizations")
            seen.update(row.id for row in rows)
            await asyncio.sleep(0)
        return seen

    results = await asyncio.gather(*(observe(account) for account in accounts * 3))
    for account, seen in zip(accounts * 3, results, strict=True):
        assert seen == {account.organization_id}


# --- Through the API -----------------------------------------------------------


async def test_api_resources_of_another_tenant_are_not_found(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    alice, bob = await register(client), await register(client)

    created = await client.post(f"{API}/account/exports", headers=alice.headers)
    assert created.status_code == 202, created.text
    export_id = created.json()["items"][0]["id"]
    assert created.json()["items"][0]["status"] == "available"

    own = await client.get(f"{API}/account/exports/{export_id}/download-url", headers=alice.headers)
    assert own.status_code == 200 and f"tenants/{alice.organization_id}/" in own.json()["url"]
    # Same id, other tenant: indistinguishable from an id that does not exist.
    foreign = await client.get(
        f"{API}/account/exports/{export_id}/download-url", headers=bob.headers
    )
    missing = await client.get(
        f"{API}/account/exports/{uuid.uuid4()}/download-url", headers=bob.headers
    )
    assert foreign.status_code == missing.status_code == 404
    assert error_code(foreign) == error_code(missing) == "export_not_found"
    assert (await client.get(f"{API}/account/exports", headers=bob.headers)).json()["items"] == []

    # Notifications: Bob cannot read nor acknowledge Alice's.
    alice_notifications = (await client.get(f"{API}/notifications", headers=alice.headers)).json()
    assert alice_notifications["unread_count"] == 1
    notification_id = alice_notifications["items"][0]["id"]
    bob_notifications = (await client.get(f"{API}/notifications", headers=bob.headers)).json()
    assert bob_notifications == {"items": [], "unread_count": 0}
    response = await client.post(
        f"{API}/notifications/read", headers=bob.headers, json={"notification_id": notification_id}
    )
    assert response.status_code == 204
    after = (await client.get(f"{API}/notifications", headers=alice.headers)).json()
    assert after["unread_count"] == 1

    # Each caller only ever gets their own organization.
    for account in (alice, bob):
        me = (await client.get(f"{API}/me", headers=account.headers)).json()
        assert me["organization"]["id"] == str(account.organization_id)
        assert me["user"]["email"] == account.email
