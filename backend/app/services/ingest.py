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
from datetime import UTC, datetime

from sqlalchemy import select
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
    rtmps_url: str | None
    srt_url: str | None
    stream_key: str | None
    online: bool


def endpoints_for(settings: Settings, *, public_id: str, secret: str | None) -> IngestEndpoints:
    host = (settings.ingest_public_host or "").strip() or None
    if host is None or secret is None:
        return IngestEndpoints(rtmps_url=None, srt_url=None, stream_key=None, online=False)
    rtmps = settings.ingest_rtmps_url or f"rtmps://{host}:1935/live/{public_id}"
    if "{public_id}" in rtmps:
        rtmps = rtmps.format(public_id=public_id)
    srt = settings.ingest_srt_url or (
        f"srt://{host}:8890?streamid=publish:live/{public_id}:{secret}"
    )
    if "{public_id}" in srt:
        srt = srt.format(public_id=public_id, secret=secret)
    return IngestEndpoints(
        rtmps_url=rtmps,
        srt_url=srt,
        stream_key=f"{public_id}/{secret}",
        online=True,
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
    if existing is not None:
        existing.status = StreamSessionStatus.LIVE
        existing.protocol = protocol
        existing.last_media_at = now
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


async def record_processed_tick(
    session: AsyncSession,
    stream: StreamSession,
    *,
    processed_ms: int,
    media_end_ms: int | None = None,
) -> entitlements.QuotaSnapshot:
    """Charge processed time and stop the session if the quota is exhausted."""
    if processed_ms <= 0:
        return (await entitlements.get_entitlement(session, stream.organization_id)).quota
    previous = stream.processed_ms
    stream.processed_ms = previous + processed_ms
    if media_end_ms is not None:
        stream.media_duration_ms = max(stream.media_duration_ms, media_end_ms)
    stream.last_media_at = datetime.now(UTC)
    await session.flush()
    snapshot = await entitlements.record_usage(
        session,
        organization_id=stream.organization_id,
        quantity_ms=processed_ms,
        idempotency_key=f"session:{stream.id}:tick:{previous}:{processed_ms}",
        stream_session_id=stream.id,
        media_start_ms=previous,
        media_end_ms=previous + processed_ms,
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
