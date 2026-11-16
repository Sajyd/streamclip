"""Durable task queue: delivery guarantees under failures and concurrency."""

import asyncio
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select, text

from app.context import AppContext
from app.models.enums import TaskStatus
from app.models.system import Task
from app.tasks.queue import (
    ClaimedTask,
    PermanentTaskError,
    backoff_seconds,
    claim_tasks,
    enqueue,
    run_due_tasks,
    task_handler,
)
from tests.helpers import register

EXECUTIONS: Counter[str] = Counter()
FAILURES_LEFT: dict[str, int] = {}


@task_handler("test.record")
async def _record(_ctx: AppContext, task: ClaimedTask) -> None:
    await asyncio.sleep(0.01)  # give concurrent workers a chance to collide
    EXECUTIONS[str(task.payload["name"])] += 1


@task_handler("test.flaky")
async def _flaky(_ctx: AppContext, task: ClaimedTask) -> None:
    name = str(task.payload["name"])
    if FAILURES_LEFT.get(name, 0) > 0:
        FAILURES_LEFT[name] -= 1
        raise ConnectionError("temporary outage")
    EXECUTIONS[name] += 1


@task_handler("test.permanent")
async def _permanent(_ctx: AppContext, _task: ClaimedTask) -> None:
    raise PermanentTaskError("payload can never be processed")


async def _add(ctx: AppContext, kind: str, name: str = "t", **kwargs: Any) -> uuid.UUID | None:
    async with ctx.db.system_tx() as session:
        return await enqueue(session, kind, {"name": name}, **kwargs)


async def _task(ctx: AppContext, task_id: uuid.UUID | None) -> Task:
    assert task_id is not None
    async with ctx.db.system_tx() as session:
        return await session.get_one(Task, task_id)


async def _make_due(ctx: AppContext) -> None:
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE tasks SET run_at = now() WHERE status = 'queued'"))


async def test_task_runs_once_and_is_marked_succeeded(ctx: AppContext) -> None:
    EXECUTIONS.clear()
    task_id = await _add(ctx, "test.record", "once")
    assert await run_due_tasks(ctx, worker="w1") == {"succeeded": 1, "retried": 0, "dead": 0}
    assert await run_due_tasks(ctx, worker="w1") == {"succeeded": 0, "retried": 0, "dead": 0}
    task = await _task(ctx, task_id)
    assert task.status is TaskStatus.SUCCEEDED and task.attempts == 1
    assert task.locked_by is None and task.finished_at is not None
    assert EXECUTIONS == {"once": 1}


async def test_idempotency_key_deduplicates_enqueues(ctx: AppContext) -> None:
    first = await _add(ctx, "test.record", idempotency_key="report:2026-11")
    second = await _add(ctx, "test.record", idempotency_key="report:2026-11")
    other = await _add(ctx, "test.record", idempotency_key="report:2026-12")
    assert first is not None and second is None and other is not None
    async with ctx.db.system_tx() as session:
        assert (await session.execute(text("SELECT count(*) FROM tasks"))).scalar_one() == 2


async def test_enqueue_is_transactional_with_the_business_change(ctx: AppContext) -> None:
    try:
        async with ctx.db.system_tx() as session:
            await enqueue(session, "test.record", {"name": "rolled-back"})
            raise RuntimeError("business operation failed")
    except RuntimeError:
        pass
    async with ctx.db.system_tx() as session:
        assert (await session.execute(text("SELECT count(*) FROM tasks"))).scalar_one() == 0


async def test_failures_are_retried_with_backoff_then_succeed(ctx: AppContext) -> None:
    EXECUTIONS.clear()
    FAILURES_LEFT["retry"] = 2
    task_id = await _add(ctx, "test.flaky", "retry")

    assert await run_due_tasks(ctx, worker="w1") == {"succeeded": 0, "retried": 1, "dead": 0}
    task = await _task(ctx, task_id)
    assert task.status is TaskStatus.QUEUED and task.attempts == 1
    assert task.last_error == "ConnectionError: temporary outage"
    assert task.run_at > datetime.now(UTC) + timedelta(seconds=5)  # backoff: not due yet
    assert await run_due_tasks(ctx, worker="w1") == {"succeeded": 0, "retried": 0, "dead": 0}

    await _make_due(ctx)
    assert (await run_due_tasks(ctx, worker="w1"))["retried"] == 1
    await _make_due(ctx)
    assert (await run_due_tasks(ctx, worker="w1"))["succeeded"] == 1
    task = await _task(ctx, task_id)
    assert task.status is TaskStatus.SUCCEEDED and task.attempts == 3 and task.last_error is None
    assert EXECUTIONS == {"retry": 1}


