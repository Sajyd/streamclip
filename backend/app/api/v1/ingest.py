"""Ingest keys, resolve→dedicated RTMP instance, and MediaMTX hooks."""

from __future__ import annotations

import asyncio
import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import parse_qs

import structlog
from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from app.api.deps import Ctx, CurrentPrincipal, Meta, OptionalPrincipal
from app.core import release
from app.core.errors import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
)
from app.models.enums import (
    ActorType,
    AuditOutcome,
    IngestProtocol,
    StreamEndReason,
    StreamSessionStatus,
)
from app.models.media import StreamKey, StreamSession
from app.schemas.api import (
    IngestAuthHookRequest,
    IngestEventHookOut,
    IngestEventHookRequest,
    IngestRelayTargetOut,
    IngestResolveOut,
    IngestResolveRequest,
    LivePlaybackOut,
    Message,
    SegmentAnalysisHookOut,
    SegmentAnalysisHookRequest,
    StreamKeyIssueRequest,
    StreamKeyOut,
    StreamSessionList,
    StreamSessionOut,
)
from app.services import ingest as ingest_service
from app.services import ingest_nodes
from app.services import playback as playback_service
from app.services.audit import RequestMeta, audit
from app.services.rtmp_resolve_page import render_resolve_page

log = structlog.get_logger(__name__)

_DIAG_STR = {
    "empty_reason": 80,
    "transcript_preview": 280,
    "raw_preview": 1200,
    "error": 400,
    "model": 128,
    "region": 32,
    "stop_reason": 64,
    "provider": 64,
}
_DIAG_INT = (
    "transcript_chars",
    "word_count",
    "frames",
    "raw_moments",
    "kept_moments",
    "dropped_count",
    "input_tokens",
    "output_tokens",
)


def _clip_text(value: object, limit: int) -> str:
    return str(value or "").replace("\n", " ")[:limit]


def _segment_analysis_details(
    body: SegmentAnalysisHookRequest, moments: list[Any]
) -> dict[str, Any]:
    """Bounded trace written to the live pipeline log for one 5-min segment."""
    diag = body.diagnostics if isinstance(body.diagnostics, dict) else {}
    details: dict[str, Any] = {
        "sequence": body.sequence,
        "storage_key": body.storage_key,
        "size_bytes": body.size_bytes,
        "moments": len(moments),
        "highlights_written": len(moments),
        "frames": body.frames,
        "provider": body.provider,
        "model": body.model,
        "transcript_chars": len(body.transcript_text or ""),
        "word_count": len(body.transcript_words or []),
        "transcript_preview": _clip_text(body.transcript_text, 280),
    }
    if moments:
        details["moment_summaries"] = [
            {
                "title": _clip_text(getattr(m, "title", ""), 80),
                "score": getattr(m, "score", None),
                "start_ms": getattr(m, "start_ms", None),
                "end_ms": getattr(m, "end_ms", None),
                "category": getattr(m, "category", None),
            }
            for m in moments[:8]
        ]
    for key, limit in _DIAG_STR.items():
        if diag.get(key):
            details[key] = _clip_text(diag.get(key), limit)
    for key in _DIAG_INT:
        value = diag.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        details[key] = value
    dropped = diag.get("dropped")
    if isinstance(dropped, list) and dropped:
        details["dropped"] = [
            item for item in dropped[:8] if isinstance(item, dict)
        ]
    if "empty_reason" not in details:
        if moments:
            details["result"] = "highlights_written"
        elif (body.provider or "").endswith("failed"):
            details["empty_reason"] = "luna_error"
        elif body.frames <= 0:
            details["empty_reason"] = "no_frames"
        elif not (body.transcript_text or "").strip():
            details["empty_reason"] = "model_returned_no_moments"
            details["transcript"] = "empty"
        else:
            details["empty_reason"] = "model_returned_no_moments"
    elif moments:
        details["result"] = "highlights_written"
    return details


