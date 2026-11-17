"""Content understanding: analysis windows, jobs, speakers, events, candidates."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    AnalysisJobKind,
    CandidateStatus,
    EventCategory,
    EventStatus,
    JobStatus,
    VisualAssociationStatus,
    WindowStatus,
)


class AnalysisWindow(Base, IdMixin, TimestampMixin, TenantMixin):
    """A ~5 minute slice of a live, analysed as a whole.

    Windows overlap and hand over a rolling summary plus still-open events, so
    a story that starts in one window and pays off in the next is not cut.
    """

    __tablename__ = "analysis_windows"
    __table_args__ = (
        UniqueConstraint("stream_session_id", "sequence"),
        CheckConstraint("end_ms > start_ms", name="range_ordered"),
        access(rls="tenant", app=()),
    )

    stream_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stream_sessions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[WindowStatus] = mapped_column(
        enum_type(WindowStatus, "status"), nullable=False, default=WindowStatus.PENDING, index=True
    )
    # Cheap local signals (speech ratio, loudness peaks, scene changes...).
    signals: Mapped[dict[str, Any]] = json_column()
    context_summary: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    open_events: Mapped[list[Any]] = json_column(as_list=True)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default="0")
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisJob(Base, IdMixin, TimestampMixin, TenantMixin):
    """One unit of processing with its measured usage and cost."""

    __tablename__ = "analysis_jobs"
    __table_args__ = (
        Index("ix_analysis_jobs_session_kind", "stream_session_id", "kind"),
        access(rls="tenant", app=()),
    )

    stream_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stream_sessions.id", ondelete="CASCADE"), nullable=False
    )
    analysis_window_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("analysis_windows.id", ondelete="CASCADE"), index=True
    )
    clip_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    kind: Mapped[AnalysisJobKind] = mapped_column(
        enum_type(AnalysisJobKind, "kind"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus, "status"), nullable=False, default=JobStatus.QUEUED, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(48))
    model: Mapped[str | None] = mapped_column(String(96))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    audio_ms: Mapped[int | None] = mapped_column(BigInteger)
    frames: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    details: Mapped[dict[str, Any]] = json_column()


class Speaker(Base, IdMixin, TimestampMixin, TenantMixin):
    """A voice separated by audio diarization within one session.

    Diarization answers "which voice spoke when"; tying a voice to a visible
    person is a separate, uncertain step tracked by `visual_status`. A speaker
    is never given a civil identity: only the creator may name it.
    """

    __tablename__ = "speakers"
    __table_args__ = (
        UniqueConstraint("stream_session_id", "label"),
        access(rls="tenant", app=READ),
    )

    stream_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stream_sessions.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80))
    total_speech_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    first_heard_ms: Mapped[int | None] = mapped_column(BigInteger)
    visual_status: Mapped[VisualAssociationStatus] = mapped_column(
        enum_type(VisualAssociationStatus, "visual_status"),
        nullable=False,
        default=VisualAssociationStatus.NOT_VISUALLY_IDENTIFIED,
    )
    visual_confidence: Mapped[float | None] = mapped_column(Float)
    visual_track: Mapped[dict[str, Any] | None] = json_column(nullable=True)


class DetectedEvent(Base, IdMixin, CreatedAtMixin, TenantMixin):
    """Something notable found in one analysis window (raw detection)."""

    __tablename__ = "detected_events"
    __table_args__ = (
        Index("ix_detected_events_session_time", "stream_session_id", "start_ms"),
        CheckConstraint("end_ms > start_ms", name="range_ordered"),
        access(rls="tenant", app=()),
    )

    stream_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stream_sessions.id", ondelete="CASCADE"), nullable=False
    )
    analysis_window_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("analysis_windows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[EventCategory] = mapped_column(
        enum_type(EventCategory, "category"), nullable=False
    )
    status: Mapped[EventStatus] = mapped_column(
        enum_type(EventStatus, "status"), nullable=False, default=EventStatus.DETECTED
    )
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    peak_ms: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    scores: Mapped[dict[str, Any]] = json_column()
    evidence: Mapped[dict[str, Any]] = json_column()
    # The event was still unfolding at the end of its window.
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("detected_events.id", ondelete="SET NULL")
    )


class HighlightCandidate(Base, IdMixin, TimestampMixin, TenantMixin):
    """A potential clip: merged events with refined, self-contained boundaries."""

    __tablename__ = "highlight_candidates"
    __table_args__ = (
        Index("ix_highlight_candidates_session_score", "stream_session_id", "score"),
        CheckConstraint("end_ms > start_ms", name="range_ordered"),
        # Readable by the tenant (Remotion highlights UI); workers write as system.
        access(rls="tenant", app=READ),
    )

    stream_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stream_sessions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[CandidateStatus] = mapped_column(
        enum_type(CandidateStatus, "status"), nullable=False, default=CandidateStatus.CANDIDATE
    )
    category: Mapped[EventCategory] = mapped_column(
        enum_type(EventCategory, "category"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Setup -> payoff structure: a clip must contain both to be understandable.
    context_start_ms: Mapped[int | None] = mapped_column(BigInteger)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payoff_ms: Mapped[int | None] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = json_column()
    verification: Mapped[dict[str, Any]] = json_column()
    rejection_reason: Mapped[str | None] = mapped_column(String(300))


class HighlightCandidateEvent(Base, CreatedAtMixin, TenantMixin):
    """Which detected events a candidate was built from."""

    __tablename__ = "highlight_candidate_events"
    __table_args__ = (access(rls="tenant", app=()),)

    highlight_candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("highlight_candidates.id", ondelete="CASCADE"), primary_key=True
    )
    detected_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("detected_events.id", ondelete="CASCADE"), primary_key=True, index=True
    )
