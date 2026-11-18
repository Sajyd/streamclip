"""Live preview: HLS via edge (preferred) or dedicated agent (:8080).

Browsers cannot play RTMP. OBS publishes to the shared edge; MediaMTX remuxes
to localhost HLS and a small proxy on :8080 serves it. Dedicated spots keep the
same shape as a fallback. The API authenticates the caller, then proxies bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
import structlog
from sqlalchemy import select

from app.context import AppContext
from app.core.config import Settings
from app.core.errors import NotFoundError, PermissionDeniedError, ServiceUnavailableError
from app.models.enums import StreamKeyStatus, StreamSessionStatus
from app.models.media import StreamKey, StreamSession
from app.services import ingest_nodes
from app.services.auth import Principal
from app.services.preview_network import edge_preview_host, schedule_repair

log = structlog.get_logger(__name__)

_LIVE = {StreamSessionStatus.PENDING, StreamSessionStatus.LIVE}
_TOKEN_TTL_SEC = 300
_AGENT_PORT = 8080


@dataclass(frozen=True, slots=True)
class PlaybackInfo:
    status: str
    session_id: uuid.UUID | None
    public_id: str | None
    title: str | None
    rtmp_url: str | None
    preview_available: bool
    message: str
    stream_key_hint: str | None = None
    organization_id: uuid.UUID | None = None
    # MediaMTX path OBS actually published (may include the stream secret).
    # Server-side only — never returned to the browser.
    publish_path: str | None = None


def _signing_secret(settings: Settings) -> bytes | None:
    if settings.ingest_hook_secret is None:
        return None
    return settings.ingest_hook_secret.get_secret_value().encode("utf-8")


def mint_preview_token(settings: Settings, *, public_id: str) -> str | None:
    secret = _signing_secret(settings)
    if secret is None:
        return None
    exp = int(time.time()) + _TOKEN_TTL_SEC
    payload = f"{public_id}:{exp}"
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"pb.{public_id}.{exp}.{sig}"


def verify_preview_token(settings: Settings, token: str | None, *, public_id: str) -> bool:
    if not token or not token.startswith("pb."):
        return False
    secret = _signing_secret(settings)
    if secret is None:
        return False
    parts = token.split(".")
    if len(parts) != 4:
        return False
    _, tok_pid, exp_s, sig = parts
    if tok_pid != public_id:
        return False
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    payload = f"{public_id}:{exp}"
    expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected)


_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,240}$")


def sanitize_publish_path(raw: str | None) -> str | None:
    """Keep a MediaMTX path and drop anything that could escape the HLS prefix."""
    if not raw:
        return None
    path = raw.strip().split("?", 1)[0].strip("/")
    if not path or ".." in path.split("/") or not _PATH_RE.fullmatch(path):
        return None
    return path


def hls_stream_path(info: PlaybackInfo) -> str:
    """Directory MediaMTX uses for this live.

    OBS is given server ``…/live`` and stream key ``{public_id}/{secret}``, so the
    real path is ``live/{public_id}/{secret}``. Falling back to ``live/{public_id}``
    only covers publishers that put the secret in the RTMP password instead.
    """
    stored = sanitize_publish_path(info.publish_path)
    if stored:
        return stored
    if info.public_id:
        return f"live/{info.public_id}"
    return ""


def hls_leaf_name(file_path: str) -> str:
    name = file_path.strip().split("?", 1)[0].strip("/").split("/")[-1]
    if not name or name in {".", ".."} or not _PATH_RE.fullmatch(name):
        return ""
    return name


def agent_hls_url(host: str, stream_path: str, *, file_path: str, token: str | None) -> str:
    parts = [quote(part, safe="") for part in stream_path.strip("/").split("/") if part]
    leaf = quote(hls_leaf_name(file_path) or file_path.strip("/").split("/")[-1], safe="")
    base = f"http://{host}:{_AGENT_PORT}/hls/{'/'.join(parts)}/{leaf}"
    if token:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}token={quote(token, safe='')}"
    return base


async def _active_session(
    session, organization_id: uuid.UUID
) -> tuple[StreamSession | None, StreamKey | None]:
    stream = (
        await session.execute(
            select(StreamSession)
            .where(
                StreamSession.organization_id == organization_id,
                StreamSession.status.in_(_LIVE),
            )
            .order_by(StreamSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    key = None
    if stream is not None and stream.stream_key_id is not None:
        key = await session.get(StreamKey, stream.stream_key_id)
    if key is None:
        key = (
            await session.execute(
                select(StreamKey).where(
                    StreamKey.organization_id == organization_id,
                    StreamKey.status == StreamKeyStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
    return stream, key


async def _publish_path(session, stream: StreamSession) -> str | None:
    """Path MediaMTX recorded when it accepted the publisher."""
    from app.models.system import AuditLog

    details = (
        await session.execute(
            select(AuditLog.details)
            .where(
                AuditLog.organization_id == stream.organization_id,
                AuditLog.action == "ingest.publish_auth",
                AuditLog.target_id == str(stream.id),
            )
            .order_by(AuditLog.occurred_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not isinstance(details, dict):
        return None
    raw = details.get("path")
    return sanitize_publish_path(raw if isinstance(raw, str) else None)


def _assemble_playback(
    *,
    stream: StreamSession | None,
    key: StreamKey | None,
    dedicated_host: str | None,
    edge_host: str | None,
    organization_id: uuid.UUID,
    publish_path: str | None,
    offline_message: str,
) -> PlaybackInfo:
    public_id = key.public_id if key else None
    rtmp = ingest_nodes.rtmp_url_for_host(dedicated_host) if dedicated_host else None
    hint = key.key_hint if key else None
    base = dict(
        public_id=public_id,
        rtmp_url=rtmp,
        stream_key_hint=hint,
        organization_id=organization_id,
        publish_path=publish_path,
    )
    if stream is None:
        return PlaybackInfo(
            status="offline",
            session_id=None,
            title=None,
            preview_available=False,
            message=offline_message,
            **base,
        )
    # HLS is remuxed on the shared edge as soon as OBS connects. A dedicated
    # spot is only a fallback host — waiting for it left the preview blank.
    can_preview = bool(public_id and (edge_host or dedicated_host) and stream.status in _LIVE)
    if stream.status not in _LIVE:
        status, preview, message = "offline", False, offline_message
    elif not can_preview:
        status, preview, message = (
            "starting",
            False,
            "Aperçu en préparation — le flux n'est pas encore joignable.",
        )
    elif stream.status == StreamSessionStatus.PENDING:
        status, preview, message = "starting", True, "Préparation de l'aperçu…"
    else:
        status, preview, message = "live", True, "Live en cours."
    return PlaybackInfo(
        status=status,
        session_id=stream.id,
        title=stream.title,
        preview_available=preview,
        message=message,
        **base,
    )


async def playback_for_org(ctx: AppContext, organization_id: uuid.UUID) -> PlaybackInfo:
    async with ctx.db.system_tx() as session:
        stream, key = await _active_session(session, organization_id)
        node = None
        if stream is not None and stream.ingest_node_id:
            from app.models.media import IngestNode

            node = await session.get(IngestNode, stream.ingest_node_id)
        if node is None:
            node = await ingest_nodes.preferred_ready_node(session, organization_id)
        publish_path = await _publish_path(session, stream) if stream is not None else None

    dedicated = node.public_hostname if node and node.status.value == "ready" else None
    return _assemble_playback(
        stream=stream,
        key=key,
        dedicated_host=dedicated,
        edge_host=edge_preview_host(ctx.settings),
        organization_id=organization_id,
        publish_path=publish_path,
        offline_message="Aucun live en cours.",
    )


async def playback_for_principal(ctx: AppContext, principal: Principal) -> PlaybackInfo:
    return await playback_for_org(ctx, principal.organization_id)


async def playback_for_live(ctx: AppContext, live_id: uuid.UUID) -> PlaybackInfo:
    async with ctx.db.system_tx() as session:
        stream = await session.get(StreamSession, live_id)
        if stream is None:
            raise NotFoundError("Live introuvable.", code="live_not_found")
        key = None
        if stream.stream_key_id:
            key = await session.get(StreamKey, stream.stream_key_id)
        if key is None:
            key = (
                await session.execute(
                    select(StreamKey).where(
                        StreamKey.organization_id == stream.organization_id,
                        StreamKey.status == StreamKeyStatus.ACTIVE,
                    )
                )
            ).scalar_one_or_none()
        node = None
        if stream.ingest_node_id:
            from app.models.media import IngestNode

            node = await session.get(IngestNode, stream.ingest_node_id)
        if node is None:
            node = await ingest_nodes.preferred_ready_node(session, stream.organization_id)
        publish_path = await _publish_path(session, stream)

    dedicated = node.public_hostname if node and node.status.value == "ready" else None
    return _assemble_playback(
        stream=stream,
        key=key,
        dedicated_host=dedicated,
        edge_host=edge_preview_host(ctx.settings),
        organization_id=stream.organization_id,
        publish_path=publish_path,
        offline_message="Ce live n'est plus en cours.",
    )


def info_to_dict(info: PlaybackInfo, settings: Settings) -> dict[str, Any]:
    token = (
        mint_preview_token(settings, public_id=info.public_id)
        if info.public_id and info.preview_available
        else None
    )
    # Do NOT schedule_repair here. Playback status is polled every few seconds from
    # the dashboard; repair rewrites MediaMTX and restarts it, which drops OBS and
    # aborts the 5-min segment window. Heal only from proxy_hls failures.
    return {
        "status": info.status,
        "session_id": info.session_id,
        "public_id": info.public_id,
        "title": info.title,
        "rtmp_url": info.rtmp_url,
        "preview_available": info.preview_available,
        "message": info.message,
        "stream_key_hint": info.stream_key_hint,
        "preview_token": token,
    }


def _preview_hosts(
    settings: Settings, *, dedicated_host: str | None
) -> list[str]:
    """The live is on its own spot. The shared edge is only a fallback."""
    hosts: list[str] = []
    if dedicated_host:
        hosts.append(dedicated_host)
    edge = edge_preview_host(settings)
    if edge and edge not in hosts:
        hosts.append(edge)
    return hosts


async def _fetch_hls(
    *,
    host: str,
    stream_path: str,
    file_path: str,
    token: str | None,
    headers: dict[str, str],
) -> httpx.Response:
    url = agent_hls_url(host, stream_path, file_path=file_path, token=token)
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.get(url, headers=headers)
        # MediaMTX: index.m3u8 (master) may 404 briefly; stream.m3u8 is the media playlist.
        if response.status_code == 404 and file_path.rstrip("/").endswith("index.m3u8"):
            alt = agent_hls_url(host, stream_path, file_path="stream.m3u8", token=token)
            response = await client.get(alt, headers=headers)
        return response


async def proxy_hls(
    ctx: AppContext,
    info: PlaybackInfo,
    *,
    file_path: str,
) -> tuple[bytes, str]:
    if not info.preview_available or not info.public_id:
        raise ServiceUnavailableError(info.message, code="preview_unavailable")
    dedicated_host: str | None = None
    dedicated_instance_id: str | None = None
    async with ctx.db.system_tx() as session:
        node = None
        if info.session_id:
            stream = await session.get(StreamSession, info.session_id)
            if stream and stream.ingest_node_id:
                from app.models.media import IngestNode

                node = await session.get(IngestNode, stream.ingest_node_id)
        if node is None:
            node = await ingest_nodes.preferred_ready_node(session, info.organization_id)
        if node and node.status.value == "ready":
            dedicated_host = node.public_hostname
            dedicated_instance_id = node.instance_id

    hosts = _preview_hosts(ctx.settings, dedicated_host=dedicated_host)
    if not hosts:
        raise ServiceUnavailableError("Instance dédiée hors ligne.", code="preview_unavailable")
    stream_path = hls_stream_path(info)
    leaf = hls_leaf_name(file_path)
    if not stream_path or not leaf:
        raise NotFoundError("Segment introuvable.", code="preview_not_found")

    token = mint_preview_token(ctx.settings, public_id=info.public_id)
    headers: dict[str, str] = {}
    if ctx.settings.ingest_hook_secret is not None:
        headers["X-Streamclip-Ingest-Secret"] = (
            ctx.settings.ingest_hook_secret.get_secret_value()
        )

    last_error: Exception | None = None
    response: httpx.Response | None = None
    used_host: str | None = None
    for host in hosts:
        try:
            response = await _fetch_hls(
                host=host,
                stream_path=stream_path,
                file_path=leaf,
                token=token,
                headers=headers,
            )
            used_host = host
            if response.status_code < 500:
                break
            log.warning(
                "playback.proxy_bad_status",
                status=response.status_code,
                host=host,
                path=file_path,
            )
        except httpx.HTTPError as exc:
            last_error = exc
            log.warning("playback.proxy_failed", error=str(exc), host=host)
            continue

    if response is None:
        schedule_repair(ctx.settings, dedicated_instance_id=dedicated_instance_id)
        raise ServiceUnavailableError(
            "Aperçu temporairement indisponible.", code="preview_unavailable"
        ) from last_error

    if response.status_code >= 500 or (
        response.status_code in {401, 403, 404} and used_host == hosts[0] and len(hosts) > 1
    ):
        # Edge missing proxy / not ready yet → heal in background and try dedicated.
        schedule_repair(ctx.settings, dedicated_instance_id=dedicated_instance_id)
        if used_host == hosts[0] and len(hosts) > 1:
            try:
                response = await _fetch_hls(
                    host=hosts[1],
                    stream_path=stream_path,
                    file_path=leaf,
                    token=token,
                    headers=headers,
                )
                used_host = hosts[1]
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning("playback.proxy_failed", error=str(exc), host=hosts[1])

    if response is None or response.status_code >= 500:
        schedule_repair(ctx.settings, dedicated_instance_id=dedicated_instance_id)
        raise ServiceUnavailableError(
            "Aperçu temporairement indisponible.", code="preview_unavailable"
        ) from last_error

    if response.status_code in {401, 403}:
        raise PermissionDeniedError("Aperçu non autorisé.", code="preview_forbidden")
    if response.status_code == 404:
        # First failure often means edge HLS not installed yet — kick repair.
        schedule_repair(ctx.settings, dedicated_instance_id=dedicated_instance_id)
        raise NotFoundError(
            "Flux HLS introuvable — le live vient peut-être de démarrer.",
            code="preview_not_found",
        )
    if response.status_code >= 400:
        log.warning(
            "playback.proxy_bad_status",
            status=response.status_code,
            host=used_host,
            path=file_path,
        )
        schedule_repair(ctx.settings, dedicated_instance_id=dedicated_instance_id)
        raise ServiceUnavailableError(
            "Aperçu temporairement indisponible.", code="preview_unavailable"
        )
    content_type = response.headers.get("content-type") or (
        "application/vnd.apple.mpegurl"
        if file_path.endswith(".m3u8")
        else "video/mp2t"
    )
    body = response.content
    # Rewrite absolute URIs so the browser stays on the Next.js proxy.
    if file_path.endswith(".m3u8") or "mpegurl" in content_type:
        text = body.decode("utf-8", errors="replace")
        if text.lstrip().startswith("#EXTM3U"):
            lines: list[str] = []
            for line in text.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    path_only = stripped.split("?", 1)[0]
                    if (
                        path_only.startswith("http://")
                        or path_only.startswith("https://")
                        or path_only.startswith("/")
                    ):
                        line = path_only.rsplit("/", 1)[-1]
                lines.append(line)
            body = "\n".join(lines).encode("utf-8")
            content_type = "application/vnd.apple.mpegurl"
    return body, content_type
