"""Personal data rights (GDPR): export and erasure of an account's data.

Both walk the ORM metadata instead of a hand-written table list: a table
added later with an `organization_id` column is exported and erased
automatically, so these rights cannot silently fall behind the schema.
"""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Any

import structlog
from sqlalchemy import Table, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
)
from app.models import Base
from app.models.billing import Subscription
from app.models.clips import StorageAsset
from app.models.enums import (
    ActorType,
    AssetKind,
    AssetStatus,
    NotificationSeverity,
    OrganizationStatus,
    SessionRevokeReason,
    UserStatus,
)
from app.models.identity import AuthSession, Organization, User
from app.models.system import AuditLog, Task
from app.security import rate_limit as limits
from app.security.passwords import verify_password
from app.services.audit import RequestMeta, audit
from app.services.auth import Principal
from app.services.notifications import notify
from app.storage.s3 import EXPORTS_PREFIX, tenant_key
from app.tasks.queue import enqueue

log = structlog.get_logger(__name__)

EXPORT_FORMAT_VERSION = 1
# Secrets and credentials are not personal data to hand out: never exported.
_NEVER_EXPORTED = frozenset(
    {
        "password_hash",
        "token_hash",
        "key_hash",
        "access_token_encrypted",
        "refresh_token_encrypted",
    }
)
# Operational tables holding nothing about the person.
_NOT_EXPORTED_TABLES = frozenset({"tasks", "cost_records", "refresh_tokens", "auth_tokens"})
_MAX_ROWS_PER_TABLE = 20_000


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | list | dict):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    # UUID, Decimal, IP addresses and any other scalar: their text form.
    return str(value)


async def _dump(session: AsyncSession, table: Table, condition: Any) -> list[dict[str, Any]]:
    columns = [column for column in table.columns if column.name not in _NEVER_EXPORTED]
    rows = await session.execute(select(*columns).where(condition).limit(_MAX_ROWS_PER_TABLE))
    return [{key: _jsonable(value) for key, value in row._mapping.items()} for row in rows]


async def build_export(
    session: AsyncSession, *, user_id: uuid.UUID, organization_id: uuid.UUID
) -> dict[str, Any]:
    """Collect everything stored about a user and their organization."""
    tables = Base.metadata.tables
    document: dict[str, Any] = {
        "format_version": EXPORT_FORMAT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": str(user_id),
        "organization_id": str(organization_id),
        "data": {},
    }
    data: dict[str, Any] = document["data"]
    data["users"] = await _dump(session, tables["users"], tables["users"].c.id == user_id)
    data["organizations"] = await _dump(
        session, tables["organizations"], tables["organizations"].c.id == organization_id
    )
    for name, table in sorted(tables.items()):
        if name in _NOT_EXPORTED_TABLES or name in data:
            continue
        if "organization_id" in table.c:
            condition = table.c.organization_id == organization_id
            if name == "audit_logs":
                condition = condition | (table.c.actor_user_id == user_id)
            data[name] = await _dump(session, table, condition)
        elif "user_id" in table.c:
            data[name] = await _dump(session, table, table.c.user_id == user_id)
    return document


def _require_storage(ctx: AppContext) -> None:
    if ctx.storage is None:
        raise ServiceUnavailableError(
            "Le stockage de fichiers n'est pas encore activé sur cette plateforme.",
            code="storage_unavailable",
        )


def _require_owner(principal: Principal) -> None:
    if not principal.can_manage_organization:
        raise PermissionDeniedError(
            "Seul un administrateur de l'espace peut effectuer cette action.",
            code="insufficient_role",
        )


