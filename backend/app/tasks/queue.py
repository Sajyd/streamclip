"""Durable task queue on PostgreSQL.

* Tasks are inserted in the same transaction as the business change that
  needs them (transactional outbox): either both happen or neither does.
* Workers claim tasks with FOR UPDATE SKIP LOCKED and hold a time-limited
  lease. A worker that dies simply lets its lease expire; the task is picked
  up again. Handlers must therefore be idempotent (at-least-once delivery).
* Failures are retried with exponential backoff and jitter, then parked in
  the `dead` state for inspection instead of being lost.
* `idempotency_key` deduplicates logically identical tasks.

The same runner serves three execution modes: inline right after a request
(serverless), a scheduled drain endpoint, and a long-running worker process.
"""

import asyncio
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.db.engine import Database
from app.models.enums import TaskStatus
from app.models.system import Task

if TYPE_CHECKING:
    from app.context import AppContext

log = structlog.get_logger(__name__)

DEFAULT_LEASE_SECONDS = 120
_BACKOFF_BASE_SECONDS = 15
_BACKOFF_MAX_SECONDS = 3600


class PermanentTaskError(Exception):
    """Raised by a handler when retrying cannot help (bad payload, gone resource)."""


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    organization_id: uuid.UUID | None


TaskHandler = Callable[["AppContext", ClaimedTask], Awaitable[None]]
_HANDLERS: dict[str, TaskHandler] = {}


def task_handler(kind: str) -> Callable[[TaskHandler], TaskHandler]:
    def register(func: TaskHandler) -> TaskHandler:
        if kind in _HANDLERS:
            raise RuntimeError(f"Duplicate task handler for {kind!r}")
        _HANDLERS[kind] = func
        return func

    return register


