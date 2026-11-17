"""Clip library endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import Ctx, CurrentPrincipal
from app.schemas.api import ClipList, ClipOut, UrlResponse
from app.services import clips as clips_service

router = APIRouter(tags=["clips"])


def _clip_out(row: clips_service.ClipRow) -> ClipOut:
    return ClipOut(
        id=row.id,
        title=row.title,
        description=row.description,
        status=row.status,
        category=row.category,
        score=float(row.score),
        start_ms=row.start_ms,
        end_ms=row.end_ms,
        duration_ms=row.duration_ms,
        is_favorite=row.is_favorite,
        thumbnail_available=row.thumbnail_available,
        download_available=row.download_available,
        created_at=row.created_at,
        stream_session_id=row.stream_session_id,
    )


@router.get("/clips", response_model=ClipList)
async def list_clips(principal: CurrentPrincipal, ctx: Ctx) -> ClipList:
    async with ctx.db.tenant_tx(principal.tenant) as session:
        items = await clips_service.list_clips(session, principal.organization_id)
    return ClipList(items=[_clip_out(item) for item in items])


@router.get("/clips/{clip_id}/download-url", response_model=UrlResponse)
async def clip_download_url(
    clip_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx
) -> UrlResponse:
    return UrlResponse(url=await clips_service.download_url(ctx, principal, clip_id))
