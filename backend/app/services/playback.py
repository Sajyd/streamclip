"""Live preview: resolve dedicated-node HLS via the on-box agent (:8080).

Browsers cannot play RTMP. MediaMTX remuxes to HLS on localhost; the analysis
agent proxies `/hls/…` on the already-open :8080. The API authenticates the
caller (user or staff), then either returns metadata or proxies bytes.
"""

from __future__ import annotations

import hashlib
import hmac
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


def agent_hls_url(host: str, public_id: str, *, file_path: str, token: str | None) -> str:
    safe = file_path.lstrip("/")
    base = f"http://{host}:{_AGENT_PORT}/hls/live/{quote(public_id, safe='')}/{safe}"
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


async def playback_for_org(ctx: AppContext, organization_id: uuid.UUID) -> PlaybackInfo:
    async with ctx.db.system_tx() as session:
        stream, key = await _active_session(session, organization_id)
        node = await ingest_nodes.get_dedicated_node(session, organization_id)
        if node is None and stream is not None and stream.ingest_node_id:
            from app.models.media import IngestNode

            node = await session.get(IngestNode, stream.ingest_node_id)

    public_id = key.public_id if key else None
    host = node.public_hostname if node and node.status.value == "ready" else None
    rtmp = ingest_nodes.rtmp_url_for_host(host) if host else None

    if stream is None:
        return PlaybackInfo(
            status="offline",
            session_id=None,
            public_id=public_id,
            title=None,
            rtmp_url=rtmp,
            preview_available=False,
            message="Aucun live en cours.",
            stream_key_hint=key.key_hint if key else None,
            organization_id=organization_id,
        )
    if not host or not public_id:
        return PlaybackInfo(
            status="starting",
            session_id=stream.id,
            public_id=public_id,
            title=stream.title,
            rtmp_url=rtmp,
            preview_available=False,
            message="Instance dédiée en cours de démarrage — l'aperçu arrive dans un instant.",
            stream_key_hint=key.key_hint if key else None,
            organization_id=organization_id,
        )
    return PlaybackInfo(
        status="live",
        session_id=stream.id,
        public_id=public_id,
        title=stream.title,
        rtmp_url=rtmp,
        preview_available=True,
        message="Live en cours.",
        stream_key_hint=key.key_hint if key else None,
        organization_id=organization_id,
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
        node = await ingest_nodes.get_dedicated_node(session, stream.organization_id)
        if node is None and stream.ingest_node_id:
            from app.models.media import IngestNode

            node = await session.get(IngestNode, stream.ingest_node_id)

    public_id = key.public_id if key else None
    host = node.public_hostname if node and node.status.value == "ready" else None
    rtmp = ingest_nodes.rtmp_url_for_host(host) if host else None
    is_live = stream.status in _LIVE

    if not is_live:
        return PlaybackInfo(
            status="offline",
            session_id=stream.id,
            public_id=public_id,
            title=stream.title,
            rtmp_url=rtmp,
            preview_available=False,
            message="Ce live n'est plus en cours.",
            stream_key_hint=key.key_hint if key else None,
            organization_id=stream.organization_id,
        )
    if not host or not public_id:
        return PlaybackInfo(
            status="starting",
            session_id=stream.id,
            public_id=public_id,
            title=stream.title,
            rtmp_url=rtmp,
            preview_available=False,
            message="Instance dédiée indisponible pour l'aperçu.",
            stream_key_hint=key.key_hint if key else None,
            organization_id=stream.organization_id,
        )
    return PlaybackInfo(
        status="live",
        session_id=stream.id,
        public_id=public_id,
        title=stream.title,
        rtmp_url=rtmp,
        preview_available=True,
        message="Live en cours.",
        stream_key_hint=key.key_hint if key else None,
        organization_id=stream.organization_id,
    )


def info_to_dict(info: PlaybackInfo, settings: Settings) -> dict[str, Any]:
    token = (
        mint_preview_token(settings, public_id=info.public_id)
        if info.public_id and info.preview_available
        else None
    )
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


async def proxy_hls(
    ctx: AppContext,
    info: PlaybackInfo,
    *,
    file_path: str,
) -> tuple[bytes, str]:
    if not info.preview_available or not info.public_id:
        raise ServiceUnavailableError(info.message, code="preview_unavailable")
    async with ctx.db.system_tx() as session:
        node = await ingest_nodes.get_dedicated_node(session, info.organization_id)
        if node is None and info.session_id:
            stream = await session.get(StreamSession, info.session_id)
            if stream and stream.ingest_node_id:
                from app.models.media import IngestNode

                node = await session.get(IngestNode, stream.ingest_node_id)
    host = node.public_hostname if node and node.status.value == "ready" else None
    if not host:
        raise ServiceUnavailableError("Instance dédiée hors ligne.", code="preview_unavailable")

    token = mint_preview_token(ctx.settings, public_id=info.public_id)
    url = agent_hls_url(host, info.public_id, file_path=file_path, token=token)
    headers: dict[str, str] = {}
    if ctx.settings.ingest_hook_secret is not None:
        headers["X-Streamclip-Ingest-Secret"] = (
            ctx.settings.ingest_hook_secret.get_secret_value()
        )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=headers)
            # MediaMTX: index.m3u8 (master) may 404 briefly; stream.m3u8 is the media playlist.
            if (
                response.status_code == 404
                and file_path.rstrip("/").endswith("index.m3u8")
            ):
                alt = agent_hls_url(
                    host, info.public_id, file_path="stream.m3u8", token=token
                )
                response = await client.get(alt, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("playback.proxy_failed", error=str(exc), host=host)
        raise ServiceUnavailableError(
            "Aperçu temporairement indisponible.", code="preview_unavailable"
        ) from exc
    if response.status_code == 401 or response.status_code == 403:
        raise PermissionDeniedError("Aperçu non autorisé.", code="preview_forbidden")
    if response.status_code == 404:
        raise NotFoundError(
            "Flux HLS introuvable — le live vient peut-être de démarrer.",
            code="preview_not_found",
        )
    if response.status_code >= 400:
        log.warning(
            "playback.proxy_bad_status",
            status=response.status_code,
            host=host,
            path=file_path,
        )
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
                    if path_only.startswith("http://") or path_only.startswith("https://") or path_only.startswith("/"):
                        line = path_only.rsplit("/", 1)[-1]
                lines.append(line)
            body = "\n".join(lines).encode("utf-8")
            content_type = "application/vnd.apple.mpegurl"
    return body, content_type
