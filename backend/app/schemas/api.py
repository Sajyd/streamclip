"""Request and response models of the public API."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# Upper bounds stop oversized inputs early; the real password policy lives in
# app.security.passwords.
Email = Annotated[str, Field(min_length=3, max_length=320)]
# Passwords are taken exactly as typed: surrounding spaces are part of them.
Password = Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, max_length=512)]
OpaqueToken = Annotated[str, Field(min_length=20, max_length=200)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Message(ApiModel):
    message: str


class UrlResponse(ApiModel):
    url: str


# --- Authentication ----------------------------------------------------------


class RegisterRequest(ApiModel):
    email: Email
    password: Password
    display_name: Annotated[str | None, Field(max_length=120)] = None
    accept_terms: bool
    marketing_opt_in: bool = False


class LoginRequest(ApiModel):
    email: Email
    password: Password


class RefreshRequest(ApiModel):
    refresh_token: OpaqueToken


class TokenRequest(ApiModel):
    token: OpaqueToken


class ForgotPasswordRequest(ApiModel):
    email: Email


class ResetPasswordRequest(ApiModel):
    token: OpaqueToken
    new_password: Password


class ChangePasswordRequest(ApiModel):
    current_password: Password
    new_password: Password


class PasswordConfirmation(ApiModel):
    password: Password


class Tokens(ApiModel):
    token_type: Literal["Bearer"] = "Bearer"
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    locale: str
    timezone: str
    email_verified: bool
    platform_role: str
    created_at: datetime


class AuthResponse(ApiModel):
    user: UserOut
    tokens: Tokens


class SessionOut(ApiModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime | None
    ip: str | None
    user_agent: str | None
    current: bool


# --- Account -----------------------------------------------------------------


class OrganizationOut(ApiModel):
    id: uuid.UUID
    name: str
    role: str


class Capabilities(ApiModel):
    registration_open: bool
    email_delivery: bool
    billing: bool
    # True while payments run in Stripe test mode: no real money moves.
    billing_test_mode: bool
    storage: bool
    # Live ingestion and clip generation. False until that pipeline is
    # deployed: the web application then says so instead of offering it.
    live_processing: bool
    # Control plane for STREAMCLIP ingest keys (OBS destinations). Independent
    # of live_processing: keys can be issued before MediaMTX accepts traffic.
    ingest_keys: bool
    # True when the shared edge RTMP URL is configured (OBS can connect).
    ingest_online: bool
    # Stable edge RTMP URL for OBS (same for every org).
    ingest_rtmp_url: str | None = None
    # Optional status / docs URL (not the OBS server field).
    ingest_api_url: str | None
    # Official OAuth for social networks (YouTube / TikTok / Instagram).
    social_oauth: bool


class MetaResponse(ApiModel):
    name: str
    environment: str
    capabilities: Capabilities
    password_min_length: int
    terms_version: str


class OnboardingOut(ApiModel):
    completed: bool
    step: str
    referral_source: str | None = None
    usage: str | None = None
    software: str | None = None
    social_platforms: list[str] = []
    ingest_ready: bool = False
    premium_choice: Literal["free", "premium"] | None = None
    live_detected: bool = False
    completed_at: str | None = None


class UpdateOnboardingRequest(ApiModel):
    step: Annotated[str | None, Field(max_length=64)] = None
    referral_source: (
        Literal[
            "youtube",
            "twitch",
            "tiktok",
            "instagram",
            "x",
            "discord",
            "friend",
            "search",
            "other",
        ]
        | None
    ) = None
    usage: (
        Literal[
            "gaming",
            "vlog",
            "podcast",
            "concert",
            "interview",
            "just_chatting",
            "irl",
            "conference",
            "other",
        ]
        | None
    ) = None
    software: Literal["obs", "streamlabs"] | None = None
    social_platforms: list[Literal["youtube", "tiktok", "instagram"]] | None = None
    ingest_ready: bool | None = None
    premium_choice: Literal["free", "premium"] | None = None
    live_detected: bool | None = None
    complete: bool = False


class MeResponse(ApiModel):
    user: UserOut
    organization: OrganizationOut
    capabilities: Capabilities
    onboarding: OnboardingOut


class ClipOut(ApiModel):
    id: uuid.UUID
    title: str
    description: str
    status: str
    category: str
    score: float
    start_ms: int
    end_ms: int
    duration_ms: int | None
    is_favorite: bool
    thumbnail_available: bool
    download_available: bool
    created_at: datetime
    stream_session_id: uuid.UUID | None


class ClipList(ApiModel):
    items: list[ClipOut]


class HighlightOut(ApiModel):
    id: uuid.UUID
    stream_session_id: uuid.UUID
    title: str
    description: str
    category: str
    score: float
    start_ms: int
    end_ms: int
    relative_start_ms: int
    relative_end_ms: int
    segment_sequence: int
    hashtags: list[str] = []
    words: list[dict[str, Any]] = []
    camera: dict[str, Any] = {}
    media_available: bool = False
    created_at: datetime


class HighlightList(ApiModel):
    items: list[HighlightOut]


class SocialAccountOut(ApiModel):
    id: uuid.UUID
    platform: str
    status: str
    display_name: str
    connected_at: datetime


class SocialAccountList(ApiModel):
    items: list[SocialAccountOut]
    oauth_available: bool
    platforms: list[str]


class UpdateProfileRequest(ApiModel):
    display_name: Annotated[str | None, Field(max_length=120)] = None
    locale: Literal["fr", "en"] | None = None
    timezone: Annotated[str | None, Field(max_length=64)] = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in available_timezones():
            raise ValueError("Unknown IANA timezone")
        return value


class UpdateOrganizationRequest(ApiModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]


class NotificationOut(ApiModel):
    id: uuid.UUID
    kind: str
    severity: str
    title: str
    body: str
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class NotificationList(ApiModel):
    items: list[NotificationOut]
    unread_count: int


class MarkReadRequest(ApiModel):
    notification_id: uuid.UUID | None = None


class ExportOut(ApiModel):
    id: uuid.UUID
    status: str
    size_bytes: int | None
    created_at: datetime
    expires_at: datetime | None


class ExportList(ApiModel):
    items: list[ExportOut]


# --- Billing -----------------------------------------------------------------


class PlanOut(ApiModel):
    code: str
    name: str
    description: str
    # Monthly price, tax included, in the smallest currency unit (cents).
    price_cents: int
    currency: str
    included_seconds: int
    max_clips_per_session: int | None
    max_concurrent_streams: int
    clip_retention_days: int | None
    features: list[str]
    purchasable: bool


class PlanList(ApiModel):
    items: list[PlanOut]
    vat_rate_percent: float


class QuotaOut(ApiModel):
    included_seconds: int
    consumed_seconds: int
    remaining_seconds: int
    used_ratio: float
    warning: bool
    exhausted: bool


class BillingOverview(ApiModel):
    plan: PlanOut
    status: str
    is_paid: bool
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    payment_failed: bool
    quota: QuotaOut
    has_billing_account: bool
    can_manage: bool
    billing_available: bool
    billing_test_mode: bool


class CheckoutRequest(ApiModel):
    plan_code: Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")]


# --- Back-office -------------------------------------------------------------


class AdminUserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    status: str
    platform_role: str
    email_verified: bool
    created_at: datetime
    last_login_at: datetime | None
    organization_id: uuid.UUID | None
    plan_code: str | None


class AdminUserList(ApiModel):
    items: list[AdminUserOut]
    next_cursor: uuid.UUID | None


class SuspendRequest(ApiModel):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


# --- Ingest ------------------------------------------------------------------


class StreamKeyOut(ApiModel):
    public_id: str
    key_hint: str
    label: str
    status: str
    created_at: datetime
    last_used_at: datetime | None
    # Stable resolve API (always set). Use with stream_key to get the RTMP host.
    ingest_api_url: str
    # Dedicated instance RTMP URL — set when the org's spot is READY.
    rtmps_url: str | None
    srt_url: str | None
    # Clear OBS stream key — only present right after create/rotate.
    stream_key: str | None = None
    ingest_online: bool


class StreamKeyIssueRequest(ApiModel):
    label: Annotated[str, Field(default="", max_length=80)] = ""


class IngestResolveRequest(ApiModel):
    # Full OBS stream key: `{public_id}/{secret}` (shown once at issue time).
    # Optional when the caller is authenticated — resolve uses their org.
    stream_key: Annotated[str | None, Field(default=None, min_length=16, max_length=256)] = None


class IngestResolveOut(ApiModel):
    status: str  # starting | ready | unavailable
    ingest_api_url: str
    rtmp_url: str | None = None
    analysis_url: str | None = None
    public_hostname: str | None = None
    message: str


class IngestRelayTargetOut(ApiModel):
    """Edge → dedicated push target (polled by the shared ingest node)."""

    status: str  # ready | starting | unavailable
    rtmp_push_url: str | None = None
    message: str


class StreamSessionOut(ApiModel):
    id: uuid.UUID
    status: str
    end_reason: str | None
    protocol: str | None
    title: str | None
    started_at: datetime | None
    ended_at: datetime | None
    media_duration_ms: int
    processed_ms: int
    clips_count: int
    created_at: datetime


class StreamSessionList(ApiModel):
    items: list[StreamSessionOut]


class IngestAuthHookRequest(ApiModel):
    """MediaMTX auth webhook payload (subset we rely on)."""

    action: Annotated[str, Field(max_length=32)] = "publish"
    path: Annotated[str, Field(max_length=255)] = ""
    protocol: Annotated[str, Field(max_length=32)] = "rtmp"
    ip: Annotated[str | None, Field(max_length=64)] = None
    user: Annotated[str | None, Field(max_length=128)] = None
    password: Annotated[str | None, Field(max_length=256)] = None
    query: Annotated[str | None, Field(max_length=512)] = None


class IngestEventHookRequest(ApiModel):
    event: Annotated[str, Field(max_length=64)]
    path: Annotated[str, Field(max_length=255)] = ""
    protocol: Annotated[str, Field(max_length=32)] = "rtmp"
    ip: Annotated[str | None, Field(max_length=64)] = None
    # Optional processing tick from the ingest agent (milliseconds).
    processed_ms: int | None = Field(default=None, ge=1, le=3_600_000)
    # 5-minute HD segment uploaded to S3 by the on-box agent.
    storage_key: Annotated[str | None, Field(default=None, max_length=512)] = None
    sequence: int | None = Field(default=None, ge=0, le=10_000)
    size_bytes: int | None = Field(default=None, ge=0)