async def test_exhausted_retries_and_permanent_errors_go_to_the_dead_state(
    ctx: AppContext,
) -> None:
    FAILURES_LEFT["doomed"] = 99
    doomed = await _add(ctx, "test.flaky", "doomed", max_attempts=2)
    permanent = await _add(ctx, "test.permanent", max_attempts=5)
    unknown = await _add(ctx, "test.no_such_handler")

    summary = await run_due_tasks(ctx, worker="w1")
    assert summary == {"succeeded": 0, "retried": 1, "dead": 2}
    await _make_due(ctx)
    assert await run_due_tasks(ctx, worker="w1") == {"succeeded": 0, "retried": 0, "dead": 1}

    doomed_task = await _task(ctx, doomed)
    assert doomed_task.status is TaskStatus.DEAD and doomed_task.attempts == 2
    permanent_task = await _task(ctx, permanent)
    assert permanent_task.status is TaskStatus.DEAD and permanent_task.attempts == 1
    assert "can never be processed" in (permanent_task.last_error or "")
    assert "No handler registered" in ((await _task(ctx, unknown)).last_error or "")
    # Dead tasks are kept for inspection and never run again.
    await _make_due(ctx)
    assert await run_due_tasks(ctx, worker="w1") == {"succeeded": 0, "retried": 0, "dead": 0}


async def test_backoff_grows_exponentially_and_is_capped() -> None:
    for attempts, ceiling in ((1, 15), (2, 30), (3, 60), (5, 240), (20, 3600)):
        samples = [backoff_seconds(attempts) for _ in range(200)]
        assert ceiling / 2 <= min(samples) and max(samples) <= ceiling


async def test_scheduling_priority_and_queue_selection(ctx: AppContext) -> None:
    EXECUTIONS.clear()
    await _add(ctx, "test.record", "later", run_at=datetime.now(UTC) + timedelta(hours=1))
    await _add(ctx, "test.record", "low", priority=0)
    await _add(ctx, "test.record", "high", priority=10)
    await _add(ctx, "test.record", "other-queue", queue="media")

    first = await claim_tasks(ctx.db, "w1", queues=["default"], limit=1)
    assert [task.payload["name"] for task in first] == ["high"]
    assert (await run_due_tasks(ctx, worker="w2"))["succeeded"] == 1  # "low"; "high" is leased
    assert EXECUTIONS == {"low": 1}
    assert (await run_due_tasks(ctx, worker="w2", queues=["media"]))["succeeded"] == 1
    assert (await run_due_tasks(ctx, worker="w2", kinds=["test.flaky"]))["succeeded"] == 0
    assert EXECUTIONS == {"low": 1, "other-queue": 1}  # "later" is not due


async def test_concurrent_workers_never_run_the_same_task_twice(ctx: AppContext) -> None:
    EXECUTIONS.clear()
    for index in range(24):
        await _add(ctx, "test.record", f"job-{index}")
    summaries = await asyncio.gather(
        *(run_due_tasks(ctx, worker=f"worker-{n}", max_tasks=24) for n in range(6))
    )
    assert sum(summary["succeeded"] for summary in summaries) == 24
    assert len(EXECUTIONS) == 24 and set(EXECUTIONS.values()) == {1}


async def test_task_of_a_crashed_worker_is_recovered_after_its_lease(ctx: AppContext) -> None:
    EXECUTIONS.clear()
    task_id = await _add(ctx, "test.record", "orphan")
    claimed = await claim_tasks(ctx.db, "crashed-worker", queues=["default"], limit=1)
    assert len(claimed) == 1  # ...and the worker dies here, never reporting back

    # While the lease is valid nobody else takes the task.
    assert await run_due_tasks(ctx, worker="w2") == {"succeeded": 0, "retried": 0, "dead": 0}
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE tasks SET locked_until = now() - interval '1 second'"))
    assert await run_due_tasks(ctx, worker="w2") == {"succeeded": 1, "retried": 0, "dead": 0}
    task = await _task(ctx, task_id)
    assert task.status is TaskStatus.SUCCEEDED and task.attempts == 2
    assert EXECUTIONS == {"orphan": 1}


