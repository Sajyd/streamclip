"""Viral highlight candidates for Remotion playback."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import Ctx, CurrentPrincipal
from app.schemas.api import HighlightList, HighlightOut, UrlResponse
from app.services import highlights as highlights_service

router = APIRouter(tags=["highlights"])


def _out(row: highlights_service.HighlightRow) -> HighlightOut:
    return HighlightOut(
        id=row.id,
        stream_session_id=row.stream_session_id,
        title=row.title,
        description=row.description,
        category=row.category,
        score=float(row.score),
        start_ms=row.start_ms,
        end_ms=row.end_ms,
        relative_start_ms=row.relative_start_ms,
        relative_end_ms=row.relative_end_ms,
        segment_sequence=row.segment_sequence,
        hashtags=row.hashtags,
        words=row.words,
        camera=row.camera,
        media_available=bool(row.storage_key),
        created_at=row.created_at,
    )


@router.get("/highlights", response_model=HighlightList)
async def list_highlights(
    principal: CurrentPrincipal,
    ctx: Ctx,
    stream_session_id: uuid.UUID | None = Query(default=None),
) -> HighlightList:
    async with ctx.db.tenant_tx(principal.tenant) as session:
        items = await highlights_service.list_highlights(
            session,
            principal.organization_id,
            stream_session_id=stream_session_id,
        )
    return HighlightList(items=[_out(item) for item in items])


@router.get("/highlights/{highlight_id}", response_model=HighlightOut)
async def get_highlight(
    highlight_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx
) -> HighlightOut:
    async with ctx.db.tenant_tx(principal.tenant) as session:
        row = await highlights_service.get_highlight(
            session, principal.organization_id, highlight_id
        )
    return _out(row)


@router.get("/highlights/{highlight_id}/media-url", response_model=UrlResponse)
async def highlight_media_url(
    highlight_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx
) -> UrlResponse:
    return UrlResponse(url=await highlights_service.segment_media_url(ctx, principal, highlight_id))