async def request_export(ctx: AppContext, principal: Principal, meta: RequestMeta) -> uuid.UUID:
    """Register an export and queue its generation. Returns the asset id."""
    _require_storage(ctx)
    _require_owner(principal)
    await ctx.rate_limiter.check(limits.DATA_EXPORT_PER_ORG, str(principal.organization_id))
    assert ctx.storage is not None  # noqa: S101 - narrowed by _require_storage
    async with ctx.db.system_tx() as session:
        asset = StorageAsset(
            organization_id=principal.organization_id,
            kind=AssetKind.DATA_EXPORT,
            status=AssetStatus.PENDING,
            bucket=ctx.storage.bucket,
            key="pending",
            content_type="application/json",
            created_by_user_id=principal.user_id,
        )
        session.add(asset)
        await session.flush()
        asset.key = tenant_key(principal.organization_id, EXPORTS_PREFIX, f"{asset.id}.json")
        await enqueue(
            session,
            "account.export_data",
            {
                "asset_id": str(asset.id),
                "user_id": str(principal.user_id),
                "organization_id": str(principal.organization_id),
            },
            idempotency_key=f"account.export_data:{asset.id}",
            organization_id=principal.organization_id,
        )
        audit(
            session,
            "account.export_requested",
            meta=meta,
            actor_user_id=principal.user_id,
            organization_id=principal.organization_id,
            target_type="storage_asset",
            target_id=asset.id,
        )
        return asset.id


async def generate_export(
    ctx: AppContext, *, asset_id: uuid.UUID, user_id: uuid.UUID, organization_id: uuid.UUID
) -> None:
    """Task body: build the JSON document, store it privately, mark it ready."""
    if ctx.storage is None:
        raise RuntimeError("Object storage is not configured")
    async with ctx.db.system_tx() as session:
        asset = await session.get(StorageAsset, asset_id)
        if asset is None or asset.organization_id != organization_id:
            return  # the account was deleted meanwhile
        key = asset.key
        document = await build_export(session, user_id=user_id, organization_id=organization_id)
    body = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    await ctx.storage.put_object(
        key, body, content_type="application/json; charset=utf-8", short_retention=True
    )

    now = datetime.now(UTC)
    async with ctx.db.system_tx() as session:
        asset = await session.get(StorageAsset, asset_id)
        if asset is None:
            await ctx.storage.delete_object(key)
            return
        asset.status = AssetStatus.AVAILABLE
        asset.size_bytes = len(body)
        asset.checksum_sha256 = hashlib.sha256(body).hexdigest()
        asset.expires_at = now + timedelta(days=ctx.settings.data_export_ttl_days)
        await notify(
            session,
            organization_id=organization_id,
            user_id=user_id,
            kind="account.export_ready",
            severity=NotificationSeverity.SUCCESS,
            title="Votre export de données est prêt",
            body=(
                "Téléchargez-le depuis les paramètres. Il sera supprimé automatiquement "
                f"dans {ctx.settings.data_export_ttl_days} jours."
            ),
            data={"asset_id": str(asset_id)},
            dedupe_key=f"export-ready:{asset_id}",
        )


async def list_exports(session: AsyncSession, organization_id: uuid.UUID) -> list[StorageAsset]:
    """Tenant transaction: row-level security bounds the result to the caller."""
    result = await session.execute(
        select(StorageAsset)
        .where(
            StorageAsset.organization_id == organization_id,
            StorageAsset.kind == AssetKind.DATA_EXPORT,
            StorageAsset.status.in_([AssetStatus.PENDING, AssetStatus.AVAILABLE]),
        )
        .order_by(StorageAsset.created_at.desc())
        .limit(20)
    )
    return list(result.scalars())


async def export_download_url(ctx: AppContext, principal: Principal, asset_id: uuid.UUID) -> str:
    _require_storage(ctx)
    _require_owner(principal)
    assert ctx.storage is not None  # noqa: S101 - narrowed by _require_storage
    # Looked up through the tenant-scoped role: an id belonging to another
    # organization is simply not found.
    async with ctx.db.tenant_tx(principal.tenant) as session:
        asset = (
            await session.execute(
                select(StorageAsset).where(
                    StorageAsset.id == asset_id, StorageAsset.kind == AssetKind.DATA_EXPORT
                )
            )
        ).scalar_one_or_none()
    if asset is None:
        raise NotFoundError("Export introuvable.", code="export_not_found")
    if asset.status is not AssetStatus.AVAILABLE or (
        asset.expires_at is not None and asset.expires_at <= datetime.now(UTC)
    ):
        raise ConflictError("Cet export n'est pas disponible.", code="export_not_available")
    return await ctx.storage.presigned_download_url(
        asset.key, expires_seconds=300, filename=f"streamclip-export-{asset.created_at:%Y%m%d}.json"
    )


