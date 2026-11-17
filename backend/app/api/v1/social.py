"""Social account listing (OAuth connect opens when SOCIAL_OAUTH_AVAILABLE)."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import Ctx, CurrentPrincipal
from app.core import release
from app.core.errors import ServiceUnavailableError
from app.models.enums import SocialPlatform
from app.schemas.api import Message, SocialAccountList, SocialAccountOut
from app.services import social as social_service

router = APIRouter(tags=["social"])


@router.get("/social/accounts", response_model=SocialAccountList)
async def list_social_accounts(principal: CurrentPrincipal, ctx: Ctx) -> SocialAccountList:
    # Tokens live on a table the tenant role cannot read; system path filters
    # by organization_id and never returns secrets.
    async with ctx.db.system_tx() as session:
        items = await social_service.list_accounts(session, principal.organization_id)
    return SocialAccountList(
        items=[
            SocialAccountOut(
                id=item.id,
                platform=item.platform,
                status=item.status,
                display_name=item.display_name,
                connected_at=item.connected_at,
            )
            for item in items
        ],
        oauth_available=release.SOCIAL_OAUTH_AVAILABLE,
        platforms=[p.value for p in SocialPlatform],
    )


@router.post(
    "/social/accounts/{platform}/connect",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_social_connect(platform: str, principal: CurrentPrincipal, ctx: Ctx) -> Message:
    del principal, ctx  # reserved for the upcoming OAuth handshake
    social_service.platform_or_raise(platform)
    social_service.require_oauth_open()
    # Unreachable until SOCIAL_OAUTH_AVAILABLE is flipped.
    raise ServiceUnavailableError(
        "La connexion OAuth n'est pas encore ouverte.",
        code="social_oauth_unavailable",
    )
