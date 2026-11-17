"""First-run onboarding preferences (stored in user_settings.ui_preferences)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.enums import ContentCategory
from app.models.identity import OrganizationSettings, UserSettings
from app.services.audit import RequestMeta, audit

ONBOARDING_KEY = "onboarding"

REFERRAL_SOURCES = frozenset(
    {
        "youtube",
        "twitch",
        "tiktok",
        "instagram",
        "x",
        "discord",
        "friend",
        "search",
        "other",
    }
)

USAGE_OPTIONS = frozenset(
    {
        "gaming",
        "vlog",
        "podcast",
        "concert",
        "interview",
        "just_chatting",
        "irl",
        "conference",
        "other",
    }
)

SOFTWARE_OPTIONS = frozenset({"obs", "streamlabs"})

SOCIAL_PLATFORMS = frozenset({"youtube", "tiktok", "instagram"})

# Map onboarding usage labels onto the analysis ContentCategory enum.
USAGE_TO_CATEGORY: dict[str, ContentCategory] = {
    "gaming": ContentCategory.GAMING,
    "vlog": ContentCategory.IRL,
    "podcast": ContentCategory.PODCAST,
    "concert": ContentCategory.MUSIC,
    "interview": ContentCategory.INTERVIEW,
    "just_chatting": ContentCategory.JUST_CHATTING,
    "irl": ContentCategory.IRL,
    "conference": ContentCategory.CONFERENCE,
    "other": ContentCategory.OTHER,
}

DEFAULT_ONBOARDING: dict[str, Any] = {
    "completed": False,
    "step": "welcome",
    "referral_source": None,
    "usage": None,
    "software": None,
    "social_platforms": [],
    "ingest_ready": False,
    "premium_choice": None,  # "free" | "premium" | None
    "live_detected": False,
    "completed_at": None,
}


def normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(DEFAULT_ONBOARDING)
    if not isinstance(raw, dict):
        return data
    blob = raw.get(ONBOARDING_KEY)
    if not isinstance(blob, dict):
        return data
    if isinstance(blob.get("completed"), bool):
        data["completed"] = blob["completed"]
    if isinstance(blob.get("step"), str) and blob["step"]:
        data["step"] = blob["step"][:64]
    if blob.get("referral_source") in REFERRAL_SOURCES:
        data["referral_source"] = blob["referral_source"]
    if blob.get("usage") in USAGE_OPTIONS:
        data["usage"] = blob["usage"]
    if blob.get("software") in SOFTWARE_OPTIONS:
        data["software"] = blob["software"]
    platforms = blob.get("social_platforms")
    if isinstance(platforms, list):
        data["social_platforms"] = [p for p in platforms if p in SOCIAL_PLATFORMS][:8]
    if isinstance(blob.get("ingest_ready"), bool):
        data["ingest_ready"] = blob["ingest_ready"]
    if blob.get("premium_choice") in ("free", "premium"):
        data["premium_choice"] = blob["premium_choice"]
    if isinstance(blob.get("live_detected"), bool):
        data["live_detected"] = blob["live_detected"]
    if isinstance(blob.get("completed_at"), str):
        data["completed_at"] = blob["completed_at"]
    return data


async def get_onboarding(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        return dict(DEFAULT_ONBOARDING)
    return normalize(settings.ui_preferences)


async def save_onboarding(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    patch: dict[str, Any],
    meta: RequestMeta,
    mark_complete: bool = False,
) -> dict[str, Any]:
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id)
        session.add(settings)
        await session.flush()

    current = normalize(settings.ui_preferences)
    updated = dict(current)

    if "step" in patch and isinstance(patch["step"], str) and patch["step"]:
        updated["step"] = patch["step"][:64]
    if "referral_source" in patch:
        value = patch["referral_source"]
        updated["referral_source"] = value if value in REFERRAL_SOURCES else None
    if "usage" in patch:
        value = patch["usage"]
        updated["usage"] = value if value in USAGE_OPTIONS else None
        if updated["usage"]:
            category = USAGE_TO_CATEGORY.get(updated["usage"])
            if category is not None:
                await session.execute(
                    update(OrganizationSettings)
                    .where(OrganizationSettings.organization_id == organization_id)
                    .values(content_category_override=category)
                )
    if "software" in patch:
        value = patch["software"]
        updated["software"] = value if value in SOFTWARE_OPTIONS else None
    if "social_platforms" in patch and isinstance(patch["social_platforms"], list):
        updated["social_platforms"] = [
            p for p in patch["social_platforms"] if p in SOCIAL_PLATFORMS
        ][:8]
    if "ingest_ready" in patch and isinstance(patch["ingest_ready"], bool):
        updated["ingest_ready"] = patch["ingest_ready"]
    if "premium_choice" in patch and patch["premium_choice"] in ("free", "premium", None):
        updated["premium_choice"] = patch["premium_choice"]
    if "live_detected" in patch and isinstance(patch["live_detected"], bool):
        updated["live_detected"] = patch["live_detected"]

    if mark_complete:
        updated["completed"] = True
        updated["step"] = "done"
        updated["completed_at"] = datetime.now(UTC).isoformat()

    preferences = dict(settings.ui_preferences or {})
    preferences[ONBOARDING_KEY] = updated
    settings.ui_preferences = preferences
    flag_modified(settings, "ui_preferences")
    await session.flush()

    audit(
        session,
        "onboarding.updated",
        meta=meta,
        actor_user_id=user_id,
        organization_id=organization_id,
        details={
            "fields": sorted(k for k in patch if k in updated),
            "completed": updated["completed"],
            "step": updated["step"],
        },
    )
    return updated


async def is_completed(session: AsyncSession, user_id: uuid.UUID) -> bool:
    row = (
        await session.execute(
            select(UserSettings.ui_preferences).where(UserSettings.user_id == user_id)
        )
    ).scalar_one_or_none()
    return bool(normalize(row).get("completed"))
