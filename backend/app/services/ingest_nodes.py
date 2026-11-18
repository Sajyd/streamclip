"""Dedicated compute EC2 nodes (t4g.small spot) per organization (all plans).

OBS always connects to the shared edge RTMP URL. On publish, the API
authenticates the stream key, ensures this org's dedicated spot is up, and the
edge relays the live stream to that instance for 5-min analysis.

Plan differences are quota hours + social connections only — not infrastructure.

When the publisher disconnects, the node is marked for termination after a
5-minute idle margin.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import PermissionDeniedError
from app.core.ids import uuid7
from app.models.enums import IngestNodeKind, IngestNodeStatus, SubscriptionStatus
from app.models.media import IngestNode
from app.services import entitlements
from app.services.ingest_launcher import get_launcher

log = structlog.get_logger(__name__)

RTMP_PORT = 1935
ANALYSIS_PORT = 8080
IDLE_TERMINATE_MARGIN = timedelta(minutes=5)
# Reclaim a stuck STARTING row so a new live can relaunch the spot.
STARTING_STALE_AFTER = timedelta(minutes=8)


def rtmp_port_open(host: str, *, port: int = RTMP_PORT, timeout: float = 1.5) -> bool:
    """True when MediaMTX is accepting RTMP on the dedicated host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
ACTIVE_SUB_STATUSES = frozenset(
    {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE}
)


@dataclass(frozen=True, slots=True)
class ResolveResult:
    status: str  # ready | starting | unavailable | forbidden
    ingest_api_url: str
    rtmp_url: str | None
    analysis_url: str | None
    public_hostname: str | None
    node_id: uuid.UUID | None
    message: str


def ingest_api_url(settings: Settings) -> str:
    """Memorable resolve URL shown to every user."""
    return f"{settings.public_app_url.rstrip('/')}/rtmp"


def rtmp_url_for_host(host: str) -> str:
    return f"rtmp://{host}:{RTMP_PORT}/live"


def analysis_url_for_host(host: str) -> str:
    return f"http://{host}:{ANALYSIS_PORT}"


def _node_name(organization_id: uuid.UUID) -> str:
    return f"dedicated-{organization_id}"


def _details(node: IngestNode) -> dict[str, Any]:
    raw = node.details
    return dict(raw) if isinstance(raw, dict) else {}


async def get_dedicated_node(
    session: AsyncSession, organization_id: uuid.UUID
) -> IngestNode | None:
    """Active (or booting) dedicated node for the org — excludes TERMINATED/LOST."""
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


async def get_dedicated_node_row(
    session: AsyncSession, organization_id: uuid.UUID
) -> IngestNode | None:
    """Any dedicated row for the org (including TERMINATED/LOST) — unique name reuse."""
    return (
        await session.execute(
            select(IngestNode).where(
                IngestNode.name == _node_name(organization_id),
                IngestNode.kind == IngestNodeKind.DEDICATED,
            )
        )
    ).scalar_one_or_none()


def _starting_is_stale(node: IngestNode, *, now: datetime) -> bool:
    details = _details(node)
    raw = details.get("starting_since")
    if raw:
        try:
            since = datetime.fromisoformat(str(raw))
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
            return now - since > STARTING_STALE_AFTER
        except ValueError:
            pass
    # Fallback: no heartbeat / launch progress for too long.
    anchor = node.last_heartbeat_at or node.launched_at or node.created_at
    if anchor is None:
        return True
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    return now - anchor > STARTING_STALE_AFTER


async def assert_can_go_live(session: AsyncSession, organization_id: uuid.UUID) -> None:
    """Subscription active + remaining processing hours required to start a live."""
    try:
        entitlement = await entitlements.get_entitlement(session, organization_id)
    except LookupError as exc:
        raise PermissionDeniedError(
            "Aucun abonnement actif pour démarrer un live.",
            code="subscription_required",
        ) from exc
    if entitlement.subscription.status not in ACTIVE_SUB_STATUSES:
        raise PermissionDeniedError(
            "Votre abonnement ne permet pas de démarrer un live.",
            code="subscription_inactive",
        )
    if entitlement.quota.exhausted:
        raise PermissionDeniedError(
            "Quota mensuel épuisé : plus de temps de traitement disponible.",
            code="quota_exhausted",
        )