def _hook_meta(request: Request) -> RequestMeta:
    return RequestMeta(
        ip=request.client.host if request.client else None,
        request_id=getattr(request.state, "request_id", None),
    )


def _pipeline_audit(
    session,
    action: str,
    *,
    organization_id,
    stream_id,
    request: Request,
    details: dict | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
) -> None:
    audit(
        session,
        action,
        actor_type=ActorType.INGEST_NODE,
        organization_id=organization_id,
        target_type="stream_session",
        target_id=stream_id,
        outcome=outcome,
        meta=_hook_meta(request),
        details=details or {},
    )

router = APIRouter(tags=["ingest"])
# Memorable public URL mounted at app root: GET /rtmp?key=…
public_router = APIRouter(tags=["ingest"])

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
        node = await ingest_nodes.preferred_ready_node(session, organization_id)
    if node is None or node.status.value != "ready" or not node.public_hostname:
        return None
    host = node.public_hostname
    if not host.endswith(".ingest.test") and not await asyncio.to_thread(
        ingest_nodes.rtmp_port_open, host
    ):
        return None
    return ingest_nodes.rtmp_url_for_host(host)


def _key_out(
    ctx: Ctx,
    key: StreamKey,
    *,
    clear_secret: str | None = None,
    instance_rtmp_url: str | None = None,
) -> StreamKeyOut:
    # Clear secret only right after create/rotate (show-once).
    # rtmps_url = this live's spot (rtmp://ip:1935/live), empty until it is up.
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
    if not provided:
        # MediaMTX 1.11 has no authHTTPAdditionalHeaders; secret rides on the URL.
        provided = request.query_params.get("ingest_secret", "")
    if (
        secret is None
        or not provided
        or not hmac.compare_digest(provided, secret.get_secret_value())
    ):
        raise AuthenticationError("Authentification requise.", code="unauthenticated")


def _public_id_from_path(path: str) -> str | None:
    # Expected: live/{public_id} or live/{public_id}/{secret} (OBS stream key in path)
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] == "live" and parts[1] != "live":
        return parts[1]
    if len(parts) == 1 and parts[0] not in ("live", "all_others"):
        return parts[0]
    return None


def _secret_from_path(path: str) -> str | None:
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 3 and parts[0] == "live" and parts[2].startswith("sc_live_"):
        return parts[2]
    if len(parts) >= 2 and parts[1].startswith("sc_live_"):
        return parts[1]
    return None


def _secret_from_hook(body: IngestAuthHookRequest) -> str | None:
    # Password / user may be the bare secret or the full OBS key public_id/sc_live_…
    for raw in (body.password, body.user):
        if not raw:
            continue
        parsed = ingest_service.parse_obs_key(raw)
        if parsed:
            return parsed[1]
        if raw.startswith("sc_live_"):
            return raw
        return raw
    embedded = _secret_from_path(body.path)
    if embedded:
        return embedded
    if body.query:
        values = parse_qs(body.query.lstrip("?"))
        for key in ("pwd", "password", "secret", "key"):
            if values.get(key):
                candidate = values[key][0]
                parsed = ingest_service.parse_obs_key(candidate)
                return parsed[1] if parsed else candidate
    return None


def _public_id_from_hook(body: IngestAuthHookRequest) -> str | None:
    for raw in (body.password, body.user):
        if not raw:
            continue
        parsed = ingest_service.parse_obs_key(raw)
        if parsed:
            return parsed[0]
    return _public_id_from_path(body.path)


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


