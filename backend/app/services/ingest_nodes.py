"""Dedicated ingest EC2 nodes (t4g.small spot) per organization.

Lifecycle:
  resolve(secret) → ensure dedicated node → start spot if needed →
  return rtmp://{public_hostname}:1935/live once READY.

MediaMTX on the instance accepts RTMP; a second HTTP port serves the
analysis agent. The 5-minute FFmpeg → analysis → DB loop runs on-box
(`python -m app.cli live-loop`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import uuid7
from app.models.enums import IngestNodeKind, IngestNodeStatus
from app.models.media import IngestNode

RTMP_PORT = 1935
ANALYSIS_PORT = 8080


@dataclass(frozen=True, slots=True)
class ResolveResult:
    status: str  # starting | ready | unavailable
    ingest_api_url: str
    rtmp_url: str | None
    analysis_url: str | None
    public_hostname: str | None
    node_id: uuid.UUID | None
    message: str


def ingest_api_url(settings: Settings) -> str:
    """Stable API address shown to every user (OBS resolves via stream key)."""
    base = settings.public_app_url.rstrip("/")
    return f"{base}/api/v1/ingest/resolve"


def rtmp_url_for_host(host: str) -> str:
    return f"rtmp://{host}:{RTMP_PORT}/live"


def analysis_url_for_host(host: str) -> str:
    return f"http://{host}:{ANALYSIS_PORT}"


def _node_name(organization_id: uuid.UUID) -> str:
    return f"dedicated-{organization_id}"


async def get_dedicated_node(
    session: AsyncSession, organization_id: uuid.UUID
) -> IngestNode | None:
    return (
        await session.execute(
            select(IngestNode).where(
                IngestNode.name == _node_name(organization_id),
                IngestNode.kind == IngestNodeKind.DEDICATED,
                IngestNode.status.in_(
                    (
                        IngestNodeStatus.STARTING,
                        IngestNodeStatus.READY,
                        IngestNodeStatus.DRAINING,
                    )
                ),
            )
        )
    ).scalar_one_or_none()


async def ensure_dedicated_node(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
) -> IngestNode:
    """Return the org's dedicated spot node, creating/starting it if needed.

    Until full RunInstances automation is wired, a configured
    `INGEST_PUBLIC_HOST` (or host extracted from `INGEST_RTMPS_URL`) marks the
    node READY immediately — one shared host can still back early deploys.
    Per-org spots replace that host once the launcher is enabled.
    """
    existing = await get_dedicated_node(session, organization_id)
    fallback_host = _fallback_hostname(settings)

    if existing is not None:
        if existing.status is IngestNodeStatus.READY and existing.public_hostname:
            return existing
        if fallback_host and (
            existing.public_hostname is None or existing.status is IngestNodeStatus.STARTING
        ):
            existing.public_hostname = fallback_host
            existing.status = IngestNodeStatus.READY
            existing.last_heartbeat_at = datetime.now(UTC)
            await session.flush()
        return existing

    now = datetime.now(UTC)
    node = IngestNode(
        id=uuid7(),
        name=_node_name(organization_id),
        kind=IngestNodeKind.DEDICATED,
        status=IngestNodeStatus.READY if fallback_host else IngestNodeStatus.STARTING,
        region=(settings.s3_region or settings.bedrock_region or "eu-north-1"),
        instance_type="t4g.small",
        public_hostname=fallback_host,
        capacity_streams=1,
        active_streams=0,
        launched_at=now if fallback_host else None,
        details={
            "organization_id": str(organization_id),
            "spot": True,
            "rtmp_port": RTMP_PORT,
            "analysis_port": ANALYSIS_PORT,
        },
    )
    session.add(node)
    await session.flush()
    return node


def _fallback_hostname(settings: Settings) -> str | None:
    host = (settings.ingest_public_host or "").strip() or None
    if host:
        return host
    raw = (settings.ingest_rtmps_url or "").strip()
    if not raw:
        return None
    # rtmp(s)://hostname[:port]/path
    without_scheme = raw.split("://", 1)[-1]
    hostport = without_scheme.split("/", 1)[0]
    return hostport.split(":", 1)[0] or None


async def resolve_for_organization(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
) -> ResolveResult:
    api = ingest_api_url(settings)
    node = await ensure_dedicated_node(session, settings, organization_id=organization_id)
    if node.status is IngestNodeStatus.READY and node.public_hostname:
        host = node.public_hostname
        return ResolveResult(
            status="ready",
            ingest_api_url=api,
            rtmp_url=rtmp_url_for_host(host),
            analysis_url=analysis_url_for_host(host),
            public_hostname=host,
            node_id=node.id,
            message="Instance prête — collez l'URL RTMP dans OBS / Streamlabs.",
        )
    if node.status is IngestNodeStatus.STARTING:
        return ResolveResult(
            status="starting",
            ingest_api_url=api,
            rtmp_url=None,
            analysis_url=None,
            public_hostname=None,
            node_id=node.id,
            message="Démarrage de votre instance spot t4g.small — réessayez dans quelques secondes.",
        )
    return ResolveResult(
        status="unavailable",
        ingest_api_url=api,
        rtmp_url=None,
        analysis_url=None,
        public_hostname=node.public_hostname,
        node_id=node.id,
        message="Aucune instance d'ingestion disponible pour le moment.",
    )


async def mark_node_ready(
    session: AsyncSession,
    *,
    node_id: uuid.UUID,
    public_hostname: str,
    instance_id: str | None = None,
) -> IngestNode | None:
    node = await session.get(IngestNode, node_id)
    if node is None:
        return None
    node.public_hostname = public_hostname
    if instance_id:
        node.instance_id = instance_id
    node.status = IngestNodeStatus.READY
    node.last_heartbeat_at = datetime.now(UTC)
    if node.launched_at is None:
        node.launched_at = datetime.now(UTC)
    await session.flush()
    return node