async def ensure_dedicated_node(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    start: bool = True,
) -> IngestNode:
    """Return the org's dedicated spot; launch (or relaunch) when needed.

    Gated by active subscription + remaining analysis hours. Reuses the unique
    `dedicated-{org}` row across TERMINATED/LOST so a new RTMP publish always
    gets a fresh spot after idle shutdown.
    """
    await assert_can_go_live(session, organization_id)
    now = datetime.now(UTC)
    existing = await get_dedicated_node(session, organization_id)
    if (
        existing is not None
        and existing.public_hostname
        and existing.status in (IngestNodeStatus.READY, IngestNodeStatus.DRAINING)
    ):
        # Resume within the idle margin: cancel shutdown, keep the same unique host.
        details = _details(existing)
        details.pop("terminate_after", None)
        details.pop("starting_since", None)
        existing.details = details
        existing.status = IngestNodeStatus.READY
        existing.last_heartbeat_at = now
        await session.flush()
        return existing
    if (
        existing is not None
        and existing.status is IngestNodeStatus.STARTING
        and not _starting_is_stale(existing, now=now)
    ):
        return existing
    if not start:
        if existing is not None:
            return existing
        raise LookupError("no_dedicated_node")

    # Prefer the unique name row (even TERMINATED/LOST) over inserting a duplicate.
    node = existing or await get_dedicated_node_row(session, organization_id)
    if node is None:
        node = IngestNode(
            id=uuid7(),
            name=_node_name(organization_id),
            kind=IngestNodeKind.DEDICATED,
            status=IngestNodeStatus.STARTING,
            region=(
                settings.ingest_ec2_region
                or settings.s3_region
                or settings.bedrock_region
                or "eu-north-1"
            ),
            instance_type=settings.ingest_ec2_instance_type or "t4g.small",
            public_hostname=None,
            capacity_streams=1,
            active_streams=0,
            launched_at=None,
            details={
                "organization_id": str(organization_id),
                "spot": True,
                "rtmp_port": RTMP_PORT,
                "analysis_port": ANALYSIS_PORT,
                "starting_since": now.isoformat(),
            },
        )
        session.add(node)
    else:
        # Relaunch: clear previous instance so a new spot is provisioned.
        if node.instance_id and node.status in (
            IngestNodeStatus.TERMINATED,
            IngestNodeStatus.LOST,
            IngestNodeStatus.STARTING,
        ):
            # Best-effort: previous instance may already be gone.
            try:
                await get_launcher(settings).terminate(instance_id=node.instance_id)
            except Exception as exc:  # noqa: BLE001
                log.info(
                    "ingest_spot_prelaunch_terminate_ignored",
                    instance_id=node.instance_id,
                    error=str(exc)[:200],
                )
        node.status = IngestNodeStatus.STARTING
        node.public_hostname = None
        node.instance_id = None
        node.terminated_at = None
        details = _details(node)
        details["organization_id"] = str(organization_id)
        details["spot"] = True
        details["rtmp_port"] = RTMP_PORT
        details["analysis_port"] = ANALYSIS_PORT
        details["starting_since"] = now.isoformat()
        details.pop("terminate_after", None)
        details.pop("launch_error", None)
        node.details = details
    await session.flush()

    launcher = get_launcher(settings)
    try:
        launched = await launcher.launch(
            organization_id=organization_id, node_name=node.name
        )
    except Exception as exc:
        log.error("ingest_spot_launch_failed", organization_id=str(organization_id), error=str(exc))
        node.status = IngestNodeStatus.LOST
        node.terminated_at = datetime.now(UTC)
        details = _details(node)
        details["launch_error"] = str(exc)[:500]
        details.pop("starting_since", None)
        node.details = details
        await session.flush()
        raise

    clash = (
        await session.execute(
            select(IngestNode.id).where(
                IngestNode.public_hostname == launched.public_hostname,
                IngestNode.id != node.id,
                IngestNode.status.in_(
                    (IngestNodeStatus.READY, IngestNodeStatus.STARTING, IngestNodeStatus.DRAINING)
                ),
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        await launcher.terminate(instance_id=launched.instance_id)
        node.status = IngestNodeStatus.LOST
        await session.flush()
        raise RuntimeError("Ingest host collision — refusing shared fallback")

    node.instance_id = launched.instance_id
    node.public_hostname = launched.public_hostname
    node.status = IngestNodeStatus.READY
    node.launched_at = now
    node.last_heartbeat_at = now
    details = _details(node)
    details.pop("terminate_after", None)
    details.pop("launch_error", None)
    details.pop("starting_since", None)
    node.details = details
    await session.flush()
    log.info(
        "ingest_spot_ready",
        organization_id=str(organization_id),
        instance_id=launched.instance_id,
        host=launched.public_hostname,
    )
    return node


async def resolve_for_organization(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
) -> ResolveResult:
    api = ingest_api_url(settings)
    await assert_can_go_live(session, organization_id)
    try:
        node = await ensure_dedicated_node(
            session, settings, organization_id=organization_id, start=True
        )
    except Exception:
        return ResolveResult(
            status="unavailable",
            ingest_api_url=api,
            rtmp_url=None,
            analysis_url=None,
            public_hostname=None,
            node_id=None,
            message="Impossible de démarrer votre instance d'ingestion. Réessayez.",
        )

    if node.status is IngestNodeStatus.READY and node.public_hostname:
        host = node.public_hostname
        # MediaMTX may still be installing — keep "starting" until :1935 accepts.
        # Skip TCP probe for fake/local hosts used in tests.
        probe = settings.environment not in ("test", "local") or not host.endswith(
            ".ingest.test"
        )
        if probe and not await asyncio.to_thread(rtmp_port_open, host):
            return ResolveResult(
                status="starting",
                ingest_api_url=api,
                rtmp_url=rtmp_url_for_host(host),
                analysis_url=analysis_url_for_host(host),
                public_hostname=host,
                node_id=node.id,
                message=(
                    "Instance allumée — MediaMTX démarre (≈1 min). "
                    "Le relay edge réessaiera automatiquement."
                ),
            )
        return ResolveResult(
            status="ready",
            ingest_api_url=api,
            rtmp_url=rtmp_url_for_host(host),
            analysis_url=analysis_url_for_host(host),
            public_hostname=host,
            node_id=node.id,
            message="Instance dédiée prête pour le relay.",
        )
    if node.status is IngestNodeStatus.STARTING:
        return ResolveResult(
            status="starting",
            ingest_api_url=api,
            rtmp_url=None,
            analysis_url=None,
            public_hostname=node.public_hostname,
            node_id=node.id,
            message="Démarrage de votre instance spot — réessayez dans quelques secondes.",
        )
    return ResolveResult(
        status="unavailable",
        ingest_api_url=api,
        rtmp_url=None,
        analysis_url=None,
        public_hostname=node.public_hostname,
        node_id=node.id,
        message="Aucune instance d'ingestion disponible.",
    )


async def schedule_idle_termination(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    margin: timedelta = IDLE_TERMINATE_MARGIN,
) -> IngestNode | None:
    """After RTMP silence: terminate the spot once `margin` has elapsed."""
    node = await get_dedicated_node(session, organization_id)
    if node is None or node.status is IngestNodeStatus.TERMINATED:
        return None
    details = _details(node)
    details["terminate_after"] = (datetime.now(UTC) + margin).isoformat()
    node.details = details
    node.status = IngestNodeStatus.DRAINING
    await session.flush()
    return node


async def cancel_idle_termination(
    session: AsyncSession, *, organization_id: uuid.UUID
) -> None:
    node = await get_dedicated_node(session, organization_id)
    if node is None:
        return
    details = _details(node)
    if "terminate_after" in details:
        details.pop("terminate_after", None)
        node.details = details
        if node.status is IngestNodeStatus.DRAINING and node.public_hostname:
            node.status = IngestNodeStatus.READY
        await session.flush()


async def terminate_due_nodes(session: AsyncSession, settings: Settings) -> int:
    """Terminate spots whose idle margin has elapsed. Returns count terminated."""
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(IngestNode).where(
                IngestNode.kind == IngestNodeKind.DEDICATED,
                IngestNode.status.in_(
                    (IngestNodeStatus.DRAINING, IngestNodeStatus.READY, IngestNodeStatus.STARTING)
                ),
            )
        )
    ).scalars()
    launcher = get_launcher(settings)
    terminated = 0
    for node in rows:
        details = _details(node)
        raw = details.get("terminate_after")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when > now:
            continue
        if node.instance_id:
            try:
                await launcher.terminate(instance_id=node.instance_id)
            except Exception as exc:
                log.error("ingest_spot_terminate_failed", instance_id=node.instance_id, error=str(exc))
        node.status = IngestNodeStatus.TERMINATED
        node.terminated_at = now
        node.public_hostname = None
        details.pop("terminate_after", None)
        node.details = details
        terminated += 1
    if terminated:
        await session.flush()
    return terminated


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
    details = _details(node)
    details.pop("terminate_after", None)
    node.details = details
    await session.flush()
    return node