@public_router.get("/rtmp", response_model=None)
async def rtmp_resolve(
    request: Request,
    ctx: Ctx,
    key: Annotated[str, Query(min_length=16, max_length=256, description="Stream key")],
    redirect: Annotated[bool, Query()] = False,
) -> Response:
    """Memorable resolve: secret → quota → start unique spot → RTMP dédié.

    Browsers get an HTML page (auto-refresh while starting). OBS cannot use
    this HTTP URL as Server — after ready, copy the shown rtmp:// host.
    Pass redirect=1 for a 302 to rtmp:// when ready.
    """
    wants_html = "text/html" in (request.headers.get("accept") or "").lower()
    return await _resolve(
        ctx,
        stream_key=key,
        organization_id=None,
        redirect=redirect,
        html=wants_html and not redirect,
    )


@router.post("/ingest/resolve", response_model=None)
async def resolve_ingest_post(
    ctx: Ctx,
    principal: OptionalPrincipal,
    body: IngestResolveRequest | None = None,
) -> Response:
    """Dashboard helper: start the logged-in org's spot (JSON, no redirect)."""
    from app.services.auth import Principal

    org_id = principal.organization_id if isinstance(principal, Principal) else None
    stream_key = body.stream_key if body else None
    new_server = bool(body.new_server) if body else False
    return await _resolve(
        ctx,
        stream_key=stream_key,
        organization_id=org_id,
        redirect=False,
        new_server=new_server,
    )


@router.get("/ingest/resolve", response_model=None)
async def resolve_ingest_get(
    ctx: Ctx,
    key: Annotated[str | None, Query(min_length=16, max_length=256)] = None,
    stream_key: Annotated[str | None, Query(min_length=16, max_length=256)] = None,
) -> Response:
    """Alias of GET /rtmp (prefer /rtmp)."""
    secret = key or stream_key
    if not secret:
        raise AuthenticationError("Paramètre key requis.", code="unauthenticated")
    return await _resolve(ctx, stream_key=secret, organization_id=None, redirect=True)


async def _resolve(
    ctx: Ctx,
    *,
    stream_key: str | None,
    organization_id,
    redirect: bool,
    html: bool = False,
    new_server: bool = False,
) -> Response:
    _require_ingest_keys()
    clear_key = stream_key
    async with ctx.db.system_tx() as session:
        if stream_key:
            parsed = ingest_service.parse_obs_key(stream_key)
            if parsed is None:
                raise PermissionDeniedError(
                    "Clé d'ingestion invalide.", code="invalid_stream_key"
                )
            public_id, secret = parsed
            key = await ingest_service.authenticate_publisher(
                session, public_id=public_id, secret=secret
            )
            org_id = key.organization_id
        elif organization_id is not None:
            active = await ingest_service.get_active_key(session, organization_id)
            if active is None:
                raise NotFoundError(
                    "Aucune clé d'ingestion active.", code="stream_key_not_found"
                )
            org_id = organization_id
        else:
            raise AuthenticationError(
                "Fournissez la clé (?key=) ou connectez-vous.",
                code="unauthenticated",
            )
        result = await ingest_nodes.resolve_for_organization(
            session, ctx.settings, organization_id=org_id, new_server=new_server
        )

    payload = IngestResolveOut(
        status=result.status,
        ingest_api_url=result.ingest_api_url,
        rtmp_url=result.rtmp_url,
        analysis_url=result.analysis_url,
        public_hostname=result.public_hostname,
        message=result.message,
    )
    resolve_link = result.ingest_api_url
    if clear_key:
        from urllib.parse import quote

        resolve_link = f"{result.ingest_api_url}?key={quote(clear_key, safe='')}"

    if redirect and result.status == "ready" and result.rtmp_url:
        return RedirectResponse(url=result.rtmp_url, status_code=status.HTTP_302_FOUND)
    if html:
        page = render_resolve_page(
            status=result.status,
            message=result.message,
            rtmp_url=result.rtmp_url if result.status == "ready" else None,
            stream_key=clear_key,
            resolve_url=resolve_link,
            edge_rtmp_url=ctx.settings.edge_rtmp_url,
        )
        code = status.HTTP_202_ACCEPTED if result.status == "starting" else status.HTTP_200_OK
        if result.status == "unavailable":
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HTMLResponse(status_code=code, content=page)
    code = status.HTTP_202_ACCEPTED if result.status == "starting" else status.HTTP_200_OK
    if result.status == "unavailable":
        code = status.HTTP_503_SERVICE_UNAVAILABLE
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
    # system_tx: closing sessions writes status (tenant app role is read-only).
    async with ctx.db.system_tx() as session:
        stale = await ingest_service.close_stale_sessions(
            session, organization_id=principal.organization_id
        )
        if stale:
            await ingest_nodes.schedule_idle_termination(
                session, organization_id=principal.organization_id
            )
        items = await ingest_service.list_recent_sessions(session, principal.organization_id)
    return StreamSessionList(items=[_session_out(item) for item in items])


