"""Ingestion: stream keys, ingest nodes, live sessions and temporary media.

Media positions are expressed in milliseconds on a per-session timeline that
keeps running across reconnections (`StreamConnection.media_offset_ms`), so a
dropped and resumed live stays one coherent session.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
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
    ConnectionStatus,
    ContentCategory,
    IngestNodeKind,
    IngestNodeStatus,
    IngestProtocol,
    SegmentKind,
    SegmentStatus,
    StreamEndReason,
    StreamKeyStatus,
    StreamSessionStatus,
)


class StreamKey(Base, IdMixin, TimestampMixin, TenantMixin):
    """Personal STREAMCLIP ingest key. Only an HMAC of the secret is stored; the
    clear value is shown once, at creation. Platform stream keys (Twitch,
    YouTube, Kick) are never requested nor stored."""

    __tablename__ = "stream_keys"
    __table_args__ = (
        Index(
            "uq_stream_keys_one_active",
            "organization_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        access(rls="tenant", app=READ),
    )

    # Non-secret identifier used as the stream path and in logs.
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False, server_default="")
    status: Mapped[StreamKeyStatus] = mapped_column(
        enum_type(StreamKeyStatus, "status"), nullable=False, default=StreamKeyStatus.ACTIVE
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestNode(Base, IdMixin, TimestampMixin):
    """A MediaMTX ingest server (pooled or dedicated to one live)."""

    __tablename__ = "ingest_nodes"
    __table_args__ = (access(rls=None),)

    name: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    kind: Mapped[IngestNodeKind] = mapped_column(enum_type(IngestNodeKind, "kind"), nullable=False)
    status: Mapped[IngestNodeStatus] = mapped_column(
        enum_type(IngestNodeStatus, "status"), nullable=False, index=True
    )
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    instance_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    instance_type: Mapped[str | None] = mapped_column(String(32))
    public_hostname: Mapped[str | None] = mapped_column(String(255))
    capacity_streams: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    active_streams: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    agent_version: Mapped[str | None] = mapped_column(String(64))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = json_column()


class StreamSession(Base, IdMixin, TimestampMixin, TenantMixin):
    """One live broadcast, from first media received to finalization."""

    __tablename__ = "stream_sessions"
    __table_args__ = (
        Index("ix_stream_sessions_org_started", "organization_id", "started_at"),
        Index(
            "ix_stream_sessions_open",
            "status",
            postgresql_where=text("status IN ('pending', 'live', 'interrupted', 'finalizing')"),
        ),
        CheckConstraint("processed_ms >= 0 AND media_duration_ms >= 0", name="durations_positive"),
        access(rls="tenant", app=READ),
    )

    stream_key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stream_keys.id", ondelete="SET NULL"), index=True
    )
    ingest_node_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ingest_nodes.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[StreamSessionStatus] = mapped_column(
        enum_type(StreamSessionStatus, "status"),
        nullable=False,
        default=StreamSessionStatus.PENDING,
    )
    end_reason: Mapped[StreamEndReason | None] = mapped_column(
        enum_type(StreamEndReason, "end_reason")
    )
    title: Mapped[str | None] = mapped_column(String(200))
    protocol: Mapped[IngestProtocol | None] = mapped_column(enum_type(IngestProtocol, "protocol"))
    content_category: Mapped[ContentCategory | None] = mapped_column(
        enum_type(ContentCategory, "content_category")
    )
    content_category_confidence: Mapped[float | None] = mapped_column(Float)
    processing_profile: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="standard"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_media_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Media received vs. media actually processed (only the latter is billed).
    media_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    processed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    video_codec: Mapped[str | None] = mapped_column(String(32))
    audio_codec: Mapped[str | None] = mapped_column(String(32))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer)
    # Long-range context carried from one analysis window to the next.
    rolling_summary: Mapped[str | None] = mapped_column(Text)
    clips_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1000))


class StreamConnection(Base, IdMixin, CreatedAtMixin, TenantMixin):
    """One publisher connection. A session has several after reconnections."""

    __tablename__ = "stream_connections"
    __table_args__ = (access(rls="tenant", app=READ),)

    stream_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stream_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingest_node_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ingest_nodes.id", ondelete="SET NULL")
    )
    protocol: Mapped[IngestProtocol] = mapped_column(
        enum_type(IngestProtocol, "protocol"), nullable=False
    )
    status: Mapped[ConnectionStatus] = mapped_column(
        enum_type(ConnectionStatus, "status"), nullable=False, default=ConnectionStatus.ACTIVE
    )
    remote_ip: Mapped[str | None] = mapped_column(INET)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Position of this connection's first frame on the session timeline.
    media_offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    bytes_received: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    disconnect_reason: Mapped[str | None] = mapped_column(String(200))


class MediaSegment(Base, IdMixin, CreatedAtMixin, TenantMixin):
    """Short-lived media chunk in the temporary buffer. Full lives are never
    kept: segments expire unless pinned by a clip candidate being rendered."""

    __tablename__ = "media_segments"
    __table_args__ = (
        UniqueConstraint("stream_session_id", "kind", "sequence"),
        Index("ix_media_segments_session_time", "stream_session_id", "start_ms"),
        Index(
            "ix_media_segments_expiry", "expires_at", postgresql_where=text("status = 'available'")
        ),
        CheckConstraint("end_ms > start_ms", name="range_ordered"),
        access(rls="tenant", app=()),
    )

    stream_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stream_sessions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[SegmentKind] = mapped_column(enum_type(SegmentKind, "kind"), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[SegmentStatus] = mapped_column(
        enum_type(SegmentStatus, "status"), nullable=False, default=SegmentStatus.AVAILABLE
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pinned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
