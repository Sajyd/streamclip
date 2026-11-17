"""Clip library: list ready clips and issue short-lived download URLs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.models.clips import Clip, ClipVersion, StorageAsset
from app.models.enums import AssetStatus, ClipStatus, ClipVersionStatus
from app.services.auth import Principal


@dataclass(frozen=True)
class ClipRow:
    id: uuid.UUID
    title: str
    description: str
    status: str
    category: str
    score: Decimal
    start_ms: int
    end_ms: int
    duration_ms: int | None
    is_favorite: bool
    thumbnail_available: bool
    download_available: bool
    created_at: datetime
    stream_session_id: uuid.UUID | None


async def list_clips(
    session: AsyncSession, organization_id: uuid.UUID, *, limit: int = 50
) -> list[ClipRow]:
    clips = (
        await session.execute(
            select(Clip)
            .where(Clip.organization_id == organization_id, Clip.deleted_at.is_(None))
            .order_by(Clip.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    if not clips:
        return []

    version_ids = [c.current_version_id for c in clips if c.current_version_id]
    versions: dict[uuid.UUID, ClipVersion] = {}
    if version_ids:
        for version in (
            await session.execute(select(ClipVersion).where(ClipVersion.id.in_(version_ids)))
        ).scalars():
            versions[version.id] = version

    asset_ids = [
        vid
        for version in versions.values()
        for vid in (version.video_asset_id, version.thumbnail_asset_id)
        if vid
    ]
    assets: dict[uuid.UUID, StorageAsset] = {}
    if asset_ids:
        for asset in (
            await session.execute(select(StorageAsset).where(StorageAsset.id.in_(asset_ids)))
        ).scalars():
            assets[asset.id] = asset

    rows: list[ClipRow] = []
    for clip in clips:
        version = versions.get(clip.current_version_id) if clip.current_version_id else None
        video = assets.get(version.video_asset_id) if version and version.video_asset_id else None
        thumb_id = version.thumbnail_asset_id if version else None
        thumb = assets.get(thumb_id) if thumb_id else None
        download_available = bool(
            clip.status is ClipStatus.READY
            and version is not None
            and version.status is ClipVersionStatus.READY
            and video is not None
            and video.status is AssetStatus.AVAILABLE
        )
        rows.append(
            ClipRow(
                id=clip.id,
                title=clip.title,
                description=clip.description,
                status=clip.status.value,
                category=clip.category.value,
                score=clip.score,
                start_ms=clip.start_ms,
                end_ms=clip.end_ms,
                duration_ms=version.duration_ms if version else (clip.end_ms - clip.start_ms),
                is_favorite=clip.is_favorite,
                thumbnail_available=bool(
                    thumb is not None and thumb.status is AssetStatus.AVAILABLE
                ),
                download_available=download_available,
                created_at=clip.created_at,
                stream_session_id=clip.stream_session_id,
            )
        )
    return rows


async def download_url(ctx: AppContext, principal: Principal, clip_id: uuid.UUID) -> str:
    if ctx.storage is None:
        raise ServiceUnavailableError(
            "Le stockage des clips n'est pas disponible.", code="storage_unavailable"
        )
    async with ctx.db.tenant_tx(principal.tenant) as session:
        clip = (
            await session.execute(
                select(Clip).where(
                    Clip.id == clip_id,
                    Clip.organization_id == principal.organization_id,
                    Clip.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if clip is None or clip.current_version_id is None:
            raise NotFoundError("Clip introuvable.", code="clip_not_found")
        version = await session.get(ClipVersion, clip.current_version_id)
        if (
            version is None
            or version.video_asset_id is None
            or version.status is not ClipVersionStatus.READY
        ):
            raise NotFoundError(
                "Ce clip n'est pas encore prêt au téléchargement.",
                code="clip_not_ready",
            )
        asset = await session.get(StorageAsset, version.video_asset_id)
        if asset is None or asset.status is not AssetStatus.AVAILABLE:
            raise NotFoundError("Fichier vidéo introuvable.", code="clip_asset_missing")
        key = asset.key
        filename = f"{clip.title[:60].strip() or 'clip'}.mp4"

    return await ctx.storage.presigned_download_url(key, filename=filename)
