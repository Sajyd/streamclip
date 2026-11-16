"""Identity, tenancy and authentication tables."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    READ,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    access,
    enum_type,
    json_column,
)
from app.models.enums import (
    AuthTokenPurpose,
    ContentCategory,
    MembershipRole,
    OrganizationStatus,
    PlatformRole,
    SessionRevokeReason,
    UserStatus,
)


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        # Identity is not tenant data: only system code (authentication) reads it.
        access(rls=None),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="fr")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Europe/Paris")
    platform_role: Mapped[PlatformRole] = mapped_column(
        enum_type(PlatformRole, "platform_role"), nullable=False, default=PlatformRole.USER
    )
    status: Mapped[UserStatus] = mapped_column(
        enum_type(UserStatus, "status"), nullable=False, default=UserStatus.ACTIVE
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_version: Mapped[str] = mapped_column(String(32), nullable=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(String(500))
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSettings(Base, TimestampMixin):
    __tablename__ = "user_settings"
    __table_args__ = (access(rls=None),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    email_notifications: Mapped[dict[str, Any]] = json_column()
    ui_preferences: Mapped[dict[str, Any]] = json_column()


class Organization(Base, IdMixin, TimestampMixin):
    """The tenant. Each user gets a personal organization at sign-up; team
    seats can be added later without reshaping tenant-owned tables."""

    __tablename__ = "organizations"
    __table_args__ = (
        access(
            rls="organization_self",
            app=("SELECT", "UPDATE"),
            app_update_columns=("name", "updated_at"),
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[OrganizationStatus] = mapped_column(
        enum_type(OrganizationStatus, "status"), nullable=False, default=OrganizationStatus.ACTIVE
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    billing_email: Mapped[str | None] = mapped_column(String(320))
    country: Mapped[str | None] = mapped_column(String(2))
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganizationSettings(Base, TimestampMixin):
    """Clip, caption and analysis preferences of a tenant."""

    __tablename__ = "organization_settings"
    __table_args__ = (
        CheckConstraint("min_clip_seconds >= 5", name="min_clip_positive"),
        CheckConstraint(
            "min_clip_seconds <= target_clip_min_seconds"
            " AND target_clip_min_seconds <= target_clip_max_seconds"
            " AND target_clip_max_seconds <= max_clip_seconds",
            name="clip_durations_ordered",
        ),
        access(rls="tenant", app=("SELECT", "UPDATE")),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    min_clip_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    target_clip_min_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="45"
    )
    target_clip_max_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60"
    )
    max_clip_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="120")
    context_buffer_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="90"
    )
    content_category_override: Mapped[ContentCategory | None] = mapped_column(
        enum_type(ContentCategory, "content_category_override")
    )
    caption_style: Mapped[dict[str, Any]] = json_column()
    scoring_weights: Mapped[dict[str, Any]] = json_column()
    # Learned only from this tenant's own keep/delete/publish actions.
    preference_profile: Mapped[dict[str, Any]] = json_column()
    # Explicit opt-in before any content may contribute to a shared model.
    allow_global_training: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class Membership(Base, IdMixin, CreatedAtMixin, TenantMixin):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        access(rls="tenant", app=READ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MembershipRole] = mapped_column(
        enum_type(MembershipRole, "role"), nullable=False, default=MembershipRole.OWNER
    )


class AuthSession(Base, IdMixin, CreatedAtMixin):
    """One sign-in on one device. Refresh tokens belong to a session, so
    revoking the session invalidates the whole token family."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index(
            "ix_auth_sessions_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")
        ),
        access(rls=None),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[SessionRevokeReason | None] = mapped_column(
        enum_type(SessionRevokeReason, "revoke_reason")
    )
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))


class RefreshToken(Base, IdMixin, CreatedAtMixin):
    __tablename__ = "refresh_tokens"
    __table_args__ = (access(rls=None),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 of the opaque token: the raw value is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthToken(Base, IdMixin, CreatedAtMixin):
    """Single-use e-mail verification and password-reset tokens (hashed)."""

    __tablename__ = "auth_tokens"
    __table_args__ = (access(rls=None),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[AuthTokenPurpose] = mapped_column(
        enum_type(AuthTokenPurpose, "purpose"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    sent_to: Mapped[str] = mapped_column(String(320), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