@router.get("/ingest/playback", response_model=LivePlaybackOut)
async def get_live_playback(principal: CurrentPrincipal, ctx: Ctx) -> LivePlaybackOut:
    """Live preview metadata — session auth only, no OBS stream secret."""
    _require_ingest_keys()
    info = await playback_service.playback_for_principal(ctx, principal)
    return LivePlaybackOut(**playback_service.info_to_dict(info, ctx.settings))


@router.get("/ingest/playback/hls/{file_path:path}")
async def proxy_live_hls(
    file_path: str, principal: CurrentPrincipal, ctx: Ctx
) -> Response:
    """Authenticated HLS proxy for the org's live (session → dedicated agent)."""
    _require_ingest_keys()
    if not file_path or ".." in file_path:
        raise NotFoundError("Segment introuvable.", code="preview_not_found")
    info = await playback_service.playback_for_principal(ctx, principal)
    body, content_type = await playback_service.proxy_hls(ctx, info, file_path=file_path)
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )


def _is_loopback(ip: str | None) -> bool:
    if not ip:
        return False
    return ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("127.")


@router.post("/ingest/hooks/auth")
def _caller_ip(request: Request) -> str | None:
    state_ip = getattr(request.state, "client_ip", None)
    if isinstance(state_ip, str) and state_ip:
        return state_ip
    return request.client.host if request.client else None


