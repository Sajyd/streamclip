"""Task handlers. Importing this module registers them on the queue.

Handlers are idempotent: the queue guarantees at-least-once execution.
"""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import structlog
from sqlalchemy import delete, or_, select, update

from app.context import AppContext
from app.email import templates
from app.models.clips import StorageAsset
from app.models.enums import AssetStatus, AuthTokenPurpose, TaskStatus, UserStatus
from app.models.identity import AuthSession, AuthToken, RefreshToken, User
from app.models.system import AuditLog, RateLimitCounter, Task
from app.services import account_data
from app.services.auth import issue_auth_token
from app.tasks.queue import ClaimedTask, PermanentTaskError, task_handler

log = structlog.get_logger(__name__)

AUDIT_PII_RETENTION_DAYS = 365


def _uuid(task: ClaimedTask, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(task.payload[field]))
    except (KeyError, ValueError) as exc:
        raise PermanentTaskError(f"Invalid payload field {field!r}") from exc


def _link(ctx: AppContext, path: str, token: str) -> str:
    return f"{ctx.settings.public_app_url.rstrip('/')}{path}?{urlencode({'token': token})}"


async def _active_user(ctx: AppContext, user_id: uuid.UUID) -> User | None:
    async with ctx.db.system_tx() as session:
        user = await session.get(User, user_id)
    return user if user is not None and user.status is UserStatus.ACTIVE else None


@task_handler("email.verification")
async def send_verification_email(ctx: AppContext, task: ClaimedTask) -> None:
    user = await _active_user(ctx, _uuid(task, "user_id"))
    if user is None or user.email_verified_at is not None:
        return
    ttl_hours = ctx.settings.email_verification_ttl_hours
    # The raw token is created here, right before sending: it never sits in
    # the queue, only its hash is stored.
    async with ctx.db.system_tx() as session:
        token = await issue_auth_token(
            session, user, AuthTokenPurpose.EMAIL_VERIFICATION, timedelta(hours=ttl_hours)
        )
    await ctx.mailer.send(
        templates.verification_email(user.email, _link(ctx, "/verify-email", token), ttl_hours)
    )


@task_handler("email.password_reset")
async def send_password_reset_email(ctx: AppContext, task: ClaimedTask) -> None:
    user = await _active_user(ctx, _uuid(task, "user_id"))
    if user is None:
        return
    ttl_minutes = ctx.settings.password_reset_ttl_minutes
    async with ctx.db.system_tx() as session:
        token = await issue_auth_token(
            session, user, AuthTokenPurpose.PASSWORD_RESET, timedelta(minutes=ttl_minutes)
        )
    await ctx.mailer.send(
        templates.password_reset_email(
            user.email, _link(ctx, "/reset-password", token), ttl_minutes
        )
    )


@task_handler("email.password_changed")
async def send_password_changed_email(ctx: AppContext, task: ClaimedTask) -> None:
    user = await _active_user(ctx, _uuid(task, "user_id"))
    if user is not None:
        await ctx.mailer.send(templates.password_changed_email(user.email))


@task_handler("account.export_data")
async def export_account_data(ctx: AppContext, task: ClaimedTask) -> None:
    await account_data.generate_export(
        ctx,
        asset_id=_uuid(task, "asset_id"),
        user_id=_uuid(task, "user_id"),
        organization_id=_uuid(task, "organization_id"),
    )


@task_handler("account.delete")
async def delete_account(ctx: AppContext, task: ClaimedTask) -> None:
    await account_data.erase_account(
        ctx, user_id=_uuid(task, "user_id"), organization_id=_uuid(task, "organization_id")
    )


@task_handler("maintenance.cleanup")
async def cleanup(ctx: AppContext, _task: ClaimedTask) -> None:
    """Housekeeping: drop expired secrets and counters, enforce retention."""
    now = datetime.now(UTC)
    removed: dict[str, int] = {}

    def count(result: object) -> int:
        return int(getattr(result, "rowcount", 0) or 0)

    async with ctx.db.system_tx() as session:
        removed["refresh_tokens"] = count(
            await session.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < now - timedelta(days=1))
            )
        )
        removed["auth_tokens"] = count(
            await session.execute(
                delete(AuthToken).where(AuthToken.expires_at < now - timedelta(days=7))
            )
        )
        removed["auth_sessions"] = count(
            await session.execute(
                delete(AuthSession).where(
                    or_(
                        AuthSession.expires_at < now - timedelta(days=30),
                        AuthSession.revoked_at < now - timedelta(days=30),
                    )
                )
            )
        )
        removed["rate_limit_counters"] = count(
            await session.execute(delete(RateLimitCounter).where(RateLimitCounter.expires_at < now))
        )
        removed["tasks"] = count(
            await session.execute(
                delete(Task).where(
                    Task.status == TaskStatus.SUCCEEDED,
                    Task.finished_at < now - timedelta(days=7),
                )
            )
        )
        # Data minimisation: network identifiers leave the audit trail after a year.
        removed["audit_pii"] = count(
            await session.execute(
                update(AuditLog)
                .where(
                    AuditLog.occurred_at < now - timedelta(days=AUDIT_PII_RETENTION_DAYS),
                    AuditLog.ip.is_not(None),
                )
                .values(ip=None, user_agent=None)
            )
        )
        expired_assets = (
            await session.execute(
                select(StorageAsset.id, StorageAsset.key)
                .where(StorageAsset.status == AssetStatus.AVAILABLE, StorageAsset.expires_at < now)
                .limit(500)
            )
        ).all()

    # Delete the object first, then record it: a crash in between only means
    # the (idempotent) deletion is repeated on the next run.
    if ctx.storage is not None:
        for asset_id, key in expired_assets:
            await ctx.storage.delete_object(key)
            async with ctx.db.system_tx() as session:
                await session.execute(
                    update(StorageAsset)
                    .where(StorageAsset.id == asset_id)
                    .values(status=AssetStatus.DELETED, deleted_at=now)
                )
        removed["storage_assets"] = len(expired_assets)
    log.info("maintenance_cleanup", **removed)
