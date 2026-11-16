"""Clips, captions, feedback, social publishing and stored objects."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
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
    AssetKind,
    AssetStatus,
    CaptionFormat,
    ClipFeedbackAction,
    ClipStatus,
    ClipVersionKind,
    ClipVersionStatus,
    EventCategory,
    PublicationStatus,
    SocialAccountStatus,
    SocialPlatform,
)


class StorageAsset(Base, IdMixin, CreatedAtMixin, TenantMixin):
    """An object in S3. Every stored object is registered here so that
    retention, deletion on account closure and storage cost stay traceable."""

    __tablename__ = "storage_assets"
    __table_args__ = (
        UniqueConstraint("bucket", "key"),
        Index(
            "ix_storage_assets_expiry", "expires_at", postgresql_where=text("status = 'available'")
        ),
        access(rls="tenant", app=READ),
    )

    kind: Mapped[AssetKind] = mapped_column(enum_type(AssetKind, "kind"), nullable=False)
    status: Mapped[AssetStatus] = mapped_column(
        enum_type(AssetStatus, "status"), nullable=False, default=AssetStatus.PENDING
    )
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = json_column()


class Clip(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "clips"
    __table_args__ = (
        Index("ix_clips_org_created", "organization_id", "created_at"),
        CheckConstraint("end_ms > start_ms", name="range_ordered"),
        access(rls="tenant", app=READ),
    )

    # Clips outlive the purge of the live they come from.
    stream_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stream_sessions.id", ondelete="SET NULL"), index=True
    )
    highlight_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("highlight_candidates.id", ondelete="SET NULL")
    )
    status: Mapped[ClipStatus] = mapped_column(
        enum_type(ClipStatus, "status"), nullable=False, default=ClipStatus.QUEUED
    )
    category: Mapped[EventCategory] = mapped_column(
        enum_type(EventCategory, "category"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    language: Mapped[str | None] = mapped_column(String(12))
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = json_column()
    speakers: Mapped[list[Any]] = json_column(as_list=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClipVersion(Base, IdMixin, TimestampMixin, TenantMixin):
    """A rendered cut of a clip: the automatic one, then each user edit."""

    __tablename__ = "clip_versions"
    __table_args__ = (
        UniqueConstraint("clip_id", "version"),
        CheckConstraint("end_ms > start_ms", name="range_ordered"),
        access(rls="tenant", app=READ),
    )

    clip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[ClipVersionKind] = mapped_column(
        enum_type(ClipVersionKind, "kind"), nullable=False, default=ClipVersionKind.AUTO
    )
    status: Mapped[ClipVersionStatus] = mapped_column(
        enum_type(ClipVersionStatus, "status"), nullable=False, default=ClipVersionStatus.QUEUED
    )
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Reframing plan (crop path), caption style and encoder settings.
    render_settings: Mapped[dict[str, Any]] = json_column()
    video_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("storage_assets.id", ondelete="SET NULL")
    )
    thumbnail_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("storage_assets.id", ondelete="SET NULL")
    )
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1000))


class Caption(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "captions"
    __table_args__ = (
        UniqueConstraint("clip_version_id", "language", "format"),
        access(rls="tenant", app=READ),
    )

    clip_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clip_versions.id", ondelete="CASCADE"), nullable=False
    )
    language: Mapped[str] = mapped_column(String(12), nullable=False)
    format: Mapped[CaptionFormat] = mapped_column(
        enum_type(CaptionFormat, "format"), nullable=False
    )
    # Word-level timings with speaker labels (source for every other format).
    words: Mapped[dict[str, Any] | None] = json_column(nullable=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("storage_assets.id", ondelete="SET NULL")
    )
    is_burned_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class ClipFeedbackEvent(Base, IdMixin, CreatedAtMixin, TenantMixin):
    """Keep / delete / publish / edit signals used to personalise scoring for
    this tenant only. `clip_id` is a soft reference: the signal survives the
    clip's deletion, never leaves the tenant, and is erased with the account."""

    __tablename__ = "clip_feedback_events"
    __table_args__ = (
        Index("ix_clip_feedback_org_created", "organization_id", "created_at"),
        access(rls="tenant", app=READ),
    )

    clip_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[ClipFeedbackAction] = mapped_column(
        enum_type(ClipFeedbackAction, "action"), nullable=False
    )
    value: Mapped[dict[str, Any]] = json_column()


class SocialAccount(Base, IdMixin, TimestampMixin, TenantMixin):
    """A social account connected through the platform's official OAuth flow.
    Passwords are never requested; tokens are stored encrypted (envelope
    encryption) and are not readable by the tenant-scoped database role."""

    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "platform", "external_account_id"),
        access(rls="tenant", app=()),
    )

    platform: Mapped[SocialPlatform] = mapped_column(
        enum_type(SocialPlatform, "platform"), nullable=False
    )
    status: Mapped[SocialAccountStatus] = mapped_column(
        enum_type(SocialAccountStatus, "status"),
        nullable=False,
        default=SocialAccountStatus.CONNECTED,
    )
    external_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    scopes: Mapped[list[Any]] = json_column(as_list=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    encryption_key_version: Mapped[str | None] = mapped_column(String(64))
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_error: Mapped[str | None] = mapped_column(String(1000))


class SocialPublication(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "social_publications"
    __table_args__ = (
        Index("ix_social_publications_org_created", "organization_id", "created_at"),
        Index(
            "ix_social_publications_due",
            "scheduled_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
        access(rls="tenant", app=READ),
    )

    clip_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="SET NULL"), index=True
    )
    clip_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clip_versions.id", ondelete="SET NULL")
    )
    social_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[SocialPlatform] = mapped_column(
        enum_type(SocialPlatform, "platform"), nullable=False
    )
    status: Mapped[PublicationStatus] = mapped_column(
        enum_type(PublicationStatus, "status"), nullable=False, default=PublicationStatus.DRAFT
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    hashtags: Mapped[list[Any]] = json_column(as_list=True)
    privacy: Mapped[str | None] = mapped_column(String(32))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_post_id: Mapped[str | None] = mapped_column(String(128))
    external_url: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(1000))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