async def mediamtx_auth(body: IngestAuthHookRequest, request: Request, ctx: Ctx) -> Response:
    """Spot MediaMTX auth: the publisher must hit that live's own IP.

    The shared edge is not an ingest target. OBS uses rtmp://<spot-ip>:1935/live.
    """
    _require_hook_secret(request, ctx)
    if body.action not in ("publish", "publishs"):
        # Readers never need the user's OBS secret:
        # - loopback: local ffmpeg / agent HLS
        # - preview token: short-lived HMAC from the API (dashboard/admin)
        # - legacy allow when IP omitted (on-box relay)
        if _is_loopback(body.ip):
            return Response(status_code=200)
        public_id = _public_id_from_hook(body)
        token = None
        if body.query:
            values = parse_qs(body.query.lstrip("?"))
            token = (values.get("token") or [None])[0]
        if public_id and token and playback_service.verify_preview_token(
            ctx.settings, token, public_id=public_id
        ):
            return Response(status_code=200)
        return Response(status_code=200)
    public_id = _public_id_from_hook(body)
    secret = _secret_from_hook(body)
    if public_id is None or secret is None:
        raise PermissionDeniedError("Clé d'ingestion invalide.", code="invalid_stream_key")
    protocol = _PROTOCOL_MAP.get(body.protocol.lower(), IngestProtocol.RTMP)
    async with ctx.db.system_tx() as session:
        key = await ingest_service.authenticate_publisher(
            session, public_id=public_id, secret=secret
        )
        await ingest_nodes.assert_can_go_live(session, key.organization_id)
        caller = _caller_ip(request)
        node = await ingest_nodes.find_node_by_hostname(session, caller)
        if node is None and ctx.settings.environment in ("test", "local"):
            node = await ingest_nodes.get_dedicated_node(session, key.organization_id)
        if node is None and ctx.settings.environment not in ("test", "local"):
            raise PermissionDeniedError(
                "Connectez OBS à l'adresse IP de ce live, pas au serveur partagé.",
                code="direct_ingest_required",
            )
        if node is not None:
            prefix = f"dedicated-{key.organization_id}"
            if node.name != prefix and not node.name.startswith(f"{prefix}-"):
                raise PermissionDeniedError(
                    "Cette instance n'appartient pas à ce compte.",
                    code="direct_ingest_required",
                )
        await ingest_nodes.cancel_idle_termination(
            session,
            organization_id=key.organization_id,
            node_id=node.id if node is not None else None,
        )
        stream = await ingest_service.open_session_for_publish(
            session,
            key=key,
            protocol=protocol,
            remote_ip=body.ip,
            ingest_node_id=node.id if node is not None else None,
        )
        if node is not None and stream.ingest_node_id is None:
            stream.ingest_node_id = node.id
            await session.flush()
        from app.tasks.queue import enqueue

        # Per-live idempotency: every new session can (re)launch a spot after
        # idle terminate. Forever-org keys blocked relaunch on the next live.
        await enqueue(
            session,
            "ingest.ensure_node",
            {
                "organization_id": str(key.organization_id),
                "stream_session_id": str(stream.id),
            },
            queue="ingest",
            organization_id=key.organization_id,
            idempotency_key=f"ensure-node:{key.organization_id}:{stream.id}",
        )
        _pipeline_audit(
            session,
            "ingest.publish_auth",
            organization_id=key.organization_id,
            stream_id=stream.id,
            request=request,
            details={
                "path": body.path,
                "protocol": body.protocol,
                "ip": body.ip,
                "node_id": str(node.id) if node else None,
                "node_host": node.public_hostname if node else None,
            },
        )
    # Return immediately — MediaMTX auth must stay fast or OBS flaps / times out.
    # Spot boot: ingest.ensure_node (drain cron) + edge relay-target sync launch.
    return Response(status_code=200)


@router.get("/ingest/hooks/relay-target", response_model=IngestRelayTargetOut)
async def relay_target(
    request: Request,
    ctx: Ctx,
    path: Annotated[str, Query(min_length=1, max_length=255)],
) -> IngestRelayTargetOut:
    """Edge polls this after publisher_ready to learn where to ffmpeg-push."""
    _require_hook_secret(request, ctx)
    public_id = _public_id_from_path(path)
    if public_id is None:
        return IngestRelayTargetOut(
            status="unavailable",
            rtmp_push_url=None,
            message="Chemin RTMP invalide.",
        )
    async with ctx.db.system_tx() as session:
        key = await ingest_service.find_key_by_public_id(session, public_id)
        if key is None:
            return IngestRelayTargetOut(
                status="unavailable",
                rtmp_push_url=None,
                message="Clé inconnue.",
            )
        try:
            await ingest_nodes.assert_can_go_live(session, key.organization_id)
            result = await ingest_nodes.resolve_for_organization(
                session, ctx.settings, organization_id=key.organization_id
            )
        except PermissionDeniedError as exc:
            _pipeline_audit(
                session,
                "ingest.relay_target",
                organization_id=key.organization_id,
                stream_id=None,
                request=request,
                outcome=AuditOutcome.FAILURE,
                details={"path": path, "error": "forbidden"},
            )
            return IngestRelayTargetOut(
                status="unavailable",
                rtmp_push_url=None,
                message=str(exc.message) if hasattr(exc, "message") else "Accès refusé.",
            )
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
        push_url: str | None = None
        if result.status == "ready" and result.rtmp_url:
            push = result.rtmp_url.rstrip("/")
            parts = [p for p in path.strip("/").split("/") if p]
            if len(parts) >= 2 and parts[0] == "live":
                suffix = "/".join(parts[1:])
                push_url = f"{push}/{suffix}"
            else:
                push_url = f"{push}/{path.strip('/')}"
        # Do not spam the pipeline journal while the spot/MediaMTX is still
        # warming (edge polls every ~3s). Audit only ready / terminal states.
        if result.status != "starting":
            _pipeline_audit(
                session,
                "ingest.relay_target",
                organization_id=key.organization_id,
                stream_id=stream.id if stream else None,
                request=request,
                outcome=(
                    AuditOutcome.SUCCESS
                    if result.status == "ready" and push_url
                    else AuditOutcome.FAILURE
                ),
                details={
                    "path": path,
                    "status": result.status,
                    "host": result.public_hostname,
                    "message": result.message,
                    "has_push_url": bool(push_url),
                },
            )
        if push_url:
            return IngestRelayTargetOut(
                status="ready",
                rtmp_push_url=push_url,
                message="Relay prêt.",
            )
        return IngestRelayTargetOut(
            status=result.status,
            rtmp_push_url=None,
            message=result.message,
        )


