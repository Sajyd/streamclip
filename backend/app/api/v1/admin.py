"""Back-office endpoints (platform staff only)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from app.api.deps import Admin, Ctx, Meta, Staff
from app.core.errors import NotFoundError
from app.schemas.api import (
    AdminAnalyticsOut,
    AdminClipList,
    AdminClipOut,
    AdminExportList,
    AdminExportOut,
    AdminLiveDetailOut,
    AdminLiveList,
    AdminLiveOut,
    AdminSubscriptionList,
    AdminSubscriptionOut,
    AdminSubscriptionSummary,
    AdminUserList,
    AdminUserOut,
    LivePlaybackOut,
    SuspendRequest,
)
from app.services import admin as admin_service
from app.services import playback as playback_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/analytics", response_model=AdminAnalyticsOut)
async def get_analytics(
    _staff: Staff,
    ctx: Ctx,
    period: Annotated[Literal["day", "week", "month", "year"], Query()] = "week",
) -> AdminAnalyticsOut:
    return AdminAnalyticsOut(**(await admin_service.analytics(ctx, period=period)))


@router.get("/users", response_model=AdminUserList)
async def list_users(
    _staff: Staff,
    ctx: Ctx,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> AdminUserList:
    items, next_cursor = await admin_service.list_users(
        ctx, limit=limit, cursor=cursor, search=search
    )
    return AdminUserList(items=[AdminUserOut(**item) for item in items], next_cursor=next_cursor)


@router.post("/users/{user_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def suspend_user(
    user_id: uuid.UUID, body: SuspendRequest, admin: Admin, ctx: Ctx, meta: Meta
) -> None:
    await admin_service.set_user_suspended(
        ctx, admin, user_id, suspended=True, reason=body.reason, meta=meta
    )


@router.post("/users/{user_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_user(user_id: uuid.UUID, admin: Admin, ctx: Ctx, meta: Meta) -> None:
    await admin_service.set_user_suspended(
        ctx, admin, user_id, suspended=False, reason=None, meta=meta
    )


@router.get("/subscriptions", response_model=AdminSubscriptionList)
async def list_subscriptions(
    _staff: Staff,
    ctx: Ctx,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> AdminSubscriptionList:
    items, next_cursor, summary = await admin_service.list_subscriptions(
        ctx, limit=limit, cursor=cursor, search=search
    )
    return AdminSubscriptionList(
        items=[AdminSubscriptionOut(**item) for item in items],
        next_cursor=next_cursor,
        summary=AdminSubscriptionSummary(**summary),
    )


@router.get("/lives", response_model=AdminLiveList)
async def list_lives(
    _staff: Staff,
    ctx: Ctx,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    active_only: Annotated[bool, Query()] = True,
) -> AdminLiveList:
    items, next_cursor = await admin_service.list_lives(
        ctx, limit=limit, cursor=cursor, active_only=active_only, search=search
    )
    return AdminLiveList(items=[AdminLiveOut(**item) for item in items], next_cursor=next_cursor)


@router.get("/lives/{live_id}", response_model=AdminLiveDetailOut)
async def get_live(_staff: Staff, ctx: Ctx, live_id: uuid.UUID) -> AdminLiveDetailOut:
    detail = await admin_service.get_live(ctx, live_id)
    if detail is None:
        raise NotFoundError("Live introuvable.", code="live_not_found")
    return AdminLiveDetailOut(**detail)


@router.get("/lives/{live_id}/playback", response_model=LivePlaybackOut)
async def get_live_playback(_staff: Staff, ctx: Ctx, live_id: uuid.UUID) -> LivePlaybackOut:
    """Staff live preview — session auth only; no user OBS secret."""
    info = await playback_service.playback_for_live(ctx, live_id)
    return LivePlaybackOut(**playback_service.info_to_dict(info, ctx.settings))


@router.get("/lives/{live_id}/playback/hls/{file_path:path}")
async def proxy_live_hls(
    _staff: Staff, ctx: Ctx, live_id: uuid.UUID, file_path: str
) -> Response:
    """Staff HLS proxy (session → dedicated agent). No OBS secret required."""
    if not file_path or ".." in file_path:
        raise NotFoundError("Segment introuvable.", code="preview_not_found")
    info = await playback_service.playback_for_live(ctx, live_id)
    body, content_type = await playback_service.proxy_hls(ctx, info, file_path=file_path)
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )


@router.get("/clips", response_model=AdminClipList)
async def list_clips(
    _staff: Staff,
    ctx: Ctx,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> AdminClipList:
    items, next_cursor = await admin_service.list_clips(
        ctx, limit=limit, cursor=cursor, search=search
    )
    return AdminClipList(items=[AdminClipOut(**item) for item in items], next_cursor=next_cursor)


@router.get("/exports", response_model=AdminExportList)
async def list_exports(
    _staff: Staff,
    ctx: Ctx,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> AdminExportList:
    items, next_cursor = await admin_service.list_exports(
        ctx, limit=limit, cursor=cursor, search=search
    )
    return AdminExportList(
        items=[AdminExportOut(**item) for item in items], next_cursor=next_cursor
    )
