"""Ingest keys for OBS and MediaMTX authentication / lifecycle hooks."""

from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.api.deps import Ctx, CurrentPrincipal, Meta
from app.core import release
from app.core.errors import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
)
from app.models.enums import IngestProtocol, StreamEndReason, StreamSessionStatus
from app.models.media import StreamKey, StreamSession
from app.schemas.api import (
    IngestAuthHookRequest,
    IngestEventHookRequest,
    Message,
    StreamKeyIssueRequest,
    StreamKeyOut,
    StreamSessionList,
    StreamSessionOut,
)
from app.services import ingest as ingest_service

router = APIRouter(tags=["ingest"])

_PROTOCOL_MAP = {
    "rtmp": IngestProtocol.RTMP,
    "rtmps": IngestProtocol.RTMPS,
    "srt": IngestProtocol.SRT,
}


def _require_ingest_keys() -> None:
    if not release.INGEST_KEYS_AVAILABLE:
        raise ServiceUnavailableError(
            "La gestion des clés d'ingestion n'est pas disponible.",
            code="ingest_keys_unavailable",
        )


def _key_out(
    ctx: Ctx,
    key: StreamKey,
    *,
    clear_secret: str | None = None,
) -> StreamKeyOut:
    endpoints = ingest_service.endpoints_for(
        ctx.settings, public_id=key.public_id, secret=clear_secret
    )
    # Without the clear secret we still advertise the RTMPS base path when online.
    rtmps = endpoints.rtmps_url
    srt = endpoints.srt_url
    stream_key = endpoints.stream_key
    if clear_secret is None and ctx.settings.ingest_online:
        host = ctx.settings.ingest_public_host or ""
        rtmps = ctx.settings.ingest_rtmps_url or f"rtmps://{host}:1935/live/{key.public_id}"
        if "{public_id}" in rtmps:
            rtmps = rtmps.format(public_id=key.public_id)
        srt = None  # needs the secret
        stream_key = None
    return StreamKeyOut(
        public_id=key.public_id,
        key_hint=key.key_hint,
        label=key.label,
        status=key.status.value,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        rtmps_url=rtmps,
        srt_url=srt,
        stream_key=stream_key,
        ingest_online=ctx.settings.ingest_online,
    )


def _session_out(stream: StreamSession) -> StreamSessionOut:
    return StreamSessionOut(
        id=stream.id,
        status=stream.status.value,
        end_reason=stream.end_reason.value if stream.end_reason else None,
        protocol=stream.protocol.value if stream.protocol else None,
        title=stream.title,
        started_at=stream.started_at,
        ended_at=stream.ended_at,
        media_duration_ms=stream.media_duration_ms,
        processed_ms=stream.processed_ms,
        clips_count=stream.clips_count,
        created_at=stream.created_at,
    )


def _require_hook_secret(request: Request, ctx: Ctx) -> None:
    secret = ctx.settings.ingest_hook_secret
    provided = request.headers.get("x-streamclip-ingest-secret", "")
    if (
        secret is None
        or not provided
        or not hmac.compare_digest(provided, secret.get_secret_value())
    ):
        raise AuthenticationError("Authentification requise.", code="unauthenticated")


def _public_id_from_path(path: str) -> str | None:
    # Expected: live/{public_id} or /live/{public_id}
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] == "live":
        return parts[1]
    if len(parts) == 1:
        return parts[0]
    return None


def _secret_from_hook(body: IngestAuthHookRequest) -> str | None:
    if body.password:
        return body.password
    if body.query:
        values = parse_qs(body.query.lstrip("?"))
        for key in ("pwd", "password", "secret"):
            if values.get(key):
                return values[key][0]
    return None


@router.get("/ingest/key", response_model=StreamKeyOut)
async def get_ingest_key(principal: CurrentPrincipal, ctx: Ctx) -> StreamKeyOut:
    _require_ingest_keys()
    async with ctx.db.system_tx() as session:
        key = await ingest_service.get_active_key(session, principal.organization_id)
    if key is None:
        raise NotFoundError("Aucune clé d'ingestion active.", code="stream_key_not_found")
    return _key_out(ctx, key)


@router.post(
    "/ingest/key",
    response_model=StreamKeyOut,
    status_code=status.HTTP_201_CREATED,
)
async def issue_ingest_key(
    body: StreamKeyIssueRequest,
    principal: CurrentPrincipal,
    ctx: Ctx,
    meta: Meta,
) -> StreamKeyOut:
    _require_ingest_keys()
    if not principal.can_manage_organization:
        raise PermissionDeniedError(
            "Seul un administrateur de l'espace peut créer une clé d'ingestion.",
            code="insufficient_role",
        )
    async with ctx.db.system_tx() as session:
        key, clear = await ingest_service.create_or_rotate_key(
            session,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            label=body.label,
            meta=meta,
        )
    return _key_out(ctx, key, clear_secret=clear)


