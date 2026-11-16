"""In-app notifications."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationSeverity
from app.models.system import Notification


async def notify(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    kind: str,
    title: str,
    body: str = "",
    severity: NotificationSeverity = NotificationSeverity.INFO,
    data: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """Create a notification. With a `dedupe_key`, the same event notifies an
    organization only once, however many times it is processed."""
    await session.execute(
        insert(Notification)
        .values(
            organization_id=organization_id,
            user_id=user_id,
            kind=kind,
            severity=severity,
            title=title,
            body=body,
            data=data or {},
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=["organization_id", "dedupe_key"])
    )


async def list_notifications(
    session: AsyncSession, organization_id: uuid.UUID, *, limit: int = 30
) -> tuple[list[Notification], int]:
    """Latest notifications and the unread count (tenant transaction)."""
    rows = await session.execute(
        select(Notification)
        .where(Notification.organization_id == organization_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    unread = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.organization_id == organization_id, Notification.read_at.is_(None))
    )
    return list(rows.scalars()), int(unread.scalar_one())


async def mark_read(
    session: AsyncSession, organization_id: uuid.UUID, notification_id: uuid.UUID | None
) -> int:
    """Mark one notification (or all when `notification_id` is None) as read."""
    statement = (
        update(Notification)
        .where(Notification.organization_id == organization_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    if notification_id is not None:
        statement = statement.where(Notification.id == notification_id)
    result = await session.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)