def registered_kinds() -> list[str]:
    return sorted(_HANDLERS)


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    queue: str = "default",
    run_at: datetime | None = None,
    priority: int = 0,
    max_attempts: int = 5,
    idempotency_key: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Add a task within the caller's transaction.

    Returns the task id, or None when a task with the same idempotency key
    already exists (nothing is inserted).
    """
    statement = (
        insert(Task)
        .values(
            id=uuid7(),
            queue=queue,
            kind=kind,
            payload=payload or {},
            status=TaskStatus.QUEUED,
            priority=priority,
            run_at=run_at or datetime.now(UTC),
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            organization_id=organization_id,
        )
        .on_conflict_do_nothing(index_elements=[Task.idempotency_key])
        .returning(Task.id)
    )
    return (await session.execute(statement)).scalar_one_or_none()


def backoff_seconds(attempts: int) -> float:
    ceiling = min(_BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), _BACKOFF_MAX_SECONDS)
    return float(ceiling) * (0.5 + random.random() / 2)  # noqa: S311 - jitter, not security


_RECOVER_EXPIRED_LEASES = text(
    """
    UPDATE tasks
       SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
           locked_by = NULL,
           locked_until = NULL,
           finished_at = CASE WHEN attempts >= max_attempts THEN now() END,
           last_error = COALESCE(last_error, 'lease expired (worker lost)'),
           updated_at = now()
     WHERE status = 'running' AND locked_until < now()
    """
)

_CLAIM = text(
    """
    WITH picked AS (
        SELECT id FROM tasks
         WHERE status = 'queued'
           AND run_at <= now()
           AND queue = ANY(:queues)
           AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[])))
         ORDER BY priority DESC, run_at, id
         LIMIT :limit
           FOR UPDATE SKIP LOCKED
    )
    UPDATE tasks AS t
       SET status = 'running',
           attempts = t.attempts + 1,
           locked_by = :worker,
           locked_until = now() + make_interval(secs => :lease),
           started_at = now(),
           updated_at = now()
      FROM picked
     WHERE t.id = picked.id
 RETURNING t.id, t.kind, t.payload, t.attempts, t.max_attempts, t.organization_id
    """
)


async def claim_tasks(
    db: Database,
    worker: str,
    *,
    queues: list[str],
    limit: int,
    kinds: list[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> list[ClaimedTask]:
    async with db.system_tx() as session:
        await session.execute(_RECOVER_EXPIRED_LEASES)
        rows = await session.execute(
            _CLAIM,
            {
                "queues": queues,
                "kinds": kinds,
                "limit": limit,
                "worker": worker,
                "lease": lease_seconds,
            },
        )
        return [
            ClaimedTask(
                id=row.id,
                kind=row.kind,
                payload=row.payload,
                attempts=row.attempts,
                max_attempts=row.max_attempts,
                organization_id=row.organization_id,
            )
            for row in rows
        ]


async def _finish(
    db: Database,
    task: ClaimedTask,
    worker: str,
    *,
    error: str | None,
    permanent: bool,
) -> TaskStatus:
    if error is None:
        status = TaskStatus.SUCCEEDED
    elif permanent or task.attempts >= task.max_attempts:
        status = TaskStatus.DEAD
    else:
        status = TaskStatus.QUEUED
    run_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds(task.attempts))
    async with db.system_tx() as session:
        # `locked_by` guard: if our lease expired and another worker took the
        # task over, we must not overwrite its state.
        await session.execute(
            text(
                """
                UPDATE tasks
                   SET status = CAST(:status AS varchar),
                       locked_by = NULL,
                       locked_until = NULL,
                       last_error = CAST(:error AS text),
                       run_at = CASE WHEN CAST(:requeue AS boolean)
                                     THEN CAST(:run_at AS timestamptz) ELSE run_at END,
                       finished_at = CASE WHEN CAST(:requeue AS boolean) THEN NULL ELSE now() END,
                       updated_at = now()
                 WHERE id = :id AND status = 'running' AND locked_by = :worker
                """
            ),
            {
                "status": status.value,
                "requeue": status is TaskStatus.QUEUED,
                "error": error[:4000] if error else None,
                "run_at": run_at,
                "id": task.id,
                "worker": worker,
            },
        )
    return status


async def _execute(ctx: "AppContext", task: ClaimedTask, worker: str) -> TaskStatus:
    handler = _HANDLERS.get(task.kind)
    started = time.perf_counter()
    error: str | None = None
    permanent = False
    try:
        if handler is None:
            raise PermanentTaskError(f"No handler registered for task kind {task.kind!r}")
        await handler(ctx, task)
    except PermanentTaskError as exc:
        error, permanent = f"{type(exc).__name__}: {exc}", True
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.warning("task_failed", task_id=str(task.id), kind=task.kind, exc_info=exc)
    status = await _finish(ctx.db, task, worker, error=error, permanent=permanent)
    log.info(
        "task_finished",
        task_id=str(task.id),
        kind=task.kind,
        status=status.value,
        attempt=task.attempts,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return status


async def run_due_tasks(
    ctx: "AppContext",
    *,
    worker: str,
    queues: list[str] | None = None,
    kinds: list[str] | None = None,
    max_tasks: int = 10,
    time_budget_seconds: float = 10.0,
) -> dict[str, int]:
    """Run due tasks until none is left, `max_tasks` ran or the budget is spent."""
    deadline = time.monotonic() + time_budget_seconds
    summary = {"succeeded": 0, "retried": 0, "dead": 0}
    remaining = max_tasks
    while remaining > 0 and time.monotonic() < deadline:
        # One at a time: a lease starts when the task is claimed, so claiming a
        # batch would let the last tasks' leases run out while the first execute.
        tasks = await claim_tasks(
            ctx.db, worker, queues=queues or ["default"], kinds=kinds, limit=1
        )
        if not tasks:
            break
        for task in tasks:
            status = await _execute(ctx, task, worker)
            key = {
                TaskStatus.SUCCEEDED: "succeeded",
                TaskStatus.QUEUED: "retried",
                TaskStatus.DEAD: "dead",
            }[status]
            summary[key] += 1
            remaining -= 1
    return summary
