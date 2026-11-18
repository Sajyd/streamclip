"""Quota accounting: idempotent metering, thresholds and period rollover."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.context import AppContext
from app.models.billing import UsagePeriod, UsageRecord
from app.models.system import Notification
from app.services.entitlements import QuotaSnapshot, add_months, record_usage
from tests.helpers import API, Account, register

MINUTE_MS = 60_000


async def _use(ctx: AppContext, account: Account, minutes: float, key: str) -> QuotaSnapshot:
    async with ctx.db.system_tx() as session:
        return await record_usage(
            session,
            organization_id=account.organization_id,
            quantity_ms=int(minutes * MINUTE_MS),
            idempotency_key=key,
        )


async def _notification_kinds(ctx: AppContext) -> list[str]:
    async with ctx.db.system_tx() as session:
        return list(
            (
                await session.execute(select(Notification.kind).order_by(Notification.created_at))
            ).scalars()
        )


def test_add_months_clamps_to_the_month_length() -> None:
    def at(year: int, month: int, day: int) -> datetime:
        return datetime(year, month, day, 12, 30, tzinfo=UTC)

    assert add_months(at(2026, 1, 31), 1) == at(2026, 2, 28)
    assert add_months(at(2028, 1, 31), 1) == at(2028, 2, 29)  # leap year
    assert add_months(at(2026, 12, 15), 1) == at(2027, 1, 15)
    assert add_months(at(2026, 3, 31), 1) == at(2026, 4, 30)
    assert add_months(at(2026, 11, 30), 3) == at(2027, 2, 28)


def test_quota_snapshot_thresholds() -> None:
    now = datetime.now(UTC)

    def snapshot(consumed: int, included: int = 1000) -> QuotaSnapshot:
        return QuotaSnapshot(included, consumed, now, now + timedelta(days=30))

    assert (snapshot(799).warning, snapshot(799).exhausted) == (False, False)
    assert (snapshot(800).warning, snapshot(800).exhausted) == (True, False)
    assert (snapshot(1000).warning, snapshot(1000).exhausted) == (True, True)
    assert snapshot(1500).remaining_ms == 0 and snapshot(1500).used_ratio == 1.0
    assert snapshot(0, included=0).exhausted is True  # a zero quota allows nothing


async def test_usage_is_charged_once_per_idempotency_key(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    account = await register(client)
    first = await _use(ctx, account, 10, "session-1:segment-0")
    replay = await _use(ctx, account, 10, "session-1:segment-0")  # retried task
    assert first.consumed_ms == replay.consumed_ms == 10 * MINUTE_MS
    second = await _use(ctx, account, 5, "session-1:segment-1")
    assert second.consumed_ms == 15 * MINUTE_MS and second.remaining_ms == 45 * MINUTE_MS

    async with ctx.db.system_tx() as session:
        records = (await session.execute(select(UsageRecord.quantity_ms))).scalars().all()
    assert sorted(records) == [5 * MINUTE_MS, 10 * MINUTE_MS]

    overview = (await client.get(f"{API}/billing/overview", headers=account.headers)).json()
    assert overview["quota"]["consumed_seconds"] == 15 * 60
    assert overview["quota"]["used_ratio"] == 0.25


async def test_processing_time_must_be_positive(ctx: AppContext, client: httpx.AsyncClient) -> None:
    account = await register(client)
    for minutes in (0, -5):
        with pytest.raises(ValueError, match="positive"):
            await _use(ctx, account, minutes, f"bad-{minutes}")


async def test_warning_at_80_percent_and_stop_at_100_percent_notify_once(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    account = await register(client)  # Free plan: 60 minutes
    assert (await _use(ctx, account, 47, "a")).warning is False
    assert await _notification_kinds(ctx) == []

    crossed = await _use(ctx, account, 1, "b")  # 48 min = 80 %
    assert crossed.warning is True and crossed.exhausted is False
    await _use(ctx, account, 5, "c")  # still above 80 %: no second warning
    assert await _notification_kinds(ctx) == ["quota.warning"]

    done = await _use(ctx, account, 7, "d")  # 60 min = 100 %
    assert done.exhausted is True and done.remaining_ms == 0
    await _use(ctx, account, 3, "e")  # past the plan: not charged, notified once
    assert await _notification_kinds(ctx) == ["quota.warning", "quota.exhausted"]

    overview = (await client.get(f"{API}/billing/overview", headers=account.headers)).json()
    assert overview["quota"]["exhausted"] is True and overview["quota"]["remaining_seconds"] == 0
    assert overview["quota"]["consumed_seconds"] == 60 * 60
    assert overview["quota"]["used_ratio"] == 1.0


async def test_a_segment_that_crosses_the_plan_stops_at_the_threshold(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    account = await register(client)  # Free plan: 60 minutes
    await _use(ctx, account, 58, "almost")
    capped = await _use(ctx, account, 10, "crosses")
    assert capped.consumed_ms == 60 * MINUTE_MS
    assert capped.remaining_ms == 0 and capped.exhausted is True
    overview = (await client.get(f"{API}/billing/overview", headers=account.headers)).json()
    assert overview["quota"]["consumed_seconds"] == 60 * 60


async def test_jumping_straight_to_exhaustion_sends_only_the_exhausted_notice(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    account = await register(client)
    await _use(ctx, account, 60, "all-at-once")
    assert await _notification_kinds(ctx) == ["quota.exhausted"]


async def test_concurrent_usage_events_are_all_accounted_for(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    account = await register(client)
    # 8 distinct events and 8 duplicates racing each other.
    keys = [f"k{i}" for i in range(8)] * 2
    await asyncio.gather(*(_use(ctx, account, 2, key) for key in keys))
    async with ctx.db.system_tx() as session:
        consumed = (await session.execute(select(UsagePeriod.consumed_ms))).scalar_one()
    assert consumed == 8 * 2 * MINUTE_MS


async def test_free_plan_rolls_over_monthly_with_a_fresh_quota(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    account = await register(client)
    await _use(ctx, account, 60, "month-1")
    async with ctx.db.system_tx() as session:  # move the account 70 days into the past
        await session.execute(
            text(
                "UPDATE subscriptions SET current_period_start = current_period_start - interval"
                " '70 days', current_period_end = current_period_end - interval '70 days'"
            )
        )
        await session.execute(
            text(
                "UPDATE usage_periods SET period_start = period_start - interval '70 days',"
                " period_end = period_end - interval '70 days'"
            )
        )

    overview = (await client.get(f"{API}/billing/overview", headers=account.headers)).json()
    assert overview["plan"]["code"] == "free"
    assert overview["quota"]["consumed_seconds"] == 0 and overview["quota"]["exhausted"] is False
    start = datetime.fromisoformat(overview["current_period_start"])
    end = datetime.fromisoformat(overview["current_period_end"])
    assert start <= datetime.now(UTC) < end  # skipped the empty month in between

    async with ctx.db.system_tx() as session:
        periods = (
            (
                await session.execute(
                    select(UsagePeriod.consumed_ms).order_by(UsagePeriod.period_start)
                )
            )
            .scalars()
            .all()
        )
    assert periods == [60 * MINUTE_MS, 0]  # the past period is kept as history
    # Reading again does not create yet another period.
    await client.get(f"{API}/billing/overview", headers=account.headers)
    async with ctx.db.system_tx() as session:
        assert (await session.execute(text("SELECT count(*) FROM usage_periods"))).scalar_one() == 2
