"""Audit trail for security-relevant and administrative operations."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import Database
from app.models.enums import ActorType, AuditOutcome
from app.models.system import AuditLog


@dataclass(frozen=True, slots=True)
class RequestMeta:
    """Where a request came from, for audit entries and session records."""

    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


def audit(
    session: AsyncSession,
    action: str,
    *,
    meta: RequestMeta | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    actor_type: ActorType = ActorType.USER,
    actor_user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry to the caller's transaction (flushed with it)."""
    meta = meta or RequestMeta()
    session.add(
        AuditLog(
            action=action,
            outcome=outcome,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=meta.ip,
            user_agent=meta.user_agent,
            request_id=meta.request_id,
            details=details or {},
        )
    )


async def audit_independent(db: Database, action: str, **kwargs: Any) -> None:
    """Record an entry in its own transaction: used for failures, whose
    business transaction is rolled back and must still leave a trace."""
    async with db.system_tx() as session:
        audit(session, action, **kwargs)