async def test_lease_expiry_on_the_last_attempt_parks_the_task(ctx: AppContext) -> None:
    task_id = await _add(ctx, "test.record", "poison", max_attempts=1)
    await claim_tasks(ctx.db, "crashed-worker", queues=["default"], limit=1)
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE tasks SET locked_until = now() - interval '1 second'"))
    assert await run_due_tasks(ctx, worker="w2") == {"succeeded": 0, "retried": 0, "dead": 0}
    task = await _task(ctx, task_id)
    assert task.status is TaskStatus.DEAD
    assert task.last_error == "lease expired (worker lost)"


async def test_a_worker_that_lost_its_lease_cannot_overwrite_the_new_owner(
    ctx: AppContext,
) -> None:
    from app.tasks.queue import _finish

    task_id = await _add(ctx, "test.record", "contended")
    slow = (await claim_tasks(ctx.db, "slow-worker", queues=["default"], limit=1))[0]
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE tasks SET locked_until = now() - interval '1 second'"))
    fast = (await claim_tasks(ctx.db, "fast-worker", queues=["default"], limit=1))[0]
    assert fast.id == slow.id and fast.attempts == 2

    # The slow worker finally reports a failure: it must be ignored.
    await _finish(ctx.db, slow, "slow-worker", error="late failure", permanent=True)
    task = await _task(ctx, task_id)
    assert task.status is TaskStatus.RUNNING and task.locked_by == "fast-worker"
    await _finish(ctx.db, fast, "fast-worker", error=None, permanent=False)
    assert (await _task(ctx, task_id)).status is TaskStatus.SUCCEEDED


async def test_maintenance_cleanup_purges_expired_secrets_and_exports(
    ctx: AppContext, client: httpx.AsyncClient
) -> None:
    account = await register(client)
    created = await client.post("/api/v1/account/exports", headers=account.headers)
    assert created.status_code == 202
    key = next(iter(ctx.storage.objects))  # type: ignore[union-attr]

    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE storage_assets SET expires_at = now() - interval '1 h'"))
        await session.execute(
            text("UPDATE refresh_tokens SET expires_at = now() - interval '2 days'")
        )
        await session.execute(text("UPDATE auth_tokens SET expires_at = now() - interval '8 days'"))
        await session.execute(
            text("UPDATE rate_limit_counters SET expires_at = now() - interval '1 s'")
        )
        await session.execute(
            text("UPDATE audit_logs SET occurred_at = now() - interval '400 days'")
        )
        await session.execute(
            text(
                "UPDATE tasks SET finished_at = now() - interval '8 days'"
                " WHERE status = 'succeeded'"
            )
        )

    response = await client.get(
        "/api/v1/internal/cron/maintenance",
        headers={"Authorization": f"Bearer {ctx.settings.cron_secret.get_secret_value()}"},  # type: ignore[union-attr]
    )
    assert response.status_code == 200 and response.json()["tasks"]["succeeded"] == 1

    assert key not in ctx.storage.objects  # type: ignore[union-attr]
    async with ctx.db.system_tx() as session:
        counts = {
            table: (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            for table in ("refresh_tokens", "auth_tokens", "rate_limit_counters")
        }
        asset_status = (
            await session.execute(text("SELECT status FROM storage_assets"))
        ).scalar_one()
        with_ip = (
            await session.execute(text("SELECT count(*) FROM audit_logs WHERE ip IS NOT NULL"))
        ).scalar_one()
        kinds = (await session.execute(select(Task.kind))).scalars().all()
    assert counts == {"refresh_tokens": 0, "auth_tokens": 0, "rate_limit_counters": 0}
    assert asset_status == "deleted"
    assert with_ip == 0  # network identifiers are dropped after the retention period
    assert kinds == ["maintenance.cleanup"]  # old finished tasks were purged
    # The expired export is no longer offered for download.
    exports = await client.get("/api/v1/account/exports", headers=account.headers)
    assert exports.status_code == 200 and exports.json()["items"] == []