@router.post(
    "/ingest/key/rotate",
    response_model=StreamKeyOut,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_ingest_key(
    body: StreamKeyIssueRequest,
    principal: CurrentPrincipal,
    ctx: Ctx,
    meta: Meta,
) -> StreamKeyOut:
    return await issue_ingest_key(body, principal, ctx, meta)


@router.delete("/ingest/key", response_model=Message)
async def revoke_ingest_key(principal: CurrentPrincipal, ctx: Ctx, meta: Meta) -> Message:
    _require_ingest_keys()
    if not principal.can_manage_organization:
        raise PermissionDeniedError(
            "Seul un administrateur de l'espace peut révoquer la clé d'ingestion.",
            code="insufficient_role",
        )
    async with ctx.db.system_tx() as session:
        revoked = await ingest_service.revoke_active_key(
            session,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            meta=meta,
        )
    if not revoked:
        raise NotFoundError("Aucune clé d'ingestion active.", code="stream_key_not_found")
    return Message(message="Clé d'ingestion révoquée.")


@router.get("/ingest/sessions", response_model=StreamSessionList)
async def list_ingest_sessions(principal: CurrentPrincipal, ctx: Ctx) -> StreamSessionList:
    _require_ingest_keys()
    async with ctx.db.tenant_tx(principal.tenant) as session:
        items = await ingest_service.list_recent_sessions(session, principal.organization_id)
    return StreamSessionList(items=[_session_out(item) for item in items])


@router.post("/ingest/hooks/auth")
async def mediamtx_auth(body: IngestAuthHookRequest, request: Request, ctx: Ctx) -> Response:
    """MediaMTX calls this before accepting a publisher. 200 = allow, 401 = deny."""
    _require_hook_secret(request, ctx)
    if body.action not in ("publish", "publishs"):
        # Playback / read is not offered publicly.
        raise PermissionDeniedError("Action non autorisée.", code="ingest_action_denied")
    public_id = _public_id_from_path(body.path)
    secret = _secret_from_hook(body)
    if public_id is None or secret is None:
        raise PermissionDeniedError("Clé d'ingestion invalide.", code="invalid_stream_key")
    protocol = _PROTOCOL_MAP.get(body.protocol.lower(), IngestProtocol.RTMP)
    async with ctx.db.system_tx() as session:
        key = await ingest_service.authenticate_publisher(
            session, public_id=public_id, secret=secret
        )
        await ingest_service.open_session_for_publish(
            session, key=key, protocol=protocol, remote_ip=body.ip
        )
    return Response(status_code=200)


@router.post("/ingest/hooks/event", response_model=Message)
async def mediamtx_event(body: IngestEventHookRequest, request: Request, ctx: Ctx) -> Message:
    """Publisher disconnect / processing ticks from the ingest agent."""
    _require_hook_secret(request, ctx)
    public_id = _public_id_from_path(body.path)
    if public_id is None:
        return Message(message="ignored")
    async with ctx.db.system_tx() as session:
        key = await ingest_service.find_key_by_public_id(session, public_id)
        if key is None:
            return Message(message="ignored")
        stream = (
            await session.execute(
                select(StreamSession)
                .where(
                    StreamSession.organization_id == key.organization_id,
                    StreamSession.stream_key_id == key.id,
                    StreamSession.status.in_(
                        (
                            StreamSessionStatus.PENDING,
                            StreamSessionStatus.LIVE,
                            StreamSessionStatus.INTERRUPTED,
                            StreamSessionStatus.FINALIZING,
                        )
                    ),
                )
                .order_by(StreamSession.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if stream is None:
            return Message(message="no_open_session")
        event = body.event.lower()
        if event in ("publisher_disconnect", "end", "stop"):
            await ingest_service.close_session(
                session, stream, reason=StreamEndReason.PUBLISHER_ENDED
            )
        elif event in ("processed", "tick") and body.processed_ms:
            await ingest_service.record_processed_tick(
                session, stream, processed_ms=body.processed_ms
            )
        elif event in ("lost", "signal_lost"):
            await ingest_service.close_session(session, stream, reason=StreamEndReason.SIGNAL_LOST)
    return Message(message="ok")