async def request_account_deletion(
    ctx: AppContext, principal: Principal, *, password: str, meta: RequestMeta
) -> None:
    """Close the account immediately and queue the erasure of its data."""
    _require_owner(principal)
    async with ctx.db.system_tx() as session:
        user = await session.get_one(User, principal.user_id)
    if not await verify_password(user.password_hash, password):
        raise PermissionDeniedError("Mot de passe incorrect.", code="invalid_current_password")

    now = datetime.now(UTC)
    async with ctx.db.system_tx() as session:
        user = await session.get_one(User, principal.user_id, with_for_update=True)
        organization = await session.get_one(Organization, principal.organization_id)
        user.status = UserStatus.PENDING_DELETION
        user.deletion_requested_at = now
        organization.status = OrganizationStatus.PENDING_DELETION
        organization.deletion_requested_at = now
        sessions = await session.execute(
            select(AuthSession).where(
                AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
            )
        )
        for auth_session in sessions.scalars():
            auth_session.revoked_at = now
            auth_session.revoke_reason = SessionRevokeReason.USER_REVOKED
        await enqueue(
            session,
            "account.delete",
            {"user_id": str(user.id), "organization_id": str(organization.id)},
            idempotency_key=f"account.delete:{organization.id}",
            max_attempts=10,
        )
        audit(
            session,
            "account.deletion_requested",
            meta=meta,
            actor_user_id=user.id,
            organization_id=organization.id,
        )


async def erase_account(ctx: AppContext, *, user_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    """Task body: erase an organization, its owner and everything they own.

    Order matters and every step is repeatable: stop the billing first, then
    remove stored files, then the database rows. Invoices stay at the payment
    provider, as accounting law requires.
    """
    async with ctx.db.system_tx() as session:
        organization = await session.get(Organization, organization_id)
        if organization is None:
            return  # already erased by a previous attempt
        if organization.status is not OrganizationStatus.PENDING_DELETION:
            raise RuntimeError("Refusing to erase an organization not pending deletion")
        rows = await session.execute(
            select(Subscription.stripe_subscription_id).where(
                Subscription.organization_id == organization_id,
                Subscription.stripe_subscription_id.is_not(None),
                Subscription.ended_at.is_(None),
            )
        )
        subscription_ids = [value for value in rows.scalars() if value]

    if subscription_ids and ctx.stripe is None:
        raise RuntimeError("An active subscription exists but Stripe is not configured")
    for subscription_id in subscription_ids:
        assert ctx.stripe is not None  # noqa: S101 - checked above
        await ctx.stripe.cancel_subscription(subscription_id)

    deleted_objects = 0
    if ctx.storage is not None:
        deleted_objects = await ctx.storage.delete_tenant_objects(organization_id)

    async with ctx.db.system_tx() as session:
        # ON DELETE CASCADE removes every tenant-owned row with the organization.
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.execute(delete(User).where(User.id == user_id))
        # Queue entries about the account (soft references), except this very
        # erasure task, which the queue still has to mark as done.
        await session.execute(
            delete(Task).where(
                (Task.organization_id == organization_id)
                | (Task.payload["user_id"].astext == str(user_id)),
                Task.kind != "account.delete",
            )
        )
        # The trail of what happened is kept, without personal data.
        await session.execute(
            update(AuditLog)
            .where(
                (AuditLog.organization_id == organization_id) | (AuditLog.actor_user_id == user_id)
            )
            .values(ip=None, user_agent=None)
        )
        audit(
            session,
            "account.erased",
            actor_type=ActorType.SYSTEM,
            organization_id=organization_id,
            target_type="organization",
            target_id=organization_id,
            details={"storage_objects_deleted": deleted_objects},
        )
    log.info("account_erased", organization_id=str(organization_id), objects=deleted_objects)
