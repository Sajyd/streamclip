"""Ingest keys, resolve→dedicated RTMP instance, and MediaMTX hooks."""

from __future__ import annotations

import hmac
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.api.deps import Ctx, CurrentPrincipal, Meta, OptionalPrincipal
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
    IngestResolveOut,
    IngestResolveRequest,
    Message,
    StreamKeyIssueRequest,
    StreamKeyOut,
    StreamSessionList,
    StreamSessionOut,
)
from app.services import ingest as ingest_service
from app.services import ingest_nodes

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


async def _instance_rtmp_for_org(ctx: Ctx, organization_id) -> str | None:
    async with ctx.db.system_tx() as session:
        node = await ingest_nodes.get_dedicated_node(session, organization_id)
    if node is not None and node.status.value == "ready" and node.public_hostname:
        return ingest_nodes.rtmp_url_for_host(node.public_hostname)
    return None


def _key_out(
    ctx: Ctx,
    key: StreamKey,
    *,
    clear_secret: str | None = None,
    instance_rtmp_url: str | None = None,
) -> StreamKeyOut:
    # Clear secret only right after create/rotate (show-once).
    # ingest_api_url is always the same resolve endpoint; rtmps_url is the
    # dedicated spot's RTMP address once that instance is READY.
    endpoints = ingest_service.endpoints_for(
        ctx.settings,
        public_id=key.public_id,
        secret=clear_secret,
        instance_rtmp_url=instance_rtmp_url,
    )
    return StreamKeyOut(
        public_id=key.public_id,
        key_hint=key.key_hint,
        label=key.label,
        status=key.status.value,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        ingest_api_url=endpoints.ingest_api_url,
        rtmps_url=endpoints.rtmps_url,
        srt_url=endpoints.srt_url,
        stream_key=endpoints.stream_key,
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
    # Expected: live/{public_id} or live/{public_id}/{secret} (OBS stream key in path)
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] == "live":
        return parts[1]
    if len(parts) == 1:
        return parts[0]
    return None


def _secret_from_path(path: str) -> str | None:
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 3 and parts[0] == "live" and parts[2].startswith("sc_live_"):
        return parts[2]
    return None


def _secret_from_hook(body: IngestAuthHookRequest) -> str | None:
    if body.password:
        return body.password
    embedded = _secret_from_path(body.path)
    if embedded:
        return embedded
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
    instance_rtmp = await _instance_rtmp_for_org(ctx, principal.organization_id)
    return _key_out(ctx, key, instance_rtmp_url=instance_rtmp)


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
    instance_rtmp = await _instance_rtmp_for_org(ctx, principal.organization_id)
    return _key_out(ctx, key, clear_secret=clear, instance_rtmp_url=instance_rtmp)


@router.post("/ingest/resolve", response_model=None)
async def resolve_ingest_post(
    ctx: Ctx,
    principal: OptionalPrincipal,
    body: IngestResolveRequest | None = None,
) -> Response:
    """Resolve → dedicated RTMP instance.

    Prefer the logged-in org (no secret re-entry). Alternatively pass
    `stream_key` for unauthenticated resolve/redirect clients.
    """
    return await _resolve(ctx, body=body, principal=principal, redirect=False)


@router.get("/ingest/resolve", response_model=None)
async def resolve_ingest_get(
    ctx: Ctx,
    stream_key: Annotated[str | None, Query(min_length=16, max_length=256)] = None,
    redirect: bool = True,
) -> Response:
    """GET with stream_key: optional 302 to rtmp:// when the spot is ready."""
    body = IngestResolveRequest(stream_key=stream_key) if stream_key else None
    return await _resolve(ctx, body=body, principal=None, redirect=redirect)


async def _resolve(
    ctx: Ctx,
    *,
    body: IngestResolveRequest | None,
    principal: OptionalPrincipal | None,
    redirect: bool,
) -> Response:
    from app.services.auth import Principal

    _require_ingest_keys()
    if body and body.stream_key:
        parsed = ingest_service.parse_obs_key(body.stream_key)
        if parsed is None:
            raise PermissionDeniedError("Clé d'ingestion invalide.", code="invalid_stream_key")
        public_id, secret = parsed
        async with ctx.db.system_tx() as session:
            key = await ingest_service.authenticate_publisher(
                session, public_id=public_id, secret=secret
            )
            result = await ingest_nodes.resolve_for_organization(
                session, ctx.settings, organization_id=key.organization_id
            )
    elif isinstance(principal, Principal):
        async with ctx.db.system_tx() as session:
            active = await ingest_service.get_active_key(session, principal.organization_id)
            if active is None:
                raise NotFoundError("Aucune clé d'ingestion active.", code="stream_key_not_found")
            result = await ingest_nodes.resolve_for_organization(
                session, ctx.settings, organization_id=principal.organization_id
            )
    else:
        raise AuthenticationError(
            "Fournissez la clé de stream ou connectez-vous.",
            code="unauthenticated",
        )

    payload = IngestResolveOut(
        status=result.status,
        ingest_api_url=result.ingest_api_url,
        rtmp_url=result.rtmp_url,
        analysis_url=result.analysis_url,
        public_hostname=result.public_hostname,
        message=result.message,
    )
    if redirect and result.status == "ready" and result.rtmp_url:
        return RedirectResponse(url=result.rtmp_url, status_code=status.HTTP_302_FOUND)
    code = status.HTTP_202_ACCEPTED if result.status == "starting" else status.HTTP_200_OK
    return JSONResponse(status_code=code, content=payload.model_dump(mode="json"))


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
        # Publisher reached MediaMTX: ensure dedicated node row and bind session.
        node = await ingest_nodes.ensure_dedicated_node(
            session, ctx.settings, organization_id=key.organization_id
        )
        stream = await ingest_service.open_session_for_publish(
            session, key=key, protocol=protocol, remote_ip=body.ip
        )
        if stream.ingest_node_id is None:
            stream.ingest_node_id = node.id
            await session.flush()
    return Response(status_code=200)


@router.post("/ingest/hooks/event", response_model=Message)
async def mediamtx_event(body: IngestEventHookRequest, request: Request, ctx: Ctx) -> Message:
    """Publisher disconnect / processing ticks from the ingest agent."""
    _require_hook_secret(request, ctx)
    public_id = _public_id_from_path(body.path)
    if public_id is None:
        return Message(message="ignored")
    queued_transcription = False
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
            queued_transcription = True
        elif event in ("lost", "signal_lost"):
            await ingest_service.close_session(session, stream, reason=StreamEndReason.SIGNAL_LOST)
    if queued_transcription:
        # Serverless: run newly queued analysis tasks before the response returns.
        from app.tasks.queue import run_due_tasks

        await run_due_tasks(
            ctx,
            worker=f"ingest-{getattr(request.state, 'request_id', 'hook')}",
            queues=["analysis"],
            kinds=["analysis.transcribe"],
            max_tasks=4,
            time_budget_seconds=20.0,
        )
    return Message(message="ok")
