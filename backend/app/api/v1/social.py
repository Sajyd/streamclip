"""Social OAuth connect / disconnect and clip publishing."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Query, status
from fastapi.responses import RedirectResponse

from app.api.deps import Ctx, CurrentPrincipal
from app.core import release
from app.core.errors import PermissionDeniedError
from app.models.enums import SocialPlatform
from app.schemas.api import (
    Message,
    SocialAccountList,
    SocialAccountOut,
    SocialAutoPublishRequest,
    SocialConnectOut,
    SocialPublishRequest,
    SocialPublishResult,
)
from app.services import social as social_service
from app.tasks.queue import enqueue

router = APIRouter(tags=["social"])


def _account_out(item: social_service.SocialAccountRow) -> SocialAccountOut:
    return SocialAccountOut(
        id=item.id,
        platform=item.platform,
        status=item.status,
        display_name=item.display_name,
        connected_at=item.connected_at,
        auto_publish=item.auto_publish,
    )


@router.get("/social/accounts", response_model=SocialAccountList)
async def list_social_accounts(principal: CurrentPrincipal, ctx: Ctx) -> SocialAccountList:
    async with ctx.db.system_tx() as session:
        items = await social_service.list_accounts(session, principal.organization_id)
    return SocialAccountList(
        items=[_account_out(item) for item in items],
        oauth_available=release.SOCIAL_OAUTH_AVAILABLE,
        platforms=[p.value for p in SocialPlatform],
    )


@router.post(
    "/social/accounts/{platform}/connect",
    response_model=SocialConnectOut,
    status_code=status.HTTP_200_OK,
)
async def start_social_connect(
    platform: str, principal: CurrentPrincipal, ctx: Ctx
) -> SocialConnectOut:
    if not principal.can_manage_organization:
        raise PermissionDeniedError(
            "Seul un administrateur peut connecter un réseau social.",
            code="insufficient_role",
        )
    plat = social_service.platform_or_raise(platform)
    async with ctx.db.system_tx() as session:
        started = await social_service.start_connect(
            session,
            ctx.settings,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            platform=plat,
        )
    return SocialConnectOut(authorize_url=started.authorize_url, platform=started.platform)


@router.get("/social/oauth/callback")
async def social_oauth_callback(
    ctx: Ctx,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    base = ctx.settings.public_app_url.rstrip("/")
    if error or not code or not state:
        q = urlencode({"social": "error", "reason": error or "missing_code"})
        return RedirectResponse(f"{base}/settings?{q}", status_code=302)
    async with ctx.db.system_tx() as session:
        account = await social_service.complete_oauth(
            session, ctx.settings, code=code, state=state
        )
    q = urlencode(
        {"social": "connected", "platform": account.platform.value, "account": str(account.id)}
    )
    return RedirectResponse(f"{base}/settings?{q}", status_code=302)


@router.delete("/social/accounts/{account_id}", response_model=Message)
async def disconnect_social_account(
    account_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx
) -> Message:
    if not principal.can_manage_organization:
        raise PermissionDeniedError(
            "Seul un administrateur peut déconnecter un réseau social.",
            code="insufficient_role",
        )
    async with ctx.db.system_tx() as session:
        await social_service.disconnect(
            session, organization_id=principal.organization_id, account_id=account_id
        )
    return Message(message="Compte social déconnecté.")


@router.put("/social/auto-publish", response_model=Message)
async def update_auto_publish(
    body: SocialAutoPublishRequest, principal: CurrentPrincipal, ctx: Ctx
) -> Message:
    if not principal.can_manage_organization:
        raise PermissionDeniedError(
            "Seul un administrateur peut modifier la publication automatique.",
            code="insufficient_role",
        )
    async with ctx.db.system_tx() as session:
        platforms = await social_service.set_auto_publish(
            session,
            organization_id=principal.organization_id,
            platforms=body.platforms,
        )
    return Message(message=f"Publication auto : {', '.join(platforms) or 'désactivée'}.")


@router.post("/clips/{clip_id}/publish", response_model=SocialPublishResult)
async def publish_clip(
    clip_id: uuid.UUID,
    body: SocialPublishRequest,
    principal: CurrentPrincipal,
    ctx: Ctx,
) -> SocialPublishResult:
    social_service.require_oauth_open()
    async with ctx.db.system_tx() as session:
        pubs = await social_service.queue_publish(
            session,
            organization_id=principal.organization_id,
            clip_id=clip_id,
            platforms=body.platforms,
        )
        for pub in pubs:
            await enqueue(
                session,
                "social.publish",
                {"publication_id": str(pub.id)},
                queue="social",
                organization_id=principal.organization_id,
                idempotency_key=pub.idempotency_key,
            )
    return SocialPublishResult(
        queued=len(pubs),
        publication_ids=[p.id for p in pubs],
        message=f"{len(pubs)} publication(s) en file.",
    )
