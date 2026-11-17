"""Social account connections (OAuth control plane; publishing is phase 8)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import release
from app.core.errors import AppError, ServiceUnavailableError
from app.models.clips import SocialAccount
from app.models.enums import SocialPlatform


@dataclass(frozen=True)
class SocialAccountRow:
    id: uuid.UUID
    platform: str
    status: str
    display_name: str
    connected_at: datetime


async def list_accounts(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[SocialAccountRow]:
    rows = (
        await session.execute(
            select(SocialAccount)
            .where(SocialAccount.organization_id == organization_id)
            .order_by(SocialAccount.created_at.desc())
        )
    ).scalars().all()
    return [
        SocialAccountRow(
            id=row.id,
            platform=row.platform.value,
            status=row.status.value,
            display_name=row.display_name,
            connected_at=row.created_at,
        )
        for row in rows
    ]


def require_oauth_open() -> None:
    # Social OAuth is not shipped yet; callers surface an honest error.
    if not getattr(release, "SOCIAL_OAUTH_AVAILABLE", False):
        raise ServiceUnavailableError(
            "La connexion des réseaux sociaux n'est pas encore ouverte. "
            "Vous pouvez déjà télécharger vos clips et les publier vous-même.",
            code="social_oauth_unavailable",
        )


def platform_or_raise(value: str) -> SocialPlatform:
    try:
        return SocialPlatform(value)
    except ValueError as exc:
        raise AppError(
            "Plateforme non prise en charge.",
            code="unsupported_platform",
            status_code=400,
        ) from exc
