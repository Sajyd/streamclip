"""Dedicated compute EC2 nodes (t4g.small spot), one public IP per live.

OBS publishes straight to that spot (`rtmp://<ip>:1935/live`). A second live
gets another instance. The shared edge is not the media path.

Plan differences are quota hours + social connections only — not infrastructure.

When the publisher disconnects, that spot is marked for termination after a
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
from sqlalchemy import or_, select
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


def _name_filter(organization_id: uuid.UUID):
    prefix = _node_name(organization_id)
    return or_(IngestNode.name == prefix, IngestNode.name.startswith(f"{prefix}-"))


async def list_active_dedicated_nodes(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[IngestNode]:
    """Ready, starting, or draining spots for this org (every live slot)."""
    rows = (
        await session.execute(
            select(IngestNode)
            .where(
                _name_filter(organization_id),
                IngestNode.kind == IngestNodeKind.DEDICATED,
                IngestNode.status.in_(
                    (
                        IngestNodeStatus.STARTING,
                        IngestNodeStatus.READY,
                        IngestNodeStatus.DRAINING,
                    )
                ),
            )
            .order_by(IngestNode.created_at.asc())
        )
    ).scalars()
    return list(rows)


async def open_node_ids(session: AsyncSession, organization_id: uuid.UUID) -> set[uuid.UUID]:
    """Spots that already have a live attached — they cannot take another stream."""
    from app.models.enums import StreamSessionStatus
    from app.models.media import StreamSession

    rows = (
        await session.execute(
            select(StreamSession.ingest_node_id).where(
                StreamSession.organization_id == organization_id,
                StreamSession.ingest_node_id.is_not(None),
                StreamSession.status.in_(
                    (
                        StreamSessionStatus.PENDING,
                        StreamSessionStatus.LIVE,
                        StreamSessionStatus.INTERRUPTED,
                        StreamSessionStatus.FINALIZING,
                    )
                ),
            )
        )
    ).scalars()
    return {node_id for node_id in rows if node_id is not None}


async def find_node_by_hostname(session: AsyncSession, host: str | None) -> IngestNode | None:
    """The spot whose public IP made the MediaMTX auth call."""
    cleaned = (host or "").strip()
    if not cleaned:
        return None
    return (
        await session.execute(
            select(IngestNode).where(
                IngestNode.public_hostname == cleaned,
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


async def preferred_ready_node(
    session: AsyncSession, organization_id: uuid.UUID
) -> IngestNode | None:
    """Free ready spot if one is idle, otherwise any ready spot."""
    nodes = await list_active_dedicated_nodes(session, organization_id)
    busy = await open_node_ids(session, organization_id)
    ready = [
        node
        for node in nodes
        if node.status is IngestNodeStatus.READY and node.public_hostname
    ]
    for node in ready:
        if node.id not in busy:
            return node
    return ready[0] if ready else None


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


def _fresh_node(
    settings: Settings, *, organization_id: uuid.UUID, name: str, now: datetime
) -> IngestNode:
    return IngestNode(
        id=uuid7(),
        name=name,
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


async def _provision_node(
    session: AsyncSession,
    settings: Settings,
    node: IngestNode,
    organization_id: uuid.UUID,
    now: datetime,
) -> IngestNode:
    launcher = get_launcher(settings)
    try:
        launched = await launcher.launch(organization_id=organization_id, node_name=node.name)
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
    details.pop("lost_reason", None)
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


async def _ensure_extra_slot(
    session: AsyncSession,
    settings: Settings,
    organization_id: uuid.UUID,
    now: datetime,
) -> IngestNode:
    """Another live: reuse an idle spot, otherwise launch a new IP."""
    busy = await open_node_ids(session, organization_id)
    if busy:
        entitlement = await entitlements.get_entitlement(session, organization_id)
        if len(busy) >= entitlement.plan.max_concurrent_streams:
            raise PermissionDeniedError(
                "Votre offre n'autorise pas un second live en même temps.",
                code="concurrent_stream_limit",
            )
    for node in await list_active_dedicated_nodes(session, organization_id):
        if node.id in busy:
            continue
        if node.public_hostname and node.status in (
            IngestNodeStatus.READY,
            IngestNodeStatus.DRAINING,
        ):
            details = _details(node)
            details.pop("terminate_after", None)
            node.details = details
            node.status = IngestNodeStatus.READY
            node.last_heartbeat_at = now
            await session.flush()
            return node
        if node.status is IngestNodeStatus.STARTING and not _starting_is_stale(node, now=now):
            return node
    node = _fresh_node(
        settings,
        organization_id=organization_id,
        name=f"{_node_name(organization_id)}-{uuid.uuid4().hex[:8]}",
        now=now,
    )
    session.add(node)
    await session.flush()
    return await _provision_node(session, settings, node, organization_id, now)


async def ensure_dedicated_node(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    start: bool = True,
    additional: bool = False,
) -> IngestNode:
    """Return a spot for this org; launch when needed.

    The primary row `dedicated-{org}` is reused after idle shutdown.
    `additional=True` gives a second live its own IP when the first spot is busy.
    """
    await assert_can_go_live(session, organization_id)
    now = datetime.now(UTC)
    if additional:
        return await _ensure_extra_slot(session, settings, organization_id, now)
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
        node = _fresh_node(
            settings,
            organization_id=organization_id,
            name=_node_name(organization_id),
            now=now,
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
    return await _provision_node(session, settings, node, organization_id, now)


async def resolve_for_organization(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    new_server: bool = False,
) -> ResolveResult:
    api = ingest_api_url(settings)
    await assert_can_go_live(session, organization_id)
    try:
        node = await ensure_dedicated_node(
            session,
            settings,
            organization_id=organization_id,
            start=True,
            additional=new_server,
        )
    except PermissionDeniedError:
        raise
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
        if node.instance_id:
            try:
                view = await get_launcher(settings).describe_instance(
                    instance_id=node.instance_id
                )
            except Exception as exc:  # noqa: BLE001 — do not hand out an unverified host
                log.warning(
                    "ingest_spot_describe_failed",
                    instance_id=node.instance_id,
                    error=str(exc)[:200],
                )
                return ResolveResult(
                    status="starting",
                    ingest_api_url=api,
                    rtmp_url=None,
                    analysis_url=None,
                    public_hostname=None,
                    node_id=node.id,
                    message="Vérification de l'instance en cours. Réessayez dans quelques secondes.",
                )
            if not view.usable:
                log.warning(
                    "ingest_spot_not_running",
                    instance_id=node.instance_id,
                    state=view.state,
                    host=host,
                )
                node.status = IngestNodeStatus.LOST
                node.public_hostname = None
                node.terminated_at = datetime.now(UTC)
                details = _details(node)
                details["lost_reason"] = view.state
                node.details = details
                await session.flush()
                try:
                    await ensure_dedicated_node(
                        session,
                        settings,
                        organization_id=organization_id,
                        start=True,
                        additional=new_server,
                    )
                except PermissionDeniedError:
                    raise
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
                return await resolve_for_organization(
                    session, settings, organization_id=organization_id, new_server=new_server
                )
            if view.public_hostname and view.public_hostname != host:
                node.public_hostname = view.public_hostname
                host = view.public_hostname
                await session.flush()
        # MediaMTX may still be installing — keep "starting" until :1935 accepts.
        # Skip TCP probe for fake/local hosts used in tests.
        probe = settings.environment not in ("test", "local") or not host.endswith(
            ".ingest.test"
        )
        if probe and not await asyncio.to_thread(rtmp_port_open, host):
            launched_at = node.launched_at or node.created_at
            if launched_at is not None and launched_at.tzinfo is None:
                launched_at = launched_at.replace(tzinfo=UTC)
            still_booting = (
                launched_at is not None and datetime.now(UTC) - launched_at < timedelta(minutes=3)
            )
            if still_booting:
                return ResolveResult(
                    status="starting",
                    ingest_api_url=api,
                    rtmp_url=rtmp_url_for_host(host),
                    analysis_url=analysis_url_for_host(host),
                    public_hostname=host,
                    node_id=node.id,
                    message=(
                        "Instance allumée — MediaMTX démarre (≈1 min). "
                        "Collez cette URL dans OBS dès que le statut passe à prêt."
                    ),
                )
            # Public IP is recorded but nothing listens: the spot was reclaimed.
            log.warning("ingest_spot_unreachable", host=host, node_id=str(node.id))
            node.status = IngestNodeStatus.LOST
            node.public_hostname = None
            node.terminated_at = datetime.now(UTC)
            await session.flush()
            try:
                node = await ensure_dedicated_node(
                    session,
                    settings,
                    organization_id=organization_id,
                    start=True,
                    additional=new_server,
                )
            except PermissionDeniedError:
                raise
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
            return await resolve_for_organization(
                session, settings, organization_id=organization_id, new_server=new_server
            )
        return ResolveResult(
            status="ready",
            ingest_api_url=api,
            rtmp_url=rtmp_url_for_host(host),
            analysis_url=analysis_url_for_host(host),
            public_hostname=host,
            node_id=node.id,
            message="Serveur prêt. Collez cette URL dans OBS — un live, une IP.",
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
    """After RTMP silence: terminate idle spots once `margin` has elapsed.

    A spot that still has an open live stays up.
    """
    busy = await open_node_ids(session, organization_id)
    marked: IngestNode | None = None
    when = (datetime.now(UTC) + margin).isoformat()
    for node in await list_active_dedicated_nodes(session, organization_id):
        if node.id in busy or node.status is IngestNodeStatus.TERMINATED:
            continue
        details = _details(node)
        details["terminate_after"] = when
        node.details = details
        node.status = IngestNodeStatus.DRAINING
        marked = node
    if marked is not None:
        await session.flush()
    return marked


async def cancel_idle_termination(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    node_id: uuid.UUID | None = None,
) -> None:
    nodes = await list_active_dedicated_nodes(session, organization_id)
    changed = False
    for node in nodes:
        if node_id is not None and node.id != node_id:
            continue
        details = _details(node)
        if "terminate_after" not in details and node.status is not IngestNodeStatus.DRAINING:
            continue
        details.pop("terminate_after", None)
        node.details = details
        if node.status is IngestNodeStatus.DRAINING and node.public_hostname:
            node.status = IngestNodeStatus.READY
        changed = True
    if changed:
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
