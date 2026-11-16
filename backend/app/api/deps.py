"""Shared request dependencies: application context, caller identity, roles."""

import hmac
import time
from typing import Annotated

import structlog
from fastapi import Depends, Request

from app.context import AppContext
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.models.enums import PlatformRole
from app.services.audit import RequestMeta
from app.services.auth import Principal, authenticate
from app.tasks.queue import run_due_tasks


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


def get_request_meta(request: Request) -> RequestMeta:
    return RequestMeta(
        ip=getattr(request.state, "client_ip", None),
        user_agent=getattr(request.state, "user_agent", None),
        request_id=getattr(request.state, "request_id", None),
    )


Ctx = Annotated[AppContext, Depends(get_ctx)]
Meta = Annotated[RequestMeta, Depends(get_request_meta)]


def _bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError(
            "Authentification requise.",
            code="unauthenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


async def get_principal(request: Request, ctx: Ctx) -> Principal:
    principal = await authenticate(ctx, _bearer_token(request))
    structlog.contextvars.bind_contextvars(
        user_id=str(principal.user_id), organization_id=str(principal.organization_id)
    )
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def get_staff(principal: CurrentPrincipal) -> Principal:
    """Back-office read access: support and admin."""
    if principal.platform_role not in (PlatformRole.SUPPORT, PlatformRole.ADMIN):
        raise PermissionDeniedError("Accès réservé à l'administration.", code="admin_required")
    return principal


async def get_admin(principal: CurrentPrincipal) -> Principal:
    """Back-office write access: admin only."""
    if principal.platform_role is not PlatformRole.ADMIN:
        raise PermissionDeniedError("Accès réservé à l'administration.", code="admin_required")
    return principal


Staff = Annotated[Principal, Depends(get_staff)]
Admin = Annotated[Principal, Depends(get_admin)]


def require_cron_secret(request: Request, ctx: Ctx) -> None:
    secret = ctx.settings.cron_secret
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if (
        secret is None
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(token.strip(), secret.get_secret_value())
    ):
        raise AuthenticationError("Authentification requise.", code="unauthenticated")


async def drain_tasks(
    ctx: AppContext,
    request: Request,
    *,
    kinds: list[str],
    max_tasks: int = 3,
    time_budget_seconds: float = 8.0,
) -> None:
    """Run the tasks this request just queued, before answering.

    Serverless instances may be frozen as soon as the response is sent, so
    urgent work (an e-mail, an export) is executed inline. Anything that fails
    or does not fit in the budget stays queued and is retried by the
    scheduled drain: the queue, not this call, guarantees delivery.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        await run_due_tasks(
            ctx,
            worker=f"inline-{request_id}",
            kinds=kinds,
            max_tasks=max_tasks,
            time_budget_seconds=time_budget_seconds,
        )
    except Exception as exc:
        structlog.get_logger(__name__).warning("inline_drain_failed", exc_info=exc)


class ResponseTimePadder:
    """Make an endpoint take at least `minimum` seconds, so its duration does
    not reveal which branch ran (e.g. whether an e-mail address is known)."""

    def __init__(self, minimum: float) -> None:
        self._minimum = minimum
        self._started = time.monotonic()

    @property
    def remaining(self) -> float:
        return max(self._minimum - (time.monotonic() - self._started), 0.0)
