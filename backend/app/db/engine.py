"""Database access: engine management and transaction scoping.

Two kinds of transactions exist, and choosing one is always explicit:

* `Database.tenant_tx(ctx)`: the transaction runs as the unprivileged
  `streamclip_app` role with the caller's organization pinned in
  `app.current_org_id`. Row-level security then makes other tenants' rows
  invisible, whatever the query. All tenant-facing reads and writes use it.

* `Database.system_tx()`: the transaction runs as the login role (which
  bypasses row-level security). Reserved for code that legitimately spans
  tenants or runs before a tenant is known: authentication, payment webhooks,
  background tasks and the back-office.

The role and settings are applied with transaction-local `set_config`, so they
are safe behind a transaction-mode connection pooler (PgBouncer / Neon): they
vanish at COMMIT/ROLLBACK and can never leak to another request.
"""

import asyncio
import uuid
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, event, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session, SessionTransaction
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.models.base import APP_ROLE


@dataclass(frozen=True, slots=True)
class TenantContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class _Scope:
    statement_timeout_ms: int
    tenant: TenantContext | None


def normalize_database_url(url: str) -> str:
    """Accept any postgres URL flavour and force the psycopg (v3) driver."""
    parsed = make_url(url)
    # "postgres://" is the libpq spelling many providers hand out.
    if parsed.get_backend_name() not in ("postgresql", "postgres"):
        raise ValueError("Only PostgreSQL is supported")
    return parsed.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


@event.listens_for(Session, "after_begin")
def _apply_transaction_scope(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    scope: _Scope | None = session.info.get("scope")
    if scope is None:
        return
    if scope.tenant is None:
        connection.execute(
            text(
                "SELECT set_config('statement_timeout', :timeout, true),"
                " set_config('TimeZone', 'UTC', true)"
            ),
            {"timeout": str(scope.statement_timeout_ms)},
        )
        return
    connection.execute(
        text(
            "SELECT set_config('statement_timeout', :timeout, true),"
            " set_config('TimeZone', 'UTC', true),"
            " set_config('app.current_org_id', :org, true),"
            " set_config('app.current_user_id', :usr, true),"
            " set_config('role', :role, true)"
        ),
        {
            "timeout": str(scope.statement_timeout_ms),
            "org": str(scope.tenant.organization_id),
            "usr": str(scope.tenant.user_id),
            "role": APP_ROLE,
        },
    )


class Database:
    """Owns the engine(s) and hands out scoped transactions.

    One engine is kept per event loop: serverless runtimes may reuse a process
    with a fresh loop, and pooled connections must never cross loops.
    """

    def __init__(self, settings: Settings, *, use_null_pool: bool = False) -> None:
        self._settings = settings
        self._url = normalize_database_url(settings.database_url.get_secret_value())
        self._use_null_pool = use_null_pool
        self._engines: dict[int, tuple[weakref.ref[asyncio.AbstractEventLoop], AsyncEngine]] = {}

    def _create_engine(self) -> AsyncEngine:
        kwargs: dict[str, Any] = {
            # Required behind PgBouncer transaction pooling: no server-side
            # prepared statements (they are bound to one server connection).
            "connect_args": {"prepare_threshold": None, "connect_timeout": 10},
        }
        if self._use_null_pool:
            kwargs["poolclass"] = NullPool
        else:
            kwargs.update(
                pool_size=self._settings.db_pool_size,
                max_overflow=self._settings.db_max_overflow,
                pool_pre_ping=True,
                pool_recycle=240,
                pool_timeout=10,
            )
        return create_async_engine(self._url, **kwargs)

    @property
    def engine(self) -> AsyncEngine:
        loop = asyncio.get_running_loop()
        entry = self._engines.get(id(loop))
        if entry is not None and entry[0]() is loop:
            return entry[1]
        for key, (loop_ref, _stale) in list(self._engines.items()):
            stale_loop = loop_ref()
            if stale_loop is None or stale_loop.is_closed():
                # Connections of a dead loop cannot be closed gracefully.
                del self._engines[key]
        engine = self._create_engine()
        self._engines[id(loop)] = (weakref.ref(loop), engine)
        return engine

    def _session(self, tenant: TenantContext | None) -> AsyncSession:
        scope = _Scope(self._settings.db_statement_timeout_ms, tenant)
        return AsyncSession(self.engine, expire_on_commit=False, info={"scope": scope})

    @asynccontextmanager
    async def system_tx(self) -> AsyncIterator[AsyncSession]:
        async with self._session(None) as session, session.begin():
            yield session

    @asynccontextmanager
    async def tenant_tx(self, tenant: TenantContext) -> AsyncIterator[AsyncSession]:
        async with self._session(tenant) as session, session.begin():
            yield session

    async def ping(self) -> None:
        async with self.system_tx() as session:
            await session.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        loop = asyncio.get_running_loop()
        entry = self._engines.pop(id(loop), None)
        if entry is not None:
            await entry[1].dispose()
