"""Back-office operations. Every mutation is audited with the acting admin."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from app.context import AppContext
from app.core.errors import ConflictError, NotFoundError
from app.models.billing import Plan, Subscription
from app.models.enums import ActorType, PlatformRole, SessionRevokeReason, UserStatus
from app.models.identity import AuthSession, Membership, User
from app.services.audit import RequestMeta, audit
from app.services.auth import Principal


async def list_users(
    ctx: AppContext, *, limit: int, cursor: uuid.UUID | None, search: str | None
) -> tuple[list[dict[str, Any]], uuid.UUID | None]:
    """Newest first, keyset-paginated on the (time-ordered) user id."""
    statement = (
        select(User, Membership.organization_id, Plan.code)
        .outerjoin(Membership, Membership.user_id == User.id)
        .outerjoin(
            Subscription,
            (Subscription.organization_id == Membership.organization_id)
            & Subscription.ended_at.is_(None),
        )
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
        .order_by(User.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(User.id < cursor)
    if search:
        escaped = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(User.email.like(f"%{escaped}%", escape="\\"))
    async with ctx.db.system_tx() as session:
        rows = (await session.execute(statement)).all()
    items: list[dict[str, Any]] = [
        {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status.value,
            "platform_role": user.platform_role.value,
            "email_verified": user.email_verified_at is not None,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
            "organization_id": organization_id,
            "plan_code": plan_code,
        }
        for user, organization_id, plan_code in rows[:limit]
    ]
    next_cursor = items[-1]["id"] if len(rows) > limit and items else None
    return items, next_cursor


async def set_user_suspended(
    ctx: AppContext,
    admin: Principal,
    user_id: uuid.UUID,
    *,
    suspended: bool,
    reason: str | None,
    meta: RequestMeta,
) -> None:
    now = datetime.now(UTC)
    async with ctx.db.system_tx() as session:
        user = await session.get(User, user_id, with_for_update=True)
        if user is None:
            raise NotFoundError("Utilisateur introuvable.", code="user_not_found")
        if suspended:
            if user.id == admin.user_id:
                raise ConflictError(
                    "Vous ne pouvez pas suspendre votre propre compte.", code="cannot_suspend_self"
                )
            if user.platform_role is PlatformRole.ADMIN:
                raise ConflictError(
                    "Un administrateur ne peut pas être suspendu.", code="cannot_suspend_admin"
                )
            if user.status is not UserStatus.ACTIVE:
                raise ConflictError("Ce compte n'est pas actif.", code="user_not_active")
            user.status = UserStatus.SUSPENDED
            user.suspended_at = now
            user.suspended_reason = reason
            # Effective immediately: open sessions stop working on their next request.
            await session.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now, revoke_reason=SessionRevokeReason.ACCOUNT_SUSPENDED)
            )
        else:
            if user.status is not UserStatus.SUSPENDED:
                raise ConflictError("Ce compte n'est pas suspendu.", code="user_not_suspended")
            user.status = UserStatus.ACTIVE
            user.suspended_at = None
            user.suspended_reason = None
        audit(
            session,
            "admin.user_suspended" if suspended else "admin.user_reactivated",
            meta=meta,
            actor_type=ActorType.ADMIN,
            actor_user_id=admin.user_id,
            target_type="user",
            target_id=user.id,
            details={"reason": reason} if reason else None,
        )
