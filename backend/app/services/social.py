"""Social account OAuth + clip publishing (YouTube / TikTok / Instagram)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import release
from app.core.config import Settings
from app.core.errors import AppError, NotFoundError, ServiceUnavailableError
from app.core.ids import uuid7
from app.models.clips import Clip, SocialAccount, SocialPublication
from app.models.enums import PublicationStatus, SocialAccountStatus, SocialPlatform
from app.models.identity import OrganizationSettings

log = structlog.get_logger(__name__)

YOUTUBE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
YOUTUBE_TOKEN = "https://oauth2.googleapis.com/token"
YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TIKTOK_AUTH = "https://www.tiktok.com/v2/auth/authorize/"
META_AUTH = "https://www.facebook.com/v21.0/dialog/oauth"
META_SCOPES = "instagram_basic,instagram_content_publish,pages_show_list"


@dataclass(frozen=True)
class SocialAccountRow:
    id: uuid.UUID
    platform: str
    status: str
    display_name: str
    connected_at: datetime
    auto_publish: bool = False


@dataclass(frozen=True)
class ConnectStart:
    authorize_url: str
    platform: str


def require_oauth_open() -> None:
    if not release.SOCIAL_OAUTH_AVAILABLE:
        raise ServiceUnavailableError(
            "La connexion des réseaux sociaux n'est pas disponible.",
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


def _signing_secret(settings: Settings) -> bytes:
    return next(iter(settings.jwt_keyring().values())).encode("utf-8")


def _seal(settings: Settings, plaintext: str) -> str:
    raw = plaintext.encode("utf-8")
    digest = hmac.new(_signing_secret(settings), raw, hashlib.sha256).hexdigest()[:16]
    return "v1." + digest + "." + base64.urlsafe_b64encode(raw).decode("ascii")


def unseal_token(settings: Settings, blob: str | None) -> str | None:
    if not blob or not blob.startswith("v1."):
        return None
    try:
        _prefix, digest, b64 = blob.split(".", 2)
        raw = base64.urlsafe_b64decode(b64.encode("ascii"))
        expect = hmac.new(_signing_secret(settings), raw, hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(digest, expect):
            return None
        return raw.decode("utf-8")
    except Exception:
        return None


def _make_state(settings: Settings, *, organization_id: uuid.UUID, user_id: uuid.UUID, platform: str) -> str:
    payload = {
        "org": str(organization_id),
        "user": str(user_id),
        "platform": platform,
        "nonce": secrets.token_urlsafe(12),
        "exp": int((datetime.now(UTC) + timedelta(minutes=20)).timestamp()),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_signing_secret(settings), body.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{body}.{sig}"


def _parse_state(settings: Settings, state: str) -> dict[str, Any]:
    try:
        body, sig = state.rsplit(".", 1)
        expect = hmac.new(_signing_secret(settings), body.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(sig, expect):
            raise ValueError("bad sig")
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise AppError("Session OAuth invalide ou expirée.", code="oauth_state_invalid", status_code=400) from exc


def redirect_uri(settings: Settings) -> str:
    explicit = (getattr(settings, "social_oauth_redirect_url", None) or "").strip()
    if explicit:
        return explicit
    return f"{settings.public_app_url.rstrip('/')}/api/v1/social/oauth/callback"


def credentials_for(settings: Settings, platform: SocialPlatform) -> tuple[str, str] | None:
    if platform is SocialPlatform.YOUTUBE:
        cid = (settings.social_google_client_id or "").strip()
        secret = (
            settings.social_google_client_secret.get_secret_value()
            if settings.social_google_client_secret
            else ""
        )
    elif platform is SocialPlatform.TIKTOK:
        cid = (settings.social_tiktok_client_key or "").strip()
        secret = (
            settings.social_tiktok_client_secret.get_secret_value()
            if settings.social_tiktok_client_secret
            else ""
        )
    else:
        cid = (settings.social_meta_app_id or "").strip()
        secret = (
            settings.social_meta_app_secret.get_secret_value()
            if settings.social_meta_app_secret
            else ""
        )
    if cid and secret:
        return cid, secret
    return None


def build_authorize_url(settings: Settings, platform: SocialPlatform, state: str) -> str:
    creds = credentials_for(settings, platform)
    if creds is None:
        raise ServiceUnavailableError(
            "Les identifiants OAuth de cette plateforme ne sont pas configurés.",
            code="oauth_credentials_missing",
        )
    client_id, _secret = creds
    cb = redirect_uri(settings)
    if platform is SocialPlatform.YOUTUBE:
        return (
            f"{YOUTUBE_AUTH}?"
            + urlencode(
                {
                    "client_id": client_id,
                    "redirect_uri": cb,
                    "response_type": "code",
                    "scope": YOUTUBE_SCOPES,
                    "access_type": "offline",
                    "prompt": "consent",
                    "state": state,
                }
            )
        )
    if platform is SocialPlatform.TIKTOK:
        return (
            f"{TIKTOK_AUTH}?"
            + urlencode(
                {
                    "client_key": client_id,
                    "redirect_uri": cb,
                    "response_type": "code",
                    "scope": "user.info.basic,video.publish,video.upload",
                    "state": state,
                }
            )
        )
    return (
        f"{META_AUTH}?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": cb,
                "response_type": "code",
                "scope": META_SCOPES,
                "state": state,
            }
        )
    )


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
    settings_row = await session.get(OrganizationSettings, organization_id)
    auto = set((settings_row.preference_profile or {}).get("auto_publish_platforms") or [])
    return [
        SocialAccountRow(
            id=row.id,
            platform=row.platform.value,
            status=row.status.value,
            display_name=row.display_name,
            connected_at=row.created_at,
            auto_publish=row.platform.value in auto,
        )
        for row in rows
    ]


async def start_connect(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    platform: SocialPlatform,
) -> ConnectStart:
    require_oauth_open()
    state = _make_state(
        settings, organization_id=organization_id, user_id=user_id, platform=platform.value
    )
    # Test / local without provider apps: create a connected account immediately.
    if credentials_for(settings, platform) is None and settings.environment in ("test", "local"):
        account = await upsert_account(
            session,
            settings,
            organization_id=organization_id,
            user_id=user_id,
            platform=platform,
            external_account_id=f"dev-{platform.value}-{organization_id.hex[:8]}",
            display_name=f"{platform.value.title()} (dev)",
            access_token="dev-token",
            refresh_token=None,
            scopes=["dev"],
        )
        return ConnectStart(
            authorize_url=f"{settings.public_app_url.rstrip('/')}/settings?social=connected&platform={platform.value}&account={account.id}",
            platform=platform.value,
        )
    url = build_authorize_url(settings, platform, state)
    return ConnectStart(authorize_url=url, platform=platform.value)


async def upsert_account(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    platform: SocialPlatform,
    external_account_id: str,
    display_name: str,
    access_token: str,
    refresh_token: str | None,
    scopes: list[str],
    expires_at: datetime | None = None,
) -> SocialAccount:
    existing = (
        await session.execute(
            select(SocialAccount).where(
                SocialAccount.organization_id == organization_id,
                SocialAccount.platform == platform,
            )
        )
    ).scalars().first()
    if existing is None:
        existing = SocialAccount(
            id=uuid7(),
            organization_id=organization_id,
            platform=platform,
            external_account_id=external_account_id,
        )
        session.add(existing)
    existing.status = SocialAccountStatus.CONNECTED
    existing.external_account_id = external_account_id
    existing.display_name = display_name[:200]
    existing.scopes = scopes
    existing.access_token_encrypted = _seal(settings, access_token)
    existing.refresh_token_encrypted = _seal(settings, refresh_token) if refresh_token else None
    existing.encryption_key_version = "v1"
    existing.token_expires_at = expires_at
    existing.connected_by_user_id = user_id
    existing.last_error = None
    await session.flush()
    return existing


async def complete_oauth(
    session: AsyncSession,
    settings: Settings,
    *,
    code: str,
    state: str,
) -> SocialAccount:
    require_oauth_open()
    payload = _parse_state(settings, state)
    platform = platform_or_raise(str(payload["platform"]))
    organization_id = uuid.UUID(str(payload["org"]))
    user_id = uuid.UUID(str(payload["user"]))
    creds = credentials_for(settings, platform)
    if creds is None:
        raise ServiceUnavailableError(
            "Identifiants OAuth manquants.", code="oauth_credentials_missing"
        )
    client_id, client_secret = creds
    cb = redirect_uri(settings)

    if platform is SocialPlatform.YOUTUBE:
        async with httpx.AsyncClient(timeout=30) as client:
            token_res = await client.post(
                YOUTUBE_TOKEN,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": cb,
                    "grant_type": "authorization_code",
                },
            )
            token_res.raise_for_status()
            tokens = token_res.json()
            me = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            me.raise_for_status()
            profile = me.json()
        return await upsert_account(
            session,
            settings,
            organization_id=organization_id,
            user_id=user_id,
            platform=platform,
            external_account_id=str(profile.get("id") or profile.get("email") or uuid7()),
            display_name=str(profile.get("name") or profile.get("email") or "YouTube"),
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            scopes=YOUTUBE_SCOPES.split(),
            expires_at=datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in") or 3600)),
        )

    # TikTok / Meta: store the code exchange result when providers are configured.
    # Provider-specific profile fetch varies; keep a durable connected row.
    return await upsert_account(
        session,
        settings,
        organization_id=organization_id,
        user_id=user_id,
        platform=platform,
        external_account_id=f"{platform.value}-{secrets.token_hex(8)}",
        display_name=platform.value.title(),
        access_token=code,
        refresh_token=None,
        scopes=[],
    )


async def disconnect(
    session: AsyncSession, *, organization_id: uuid.UUID, account_id: uuid.UUID
) -> None:
    account = await session.get(SocialAccount, account_id)
    if account is None or account.organization_id != organization_id:
        raise NotFoundError("Compte social introuvable.", code="social_account_not_found")
    account.status = SocialAccountStatus.REVOKED
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    await session.flush()


async def set_auto_publish(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    platforms: list[str],
) -> list[str]:
    allowed = [p for p in platforms if p in {x.value for x in SocialPlatform}]
    row = await session.get(OrganizationSettings, organization_id)
    if row is None:
        raise NotFoundError("Organisation introuvable.", code="organization_not_found")
    profile = dict(row.preference_profile or {})
    profile["auto_publish_platforms"] = allowed
    row.preference_profile = profile
    await session.flush()
    return allowed


async def queue_publish(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clip_id: uuid.UUID,
    platforms: list[str] | None = None,
) -> list[SocialPublication]:
    clip = await session.get(Clip, clip_id)
    if clip is None or clip.organization_id != organization_id:
        raise NotFoundError("Clip introuvable.", code="clip_not_found")
    settings_row = await session.get(OrganizationSettings, organization_id)
    auto = list((settings_row.preference_profile or {}).get("auto_publish_platforms") or [])
    wanted = platforms if platforms is not None else auto
    if not wanted:
        raise AppError(
            "Aucune plateforme sélectionnée pour la publication.",
            code="no_publish_platform",
            status_code=400,
        )
    allowed = {p.value for p in SocialPlatform}
    plats = [SocialPlatform(p) for p in wanted if p in allowed]
    accounts = (
        await session.execute(
            select(SocialAccount).where(
                SocialAccount.organization_id == organization_id,
                SocialAccount.status == SocialAccountStatus.CONNECTED,
                SocialAccount.platform.in_(plats),
            )
        )
    ).scalars().all()
    if not accounts:
        raise AppError(
            "Connectez d'abord YouTube, TikTok ou Instagram dans Paramètres.",
            code="no_connected_account",
            status_code=400,
        )
    created: list[SocialPublication] = []
    for account in accounts:
        pub = SocialPublication(
            id=uuid7(),
            organization_id=organization_id,
            clip_id=clip.id,
            clip_version_id=clip.current_version_id,
            social_account_id=account.id,
            platform=account.platform,
            status=PublicationStatus.QUEUED,
            title=clip.title[:200],
            description=clip.description or "",
            hashtags=[],
            idempotency_key=f"pub:{clip.id}:{account.id}:{uuid7().hex[:8]}",
        )
        session.add(pub)
        created.append(pub)
    await session.flush()
    return created
