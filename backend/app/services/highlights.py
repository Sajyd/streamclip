"""List viral highlight candidates for the Remotion player."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.models.analysis import HighlightCandidate
from app.models.enums import CandidateStatus
from app.services.auth import Principal


@dataclass(frozen=True)
class HighlightRow:
    id: uuid.UUID
    stream_session_id: uuid.UUID
    title: str
    description: str
    category: str
    score: Decimal
    start_ms: int
    end_ms: int
    relative_start_ms: int
    relative_end_ms: int
    segment_sequence: int
    storage_key: str | None
    hashtags: list[str]
    words: list[dict[str, Any]]
    camera: dict[str, Any]
    created_at: datetime


def _row(candidate: HighlightCandidate) -> HighlightRow:
    breakdown = candidate.score_breakdown or {}
    verification = candidate.verification or {}
    camera = verification.get("camera") or {"detected": False, "x": 960, "y": 200}
    return HighlightRow(
        id=candidate.id,
        stream_session_id=candidate.stream_session_id,
        title=candidate.title,
        description=candidate.summary,
        category=candidate.category.value,
        score=candidate.score,
        start_ms=candidate.start_ms,
        end_ms=candidate.end_ms,
        relative_start_ms=int(breakdown.get("relative_start_ms") or 0),
        relative_end_ms=int(
            breakdown.get("relative_end_ms") or (candidate.end_ms - candidate.start_ms)
        ),
        segment_sequence=int(breakdown.get("segment_sequence") or 0),
        storage_key=breakdown.get("storage_key"),
        hashtags=list(breakdown.get("hashtags") or []),
        words=list(breakdown.get("words") or []),
        camera={
            "detected": bool(camera.get("detected")),
            "x": int(camera.get("x") or 960),
            "y": int(camera.get("y") or 200),
        },
        created_at=candidate.created_at,
    )


async def list_highlights(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    stream_session_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[HighlightRow]:
    query = (
        select(HighlightCandidate)
        .where(
            HighlightCandidate.organization_id == organization_id,
            HighlightCandidate.status != CandidateStatus.SUPERSEDED,
        )
        .order_by(HighlightCandidate.score.desc(), HighlightCandidate.created_at.desc())
        .limit(limit)
    )
    if stream_session_id is not None:
        query = query.where(HighlightCandidate.stream_session_id == stream_session_id)
    rows = (await session.execute(query)).scalars().all()
    return [_row(c) for c in rows]


async def get_highlight(
    session: AsyncSession, organization_id: uuid.UUID, highlight_id: uuid.UUID
) -> HighlightRow:
    candidate = (
        await session.execute(
            select(HighlightCandidate).where(
                HighlightCandidate.id == highlight_id,
                HighlightCandidate.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise NotFoundError("Highlight introuvable.", code="highlight_not_found")
    return _row(candidate)


async def segment_media_url(
    ctx: AppContext, principal: Principal, highlight_id: uuid.UUID
) -> str:
    if ctx.storage is None:
        raise ServiceUnavailableError("Stockage indisponible.", code="storage_unavailable")
    async with ctx.db.tenant_tx(principal.tenant) as session:
        row = await get_highlight(session, principal.organization_id, highlight_id)
    if not row.storage_key:
        raise NotFoundError("Extrait vidéo introuvable.", code="segment_not_found")
    return await ctx.storage.presigned_download_url(
        row.storage_key, expires_seconds=600, filename=f"segment-{row.segment_sequence:04d}.mp4"
    )
