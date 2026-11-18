"""Ingest control plane: STREAMCLIP stream keys, live sessions, MediaMTX hooks.

Platform stream keys (Twitch, YouTube, Kick) are never requested or stored.
Only an HMAC of the STREAMCLIP secret is kept; the clear value is shown once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.ids import uuid7
from app.models.enums import (
    ConnectionStatus,
    IngestProtocol,
    StreamEndReason,
    StreamKeyStatus,
    StreamSessionStatus,
)
from app.models.media import StreamConnection, StreamKey, StreamSession
from app.services import entitlements
from app.services.audit import RequestMeta, audit

OPEN_SESSION_STATUSES = frozenset(
    {
        StreamSessionStatus.PENDING,
        StreamSessionStatus.LIVE,
        StreamSessionStatus.INTERRUPTED,
        StreamSessionStatus.FINALIZING,
    }
)

# Segments land about every 5 min. After ~2 missed segments with no media tick
# (and no publisher_disconnect hook), treat the live as gone — covers abrupt
# OBS quits where MediaMTX never delivered runOnNotReady.
STALE_MEDIA_AFTER = timedelta(minutes=12)

_SECRET_PREFIX = "sc_live_"  # noqa: S105 - public prefix, not a credential
_PUBLIC_ID_BYTES = 9  # 12 char urlsafe


def hash_stream_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_stream_secret() -> str:
    return _SECRET_PREFIX + secrets.token_urlsafe(32)


def generate_public_id() -> str:
    return secrets.token_urlsafe(_PUBLIC_ID_BYTES)[:16]


def parse_obs_key(raw: str) -> tuple[str, str] | None:
    """OBS stream key format: `{public_id}/{secret}`."""
    public_id, sep, secret = raw.strip().partition("/")
    if not sep or not public_id or not secret.startswith(_SECRET_PREFIX):
        return None
    return public_id, secret


@dataclass(frozen=True, slots=True)
class IngestEndpoints:
    ingest_api_url: str
    rtmps_url: str | None
    srt_url: str | None
    stream_key: str | None
    online: bool


def endpoints_for(
    settings: Settings,
    *,
    public_id: str,
    secret: str | None,
    instance_rtmp_url: str | None = None,
) -> IngestEndpoints:
    """Values shown in the product UI / OBS.

    RTMP URL   = this live's own spot (`rtmp://<ip>:1935/live`). Empty until that
    instance is up. The shared edge is not an OBS server.
    Stream Key = {public_id}/{secret}  (shown once).
    """
    from app.services.ingest_nodes import ingest_api_url

    stream_key = f"{public_id}/{secret}" if secret else None
    srt: str | None = None
    host = (settings.ingest_public_host or "").strip() or None
    if secret and host:
        srt = settings.ingest_srt_url or (
            f"srt://{host}:8890?streamid=publish:live/{public_id}:{secret}"
        )
        if "{public_id}" in srt:
            srt = srt.format(public_id=public_id, secret=secret)
    return IngestEndpoints(
        ingest_api_url=ingest_api_url(settings),
        rtmps_url=(instance_rtmp_url or None),
        srt_url=srt,
        stream_key=stream_key,
        online=settings.ingest_online,
    )


async def get_active_key(session: AsyncSession, organization_id: uuid.UUID) -> StreamKey | None:
    return (
        await session.execute(
            select(StreamKey).where(
                StreamKey.organization_id == organization_id,
                StreamKey.status == StreamKeyStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()


async def create_or_rotate_key(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    label: str = "",
    meta: RequestMeta | None = None,
) -> tuple[StreamKey, str]:
    """Revoke any active key and issue a new one. Returns (row, clear_secret)."""
    now = datetime.now(UTC)
    existing = await get_active_key(session, organization_id)
    if existing is not None:
        existing.status = StreamKeyStatus.REVOKED
        existing.revoked_at = now
        await session.flush()

    clear = generate_stream_secret()
    key = StreamKey(
        id=uuid7(),
        organization_id=organization_id,
        public_id=generate_public_id(),
        key_hash=hash_stream_secret(clear),
        key_hint=clear[-4:],
        label=(label or "").strip()[:80],
        status=StreamKeyStatus.ACTIVE,
        created_by_user_id=user_id,
    )
    session.add(key)
    await session.flush()
    if meta is not None:
        audit(
            session,
            "ingest.key_issued",
            meta=meta,
            actor_user_id=user_id,
            organization_id=organization_id,
            details={"public_id": key.public_id, "rotated": existing is not None},
        )
    return key, clear


async def revoke_active_key(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    meta: RequestMeta | None = None,
) -> bool:
    key = await get_active_key(session, organization_id)
    if key is None:
        return False
    key.status = StreamKeyStatus.REVOKED
    key.revoked_at = datetime.now(UTC)
    await session.flush()
    if meta is not None:
        audit(
            session,
            "ingest.key_revoked",
            meta=meta,
            actor_user_id=user_id,
            organization_id=organization_id,
            details={"public_id": key.public_id},
        )
    return True


async def find_key_by_public_id(session: AsyncSession, public_id: str) -> StreamKey | None:
    return (
        await session.execute(
            select(StreamKey).where(
                StreamKey.public_id == public_id, StreamKey.status == StreamKeyStatus.ACTIVE
            )
        )
    ).scalar_one_or_none()


async def authenticate_publisher(
    session: AsyncSession, *, public_id: str, secret: str
) -> StreamKey:
    key = await find_key_by_public_id(session, public_id)
    if key is None or not hmac.compare_digest(key.key_hash, hash_stream_secret(secret)):
        raise PermissionDeniedError("Clé d'ingestion invalide.", code="invalid_stream_key")
    return key


async def count_open_sessions(session: AsyncSession, organization_id: uuid.UUID) -> int:
    rows = (
        await session.execute(
            select(StreamSession.id).where(
                StreamSession.organization_id == organization_id,
                StreamSession.status.in_(tuple(OPEN_SESSION_STATUSES)),
            )
        )
    ).all()
    return len(rows)


async def open_session_for_publish(
    session: AsyncSession,
    *,
    key: StreamKey,
    protocol: IngestProtocol,
    remote_ip: str | None,
    ingest_node_id: uuid.UUID | None = None,
) -> StreamSession:
    """Start (or resume) a live session when MediaMTX accepts a publisher."""
    entitlement = await entitlements.get_entitlement(session, key.organization_id)
    if entitlement.quota.exhausted:
        raise PermissionDeniedError(
            "Quota mensuel épuisé : le traitement des lives est suspendu.",
            code="quota_exhausted",
        )

    now = datetime.now(UTC)
    key.last_used_at = now

    existing = (
        await session.execute(
            select(StreamSession)
            .where(
                StreamSession.organization_id == key.organization_id,
                StreamSession.stream_key_id == key.id,
                StreamSession.status.in_(tuple(OPEN_SESSION_STATUSES)),
            )
            .order_by(StreamSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    # A second live on another spot must not reuse the session already bound
    # to a different instance.
    if (
        existing is not None
        and ingest_node_id is not None
        and existing.ingest_node_id is not None
        and existing.ingest_node_id != ingest_node_id
    ):
        existing = None
    if existing is not None:
        existing.status = StreamSessionStatus.LIVE
        existing.protocol = protocol
        existing.last_media_at = now
        if existing.ingest_node_id is None and ingest_node_id is not None:
            existing.ingest_node_id = ingest_node_id
        session.add(
            StreamConnection(
                id=uuid7(),
                organization_id=key.organization_id,
                stream_session_id=existing.id,
                protocol=protocol,
                status=ConnectionStatus.ACTIVE,
                remote_ip=remote_ip,
                connected_at=now,
                media_offset_ms=existing.media_duration_ms,
            )
        )
        await session.flush()
        return existing

    open_count = await count_open_sessions(session, key.organization_id)
    if open_count >= entitlement.plan.max_concurrent_streams:
        raise ConflictError(
            "Un live est déjà en cours pour cet espace.",
            code="concurrent_stream_limit",
        )

    stream = StreamSession(
        id=uuid7(),
        organization_id=key.organization_id,
        stream_key_id=key.id,
        ingest_node_id=ingest_node_id,
        status=StreamSessionStatus.LIVE,
        protocol=protocol,
        started_at=now,
        last_media_at=now,
    )
    session.add(stream)
    await session.flush()
    session.add(
        StreamConnection(
            id=uuid7(),
            organization_id=key.organization_id,
            stream_session_id=stream.id,
            protocol=protocol,
            status=ConnectionStatus.ACTIVE,
            remote_ip=remote_ip,
            connected_at=now,
            media_offset_ms=0,
        )
    )
    await session.flush()
    return stream


async def ensure_session_for_publisher(
    session: AsyncSession,
    *,
    key: StreamKey,
    protocol: IngestProtocol,
    remote_ip: str | None,
    ingest_node_id: uuid.UUID | None = None,
) -> tuple[StreamSession, bool]:
    """Return the open session for this key, creating one when the publisher is still connected.

    A quota close or a missed disconnect can end the session while OBS stays
    on the edge. The dashboard only treats an open session as "en direct", so
    the next relay poll or publisher_ready must open a new one.
    """
    existing = (
        await session.execute(
            select(StreamSession)
            .where(
                StreamSession.organization_id == key.organization_id,
                StreamSession.stream_key_id == key.id,
                StreamSession.status.in_(tuple(OPEN_SESSION_STATUSES)),
            )
            .order_by(StreamSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if ingest_node_id is not None and existing.ingest_node_id is None:
            existing.ingest_node_id = ingest_node_id
        if existing.status is StreamSessionStatus.INTERRUPTED:
            await resume_session(session, existing)
        else:
            await session.flush()
        return existing, False

    created = await open_session_for_publish(
        session,
        key=key,
        protocol=protocol,
        remote_ip=remote_ip,
        ingest_node_id=ingest_node_id,
    )
    return created, True


async def interrupt_session(
    session: AsyncSession,
    stream: StreamSession,
    *,
    reason: StreamEndReason = StreamEndReason.PUBLISHER_ENDED,
) -> StreamSession:
    """Mark a brief publisher drop without completing the live.

    MediaMTX can fire runOnNotReady on encoder stalls / RTMP flaps while OBS
    is still live and the dedicated agent stays up. Keep the session open so
    the next publisher_ready / segment can resume billing & analysis.
    """
    if stream.status not in OPEN_SESSION_STATUSES:
        return stream
    now = datetime.now(UTC)
    stream.status = StreamSessionStatus.INTERRUPTED
    stream.end_reason = None
    stream.ended_at = None
    stream.error_code = None
    stream.error_message = None
    connections = (
        await session.execute(
            select(StreamConnection).where(
                StreamConnection.stream_session_id == stream.id,
                StreamConnection.status == ConnectionStatus.ACTIVE,
            )
        )
    ).scalars()
    for connection in connections:
        connection.status = ConnectionStatus.CLOSED
        connection.disconnected_at = now
        connection.disconnect_reason = reason.value
    await session.flush()
    return stream


async def resume_session(session: AsyncSession, stream: StreamSession) -> StreamSession:
    """Re-open an interrupted live when the publisher or a segment returns."""
    if stream.status is StreamSessionStatus.INTERRUPTED:
        stream.status = StreamSessionStatus.LIVE
        stream.end_reason = None
        stream.ended_at = None
        stream.last_media_at = datetime.now(UTC)
        await session.flush()
    return stream


async def close_session(
    session: AsyncSession,
    stream: StreamSession,
    *,
    reason: StreamEndReason,
    error_code: str | None = None,
    error_message: str | None = None,
) -> StreamSession:
    if stream.status not in OPEN_SESSION_STATUSES:
        return stream
    now = datetime.now(UTC)
    stream.status = (
        StreamSessionStatus.FAILED
        if reason is StreamEndReason.ERROR
        else StreamSessionStatus.COMPLETED
    )
    stream.end_reason = reason
    stream.ended_at = now
    stream.error_code = error_code
    stream.error_message = error_message
    connections = (
        await session.execute(
            select(StreamConnection).where(
                StreamConnection.stream_session_id == stream.id,
                StreamConnection.status == ConnectionStatus.ACTIVE,
            )
        )
    ).scalars()
    for connection in connections:
        connection.status = ConnectionStatus.CLOSED
        connection.disconnected_at = now
        connection.disconnect_reason = reason.value
    await session.flush()
    return stream


async def close_stale_sessions(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID | None = None,
    older_than: timedelta = STALE_MEDIA_AFTER,
) -> list[StreamSession]:
    """Close open sessions with no media for `older_than` (missed disconnect)."""
    cutoff = datetime.now(UTC) - older_than
    last_activity = func.coalesce(
        StreamSession.last_media_at, StreamSession.started_at, StreamSession.created_at
    )
    statement = select(StreamSession).where(
        StreamSession.status.in_(tuple(OPEN_SESSION_STATUSES)),
        last_activity < cutoff,
    )
    if organization_id is not None:
        statement = statement.where(StreamSession.organization_id == organization_id)
    stale = list((await session.execute(statement)).scalars().all())
    closed: list[StreamSession] = []
    for stream in stale:
        closed.append(
            await close_session(session, stream, reason=StreamEndReason.SIGNAL_LOST)
        )
    return closed


async def record_processed_tick(
    session: AsyncSession,
    stream: StreamSession,
    *,
    processed_ms: int,
    media_end_ms: int | None = None,
    idempotency_key: str | None = None,
) -> entitlements.QuotaSnapshot:
    """Charge analyzed media time and stop once the plan threshold is reached."""
    entitlement = await entitlements.get_entitlement(session, stream.organization_id)
    bill = min(processed_ms, entitlement.quota.remaining_ms)
    if bill <= 0 or entitlement.quota.exhausted:
        if entitlement.quota.exhausted and stream.status in OPEN_SESSION_STATUSES:
            await close_session(session, stream, reason=StreamEndReason.QUOTA_EXHAUSTED)
        return entitlement.quota
    previous = stream.processed_ms
    stream.processed_ms = previous + bill
    if media_end_ms is not None:
        stream.media_duration_ms = max(stream.media_duration_ms, media_end_ms)
    stream.last_media_at = datetime.now(UTC)
    await session.flush()
    snapshot = await entitlements.record_usage(
        session,
        organization_id=stream.organization_id,
        quantity_ms=bill,
        idempotency_key=idempotency_key
        or f"session:{stream.id}:analyzed:{previous}:{bill}",
        stream_session_id=stream.id,
        media_start_ms=previous,
        media_end_ms=previous + bill,
    )
    # Open analysis windows for each completed ~5 min slice of processed media.
    from app.services import analysis as analysis_service

    await analysis_service.schedule_windows_for_progress(
        session,
        stream,
        previous_processed_ms=previous,
        current_processed_ms=stream.processed_ms,
    )
    if snapshot.exhausted and stream.status in OPEN_SESSION_STATUSES:
        await close_session(session, stream, reason=StreamEndReason.QUOTA_EXHAUSTED)
    return snapshot


async def get_session_for_org(
    session: AsyncSession, organization_id: uuid.UUID, session_id: uuid.UUID
) -> StreamSession:
    stream = (
        await session.execute(
            select(StreamSession).where(
                StreamSession.id == session_id,
                StreamSession.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    if stream is None:
        raise NotFoundError("Live introuvable.", code="stream_not_found")
    return stream


async def list_recent_sessions(
    session: AsyncSession, organization_id: uuid.UUID, *, limit: int = 20
) -> list[StreamSession]:
    result = await session.execute(
        select(StreamSession)
        .where(StreamSession.organization_id == organization_id)
        .order_by(StreamSession.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())
