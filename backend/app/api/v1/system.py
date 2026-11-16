"""Service metadata, health probes and scheduled maintenance."""

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import Ctx, require_cron_secret
from app.context import AppContext
from app.core import release
from app.db.migrations import expected_revision
from app.schemas.api import Capabilities, MetaResponse
from app.security.passwords import MIN_PASSWORD_LENGTH
from app.tasks.queue import enqueue, run_due_tasks

log = structlog.get_logger(__name__)
router = APIRouter(tags=["system"])


def capabilities(ctx: AppContext) -> Capabilities:
    """What this deployment can actually do. The web application uses it to
    hide features whose backing service is not configured, instead of
    offering buttons that would fail."""
    return Capabilities(
        registration_open=ctx.settings.registration_open,
        email_delivery=ctx.mailer.enabled,
        billing=ctx.stripe is not None,
        billing_test_mode=ctx.stripe is not None and not ctx.stripe.livemode,
        storage=ctx.storage is not None,
        live_processing=release.LIVE_PROCESSING_AVAILABLE,
    )


@router.get("/meta", response_model=MetaResponse)
async def meta(ctx: Ctx) -> MetaResponse:
    return MetaResponse(
        name=ctx.settings.app_name,
        environment=ctx.settings.environment,
        capabilities=capabilities(ctx),
        password_min_length=MIN_PASSWORD_LENGTH,
        terms_version=ctx.settings.terms_version,
    )


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process answers. No dependency is touched."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(ctx: Ctx, deep: bool = False) -> JSONResponse:
    """Readiness: database reachable and migrated to the revision this code
    expects. `?deep=true` also checks object storage."""
    checks: dict[str, Any] = {}
    try:
        async with ctx.db.system_tx() as session:
            revision = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
        expected = expected_revision()
        checks["database"] = "ok"
        checks["migrations"] = (
            "ok" if revision == expected else f"expected {expected}, found {revision}"
        )
    except Exception as exc:
        log.error("readiness_database_failed", exc_info=exc)
        checks["database"] = "unavailable"
    if deep and ctx.storage is not None:
        try:
            await ctx.storage.check()
            checks["storage"] = "ok"
        except Exception as exc:
            log.error("readiness_storage_failed", exc_info=exc)
            checks["storage"] = "unavailable"
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


@router.get("/internal/cron/maintenance", dependencies=[Depends(require_cron_secret)])
async def cron_maintenance(request: Request, ctx: Ctx) -> dict[str, Any]:
    """Scheduled entry point: queue the daily housekeeping, then drain every
    due task (including retries left behind by earlier requests)."""
    today = datetime.now(UTC).date().isoformat()
    async with ctx.db.system_tx() as session:
        await enqueue(
            session, "maintenance.cleanup", idempotency_key=f"maintenance.cleanup:{today}"
        )
    summary = await run_due_tasks(
        ctx,
        worker=f"cron-{getattr(request.state, 'request_id', 'unknown')}",
        max_tasks=200,
        time_budget_seconds=50.0,
    )
    return {"status": "ok", "tasks": summary}