@router.post("/ingest/hooks/event", response_model=IngestEventHookOut)
async def mediamtx_event(
    body: IngestEventHookRequest, request: Request, ctx: Ctx
) -> IngestEventHookOut:
    """Publisher disconnect / segment upload ack / heartbeat from the EC2 agent.

    Segment analysis (frames / ASR / Luna) runs on the per-user spot (:8080).
    This hook only acks uploads and session state — it never runs FFmpeg/Luna.
    """
    _require_hook_secret(request, ctx)
    public_id = _public_id_from_path(body.path)
    if public_id is None:
        return IngestEventHookOut(message="ignored")
    stream_session_id = None
    async with ctx.db.system_tx() as session:
        key = await ingest_service.find_key_by_public_id(session, public_id)
        if key is None:
            return IngestEventHookOut(message="ignored")
        caller = _caller_ip(request)
        node = await ingest_nodes.find_node_by_hostname(session, caller)
        stream_query = (
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
        if node is not None:
            bound = (
                await session.execute(
                    stream_query.where(StreamSession.ingest_node_id == node.id)
                )
            ).scalar_one_or_none()
            stream = bound
        else:
            stream = None
        if stream is None:
            stream = (await session.execute(stream_query)).scalar_one_or_none()
        if stream is None:
            return IngestEventHookOut(message="no_open_session")
        stream_session_id = stream.id
        event = body.event.lower()
        if event in ("publisher_disconnect", "end", "stop"):
            # Soft interrupt: MediaMTX flaps / encoder stalls must not end an
            # otherwise healthy live. Finalize only after a grace window.
            from app.tasks.queue import enqueue

            await ingest_service.interrupt_session(
                session, stream, reason=StreamEndReason.PUBLISHER_ENDED
            )
            await enqueue(
                session,
                "ingest.finalize_interrupted",
                {"stream_session_id": str(stream.id)},
                queue="ingest",
                organization_id=key.organization_id,
                run_at=datetime.now(UTC) + timedelta(minutes=3),
                max_attempts=3,
            )
            # Keep the spot warm during the grace window (finalize / stale
            # closer schedules termination if the publisher never returns).
        elif event == "segment" and body.storage_key and body.sequence is not None:
            # Upload ack only. Quota is charged when :8080 posts segment-analysis.
            await ingest_service.resume_session(session, stream)
            stream.last_media_at = datetime.now(UTC)
            await session.flush()
            await ingest_nodes.cancel_idle_termination(
                session,
                organization_id=key.organization_id,
                node_id=node.id if node is not None else stream.ingest_node_id,
            )
        elif event in ("processed", "tick") and body.processed_ms:
            # Heartbeat only — do not bill (quota = analyzed 5-min segments).
            await ingest_service.resume_session(session, stream)
            stream.last_media_at = datetime.now(UTC)
            await session.flush()
        elif event in ("lost", "signal_lost"):
            await ingest_service.close_session(session, stream, reason=StreamEndReason.SIGNAL_LOST)
            await ingest_nodes.schedule_idle_termination(
                session, organization_id=key.organization_id
            )
        elif event in ("publisher_ready", "start"):
            await ingest_service.resume_session(session, stream)
            await ingest_nodes.cancel_idle_termination(
                session,
                organization_id=key.organization_id,
                node_id=node.id if node is not None else stream.ingest_node_id,
            )
        _pipeline_audit(
            session,
            f"ingest.event.{event}",
            organization_id=key.organization_id,
            stream_id=stream.id,
            request=request,
            details={
                "path": body.path,
                "sequence": body.sequence,
                "storage_key": body.storage_key,
                "size_bytes": body.size_bytes,
                "processed_ms": body.processed_ms,
            },
        )
        await ingest_nodes.terminate_due_nodes(session, ctx.settings)
    return IngestEventHookOut(message="ok", stream_session_id=stream_session_id)


@router.post("/ingest/hooks/segment-analysis", response_model=SegmentAnalysisHookOut)
async def segment_analysis_persist(
    body: SegmentAnalysisHookRequest, request: Request, ctx: Ctx
) -> SegmentAnalysisHookOut:
    """Thin DB write for highlights already extracted on the per-user EC2 :8080 agent.

    Never downloads video, never runs FFmpeg/ASR/Bedrock — that work stays on the spot.
    """
    _require_hook_secret(request, ctx)
    from app.services.bedrock_luna import CameraBox, ViralMoment
    from app.services.segment_pipeline import WINDOW_MS, persist_segment_analysis

    moments: list[ViralMoment] = []
    for raw in body.moments:
        cam = raw.camera or {}
        moments.append(
            ViralMoment(
                start_ms=raw.start_ms,
                end_ms=raw.end_ms,
                score=raw.score,
                title=raw.title,
                description=raw.description,
                hashtags=list(raw.hashtags)[:12],
                words=list(raw.words or []),
                camera=CameraBox(
                    detected=bool(cam.get("detected")),
                    x=max(0, min(1919, int(cam.get("x") or 960))),
                    y=max(0, min(1079, int(cam.get("y") or 200))),
                ),
                category=raw.category or "punchline",
            )
        )

    async with ctx.db.system_tx() as session:
        stream = await session.get(StreamSession, body.stream_session_id)
        if stream is None:
            raise NotFoundError("Session introuvable.", code="stream_not_found")
        await ingest_service.resume_session(session, stream)
        analysis_log = _segment_analysis_details(body, moments)
        await persist_segment_analysis(
            session,
            stream=stream,
            sequence=body.sequence,
            storage_key=body.storage_key,
            size_bytes=body.size_bytes,
            moments=moments,
            transcript_text=body.transcript_text,
            transcript_words=list(body.transcript_words or []),
            frames=body.frames,
            model=body.model,
            provider=body.provider or "onbox",
            diagnostics=analysis_log,
        )
        already = stream.processed_ms or 0
        target = (body.sequence + 1) * WINDOW_MS
        unbilled = max(0, target - already)
        if unbilled > 0:
            await ingest_service.record_processed_tick(
                session,
                stream,
                processed_ms=unbilled,
                media_end_ms=target,
            )
        await ingest_nodes.cancel_idle_termination(
            session,
            organization_id=stream.organization_id,
            node_id=stream.ingest_node_id,
        )
        _pipeline_audit(
            session,
            "ingest.segment_analysis",
            organization_id=stream.organization_id,
            stream_id=stream.id,
            request=request,
            details=analysis_log,
        )
        log.info("ingest.segment_analysis", stream_id=str(stream.id), **analysis_log)
    return SegmentAnalysisHookOut(
        message="ok",
        moments=len(moments),
        stream_session_id=body.stream_session_id,
    )
