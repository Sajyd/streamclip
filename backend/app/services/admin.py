"""Back-office operations. Every mutation is audited with the acting admin."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select, update

from app.context import AppContext
from app.core.errors import ConflictError, NotFoundError
from app.models.billing import Plan, Subscription
from app.models.clips import Clip, ClipFeedbackEvent, StorageAsset
from app.models.enums import (
    ActorType,
    AssetKind,
    ClipFeedbackAction,
    ClipStatus,
    PlatformRole,
    SessionRevokeReason,
    StreamSessionStatus,
    SubscriptionStatus,
    UserStatus,
)
from app.models.identity import AuthSession, Membership, Organization, User
from app.models.media import StreamSession
from app.services.audit import RequestMeta, audit
from app.services.auth import Principal, normalize_email

AnalyticsPeriod = Literal["day", "week", "month", "year"]

_PERIOD_CONFIG: dict[AnalyticsPeriod, tuple[timedelta, str, int]] = {
    # (window length, date_trunc unit, expected bucket count hint)
    "day": (timedelta(days=1), "hour", 24),
    "week": (timedelta(days=7), "day", 7),
    "month": (timedelta(days=30), "day", 30),
    "year": (timedelta(days=365), "month", 12),
}

_MRR_STATUSES = (
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.TRIALING,
    SubscriptionStatus.PAST_DUE,
)

_LIVE_STATUSES = (
    StreamSessionStatus.PENDING,
    StreamSessionStatus.LIVE,
    StreamSessionStatus.INTERRUPTED,
    StreamSessionStatus.FINALIZING,
)


def _period_bounds(
    period: AnalyticsPeriod, *, now: datetime | None = None
) -> tuple[datetime, datetime, datetime, str]:
    """Return (range_start, range_end, previous_start, trunc_unit)."""
    end = now or datetime.now(UTC)
    window, trunc, _ = _PERIOD_CONFIG[period]
    start = end - window
    previous_start = start - window
    return start, end, previous_start, trunc


def _owner_email_subquery() -> Any:
    return (
        select(Organization.id.label("organization_id"), User.email.label("owner_email"))
        .join(User, User.id == Organization.owner_user_id)
        .subquery()
    )


async def ensure_platform_admins(ctx: AppContext) -> int:
    """Grant admin to every address listed in PLATFORM_ADMIN_EMAILS (idempotent)."""
    raw = (ctx.settings.platform_admin_emails or "").strip()
    if not raw:
        return 0
    emails = [normalize_email(part) for part in raw.split(",") if part.strip()]
    if not emails:
        return 0
    promoted = 0
    async with ctx.db.system_tx() as session:
        users = (
            await session.execute(select(User).where(User.email.in_(emails)))
        ).scalars().all()
        for user in users:
            if user.platform_role is PlatformRole.ADMIN:
                continue
            user.platform_role = PlatformRole.ADMIN
            audit(
                session,
                "admin.role_granted",
                actor_type=ActorType.SYSTEM,
                target_type="user",
                target_id=user.id,
                details={"role": PlatformRole.ADMIN.value, "via": "bootstrap"},
            )
            promoted += 1
    return promoted


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


async def _count_between(
    session: Any, model: Any, column: Any, start: datetime, end: datetime, *extra: Any
) -> int:
    statement = select(func.count()).select_from(model).where(column >= start, column < end, *extra)
    return int((await session.execute(statement)).scalar_one())


async def _series(
    session: Any,
    *,
    column: Any,
    start: datetime,
    end: datetime,
    trunc: str,
    extra: tuple[Any, ...] = (),
) -> dict[datetime, int]:
    bucket = func.date_trunc(trunc, column)
    statement = (
        select(bucket.label("bucket"), func.count().label("n"))
        .where(column >= start, column < end, *extra)
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(statement)).all()
    out: dict[datetime, int] = {}
    for bucket_at, n in rows:
        if bucket_at.tzinfo is None:
            bucket_at = bucket_at.replace(tzinfo=UTC)
        out[bucket_at] = int(n)
    return out


def _fill_series(
    start: datetime, end: datetime, trunc: str, counts: dict[datetime, int]
) -> list[dict[str, Any]]:
    """Emit every bucket in [start, end) even when the count is zero."""
    step = {
        "hour": timedelta(hours=1),
        "day": timedelta(days=1),
        "month": timedelta(days=32),  # advanced via date_trunc below
    }[trunc]
    # Align to trunc boundary the same way PostgreSQL date_trunc does.
    cursor = _truncate(start, trunc)
    end_aligned = _truncate(end, trunc)
    items: list[dict[str, Any]] = []
    guard = 0
    while cursor < end and cursor <= end_aligned and guard < 400:
        items.append({"bucket_start": cursor, "count": counts.get(cursor, 0)})
        if trunc == "month":
            year = cursor.year + (1 if cursor.month == 12 else 0)
            month = 1 if cursor.month == 12 else cursor.month + 1
            cursor = cursor.replace(year=year, month=month, day=1)
        else:
            cursor = cursor + step
        guard += 1
    return items


def _truncate(value: datetime, trunc: str) -> datetime:
    value = value.astimezone(UTC)
    if trunc == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    if trunc == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if trunc == "month":
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(trunc)


async def _mrr_cents(session: Any) -> tuple[int, int, list[dict[str, Any]]]:
    """Current MRR (cents), paying subscriber count, and breakdown by plan."""
    statement = (
        select(
            Plan.code,
            Plan.name,
            Plan.price_cents,
            Plan.currency,
            func.count(Subscription.id).label("subscribers"),
            func.coalesce(func.sum(Plan.price_cents), 0).label("mrr_cents"),
        )
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.ended_at.is_(None),
            Subscription.status.in_(_MRR_STATUSES),
            Plan.price_cents > 0,
        )
        .group_by(Plan.code, Plan.name, Plan.price_cents, Plan.currency)
        .order_by(Plan.price_cents.desc())
    )
    rows = (await session.execute(statement)).all()
    plans = [
        {
            "plan_code": code,
            "plan_name": name,
            "price_cents": price_cents,
            "currency": currency,
            "subscribers": int(subscribers),
            "mrr_cents": int(mrr),
        }
        for code, name, price_cents, currency, subscribers, mrr in rows
    ]
    total_mrr = sum(item["mrr_cents"] for item in plans)
    paying = sum(item["subscribers"] for item in plans)
    return total_mrr, paying, plans


async def analytics(ctx: AppContext, *, period: AnalyticsPeriod) -> dict[str, Any]:
    start, end, previous_start, trunc = _period_bounds(period)
    async with ctx.db.system_tx() as session:
        users_now = await _count_between(session, User, User.created_at, start, end)
        users_prev = await _count_between(
            session, User, User.created_at, previous_start, start
        )
        users_total = int((await session.execute(select(func.count()).select_from(User))).scalar_one())

        paid_filter = (
            Subscription.ended_at.is_(None),
            Subscription.status.in_(_MRR_STATUSES),
            Plan.price_cents > 0,
        )
        paid_new = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Subscription)
                    .join(Plan, Plan.id == Subscription.plan_id)
                    .where(
                        Subscription.created_at >= start,
                        Subscription.created_at < end,
                        *paid_filter,
                    )
                )
            ).scalar_one()
        )
        paid_prev = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Subscription)
                    .join(Plan, Plan.id == Subscription.plan_id)
                    .where(
                        Subscription.created_at >= previous_start,
                        Subscription.created_at < start,
                        *paid_filter,
                    )
                )
            ).scalar_one()
        )

        lives_started = await _count_between(
            session,
            StreamSession,
            func.coalesce(StreamSession.started_at, StreamSession.created_at),
            start,
            end,
        )
        lives_started_prev = await _count_between(
            session,
            StreamSession,
            func.coalesce(StreamSession.started_at, StreamSession.created_at),
            previous_start,
            start,
        )
        lives_active = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(StreamSession)
                    .where(StreamSession.status.in_(_LIVE_STATUSES))
                )
            ).scalar_one()
        )

        clips_now = await _count_between(
            session,
            Clip,
            Clip.created_at,
            start,
            end,
            Clip.status != ClipStatus.DELETED,
        )
        clips_prev = await _count_between(
            session,
            Clip,
            Clip.created_at,
            previous_start,
            start,
            Clip.status != ClipStatus.DELETED,
        )
        clips_total = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Clip)
                    .where(Clip.status != ClipStatus.DELETED)
                )
            ).scalar_one()
        )

        exports_now = await _count_between(
            session,
            StorageAsset,
            StorageAsset.created_at,
            start,
            end,
            StorageAsset.kind == AssetKind.DATA_EXPORT,
        )
        exports_prev = await _count_between(
            session,
            StorageAsset,
            StorageAsset.created_at,
            previous_start,
            start,
            StorageAsset.kind == AssetKind.DATA_EXPORT,
        )
        downloads_now = await _count_between(
            session,
            ClipFeedbackEvent,
            ClipFeedbackEvent.created_at,
            start,
            end,
            ClipFeedbackEvent.action == ClipFeedbackAction.DOWNLOADED,
        )
        downloads_prev = await _count_between(
            session,
            ClipFeedbackEvent,
            ClipFeedbackEvent.created_at,
            previous_start,
            start,
            ClipFeedbackEvent.action == ClipFeedbackAction.DOWNLOADED,
        )

        mrr_cents, paying_subscribers, plan_breakdown = await _mrr_cents(session)

        user_series = await _series(session, column=User.created_at, start=start, end=end, trunc=trunc)
        clip_series = await _series(
            session,
            column=Clip.created_at,
            start=start,
            end=end,
            trunc=trunc,
            extra=(Clip.status != ClipStatus.DELETED,),
        )
        live_series = await _series(
            session,
            column=func.coalesce(StreamSession.started_at, StreamSession.created_at),
            start=start,
            end=end,
            trunc=trunc,
        )
        export_series = await _series(
            session,
            column=StorageAsset.created_at,
            start=start,
            end=end,
            trunc=trunc,
            extra=(StorageAsset.kind == AssetKind.DATA_EXPORT,),
        )
        download_series = await _series(
            session,
            column=ClipFeedbackEvent.created_at,
            start=start,
            end=end,
            trunc=trunc,
            extra=(ClipFeedbackEvent.action == ClipFeedbackAction.DOWNLOADED,),
        )

    users_filled = _fill_series(start, end, trunc, user_series)
    clips_filled = _fill_series(start, end, trunc, clip_series)
    lives_filled = _fill_series(start, end, trunc, live_series)
    exports_filled = _fill_series(start, end, trunc, export_series)
    downloads_filled = _fill_series(start, end, trunc, download_series)

    series = [
        {
            "bucket_start": bucket["bucket_start"],
            "users_new": bucket["count"],
            "clips_created": clips_filled[index]["count"],
            "lives_started": lives_filled[index]["count"],
            "exports_created": exports_filled[index]["count"],
            "clip_downloads": downloads_filled[index]["count"],
        }
        for index, bucket in enumerate(users_filled)
    ]

    return {
        "period": period,
        "range_start": start,
        "range_end": end,
        "previous_range_start": previous_start,
        "currency": "eur",
        "totals": {
            "users_total": users_total,
            "users_new": users_now,
            "users_new_previous": users_prev,
            "paying_subscribers": paying_subscribers,
            "subscriptions_new": paid_new,
            "subscriptions_new_previous": paid_prev,
            "mrr_cents": mrr_cents,
            "lives_active": lives_active,
            "lives_started": lives_started,
            "lives_started_previous": lives_started_prev,
            "clips_total": clips_total,
            "clips_created": clips_now,
            "clips_created_previous": clips_prev,
            "exports_created": exports_now,
            "exports_created_previous": exports_prev,
            "clip_downloads": downloads_now,
            "clip_downloads_previous": downloads_prev,
        },
        "plans": plan_breakdown,
        "series": series,
    }


async def list_subscriptions(
    ctx: AppContext, *, limit: int, cursor: uuid.UUID | None, search: str | None
) -> tuple[list[dict[str, Any]], uuid.UUID | None, dict[str, Any]]:
    owner = _owner_email_subquery()
    statement = (
        select(
            Subscription,
            Plan.code,
            Plan.name,
            Plan.price_cents,
            Plan.currency,
            Organization.name,
            owner.c.owner_email,
        )
        .join(Plan, Plan.id == Subscription.plan_id)
        .join(Organization, Organization.id == Subscription.organization_id)
        .outerjoin(owner, owner.c.organization_id == Organization.id)
        .where(Subscription.ended_at.is_(None))
        .order_by(Subscription.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(Subscription.id < cursor)
    if search:
        escaped = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(owner.c.owner_email.like(f"%{escaped}%", escape="\\"))

    async with ctx.db.system_tx() as session:
        rows = (await session.execute(statement)).all()
        mrr_cents, paying, plans = await _mrr_cents(session)
        free_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Subscription)
                    .join(Plan, Plan.id == Subscription.plan_id)
                    .where(
                        Subscription.ended_at.is_(None),
                        Plan.price_cents == 0,
                    )
                )
            ).scalar_one()
        )

    items = [
        {
            "id": sub.id,
            "organization_id": sub.organization_id,
            "organization_name": org_name,
            "owner_email": owner_email,
            "plan_code": plan_code,
            "plan_name": plan_name,
            "price_cents": price_cents,
            "currency": currency,
            "status": sub.status.value,
            "is_paid": price_cents > 0,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "payment_failed": sub.payment_failed_at is not None,
            "created_at": sub.created_at,
        }
        for sub, plan_code, plan_name, price_cents, currency, org_name, owner_email in rows[:limit]
    ]
    next_cursor = items[-1]["id"] if len(rows) > limit and items else None
    summary = {
        "mrr_cents": mrr_cents,
        "currency": "eur",
        "paying_subscribers": paying,
        "free_subscribers": free_count,
        "plans": plans,
    }
    return items, next_cursor, summary


async def list_lives(
    ctx: AppContext,
    *,
    limit: int,
    cursor: uuid.UUID | None,
    active_only: bool,
    search: str | None,
) -> tuple[list[dict[str, Any]], uuid.UUID | None]:
    owner = _owner_email_subquery()
    statement = (
        select(StreamSession, Organization.name, owner.c.owner_email)
        .join(Organization, Organization.id == StreamSession.organization_id)
        .outerjoin(owner, owner.c.organization_id == Organization.id)
        .order_by(StreamSession.id.desc())
        .limit(limit + 1)
    )
    if active_only:
        statement = statement.where(StreamSession.status.in_(_LIVE_STATUSES))
    if cursor is not None:
        statement = statement.where(StreamSession.id < cursor)
    if search:
        escaped = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(owner.c.owner_email.like(f"%{escaped}%", escape="\\"))

    async with ctx.db.system_tx() as session:
        rows = (await session.execute(statement)).all()

    items = [
        {
            "id": session.id,
            "organization_id": session.organization_id,
            "organization_name": org_name,
            "owner_email": owner_email,
            "status": session.status.value,
            "end_reason": session.end_reason.value if session.end_reason else None,
            "protocol": session.protocol.value if session.protocol else None,
            "title": session.title,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "last_media_at": session.last_media_at,
            "media_duration_ms": session.media_duration_ms,
            "processed_ms": session.processed_ms,
            "clips_count": session.clips_count,
            "created_at": session.created_at,
        }
        for session, org_name, owner_email in rows[:limit]
    ]
    next_cursor = items[-1]["id"] if len(rows) > limit and items else None
    return items, next_cursor


async def list_clips(
    ctx: AppContext, *, limit: int, cursor: uuid.UUID | None, search: str | None
) -> tuple[list[dict[str, Any]], uuid.UUID | None]:
    owner = _owner_email_subquery()
    statement = (
        select(Clip, Organization.name, owner.c.owner_email)
        .join(Organization, Organization.id == Clip.organization_id)
        .outerjoin(owner, owner.c.organization_id == Organization.id)
        .where(Clip.status != ClipStatus.DELETED)
        .order_by(Clip.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(Clip.id < cursor)
    if search:
        escaped = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(owner.c.owner_email.like(f"%{escaped}%", escape="\\"))

    async with ctx.db.system_tx() as session:
        rows = (await session.execute(statement)).all()

    items = [
        {
            "id": clip.id,
            "organization_id": clip.organization_id,
            "organization_name": org_name,
            "owner_email": owner_email,
            "title": clip.title,
            "status": clip.status.value,
            "category": clip.category.value,
            "score": float(clip.score),
            "start_ms": clip.start_ms,
            "end_ms": clip.end_ms,
            "duration_ms": clip.end_ms - clip.start_ms,
            "is_favorite": clip.is_favorite,
            "stream_session_id": clip.stream_session_id,
            "created_at": clip.created_at,
        }
        for clip, org_name, owner_email in rows[:limit]
    ]
    next_cursor = items[-1]["id"] if len(rows) > limit and items else None
    return items, next_cursor


async def list_exports(
    ctx: AppContext, *, limit: int, cursor: uuid.UUID | None, search: str | None
) -> tuple[list[dict[str, Any]], uuid.UUID | None]:
    """GDPR data exports and clip download events, newest first (unified feed).

    `cursor` is the id of the last item of either kind; rows strictly older than
    that item's `created_at` are returned (stable enough for admin browsing).
    """
    owner = _owner_email_subquery()
    async with ctx.db.system_tx() as session:
        before: datetime | None = None
        if cursor is not None:
            asset = await session.get(StorageAsset, cursor)
            event = None if asset else await session.get(ClipFeedbackEvent, cursor)
            before = (asset.created_at if asset else None) or (
                event.created_at if event else None
            )

        export_statement = (
            select(StorageAsset, Organization.name, owner.c.owner_email)
            .join(Organization, Organization.id == StorageAsset.organization_id)
            .outerjoin(owner, owner.c.organization_id == Organization.id)
            .where(StorageAsset.kind == AssetKind.DATA_EXPORT)
            .order_by(StorageAsset.created_at.desc(), StorageAsset.id.desc())
            .limit(limit + 1)
        )
        download_statement = (
            select(ClipFeedbackEvent, Organization.name, owner.c.owner_email, Clip.title)
            .join(Organization, Organization.id == ClipFeedbackEvent.organization_id)
            .outerjoin(owner, owner.c.organization_id == Organization.id)
            .outerjoin(Clip, Clip.id == ClipFeedbackEvent.clip_id)
            .where(ClipFeedbackEvent.action == ClipFeedbackAction.DOWNLOADED)
            .order_by(ClipFeedbackEvent.created_at.desc(), ClipFeedbackEvent.id.desc())
            .limit(limit + 1)
        )
        if before is not None:
            export_statement = export_statement.where(StorageAsset.created_at < before)
            download_statement = download_statement.where(ClipFeedbackEvent.created_at < before)
        if search:
            escaped = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            export_statement = export_statement.where(
                owner.c.owner_email.like(f"%{escaped}%", escape="\\")
            )
            download_statement = download_statement.where(
                owner.c.owner_email.like(f"%{escaped}%", escape="\\")
            )

        export_rows = (await session.execute(export_statement)).all()
        download_rows = (await session.execute(download_statement)).all()

    merged: list[dict[str, Any]] = []
    for asset, org_name, owner_email in export_rows:
        merged.append(
            {
                "id": asset.id,
                "kind": "data_export",
                "organization_id": asset.organization_id,
                "organization_name": org_name,
                "owner_email": owner_email,
                "status": asset.status.value,
                "size_bytes": asset.size_bytes,
                "clip_id": None,
                "clip_title": None,
                "created_at": asset.created_at,
                "expires_at": asset.expires_at,
            }
        )
    for event, org_name, owner_email, clip_title in download_rows:
        merged.append(
            {
                "id": event.id,
                "kind": "clip_download",
                "organization_id": event.organization_id,
                "organization_name": org_name,
                "owner_email": owner_email,
                "status": "downloaded",
                "size_bytes": None,
                "clip_id": event.clip_id,
                "clip_title": clip_title,
                "created_at": event.created_at,
                "expires_at": None,
            }
        )
    merged.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    items = merged[:limit]
    next_cursor = items[-1]["id"] if len(merged) > limit and items else None
    return items, next_cursor
