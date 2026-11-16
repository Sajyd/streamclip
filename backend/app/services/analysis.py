"""Analysis windows and transcription job scheduling.

Windows are ~5 minutes of processed media. They are opened when ticks cross
window boundaries — never with fabricated transcripts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.models.analysis import AnalysisJob, AnalysisWindow
from app.models.enums import (
    AnalysisJobKind,
    JobStatus,
    SegmentKind,
    SegmentStatus,
    WindowStatus,
)
from app.models.media import MediaSegment, StreamSession
from app.tasks.queue import enqueue

# Matches the model docstring: a ~5 minute slice.
WINDOW_MS = 5 * 60 * 1000


async def schedule_windows_for_progress(
    session: AsyncSession,
    stream: StreamSession,
    *,
    previous_processed_ms: int,
    current_processed_ms: int,
) -> list[AnalysisJob]:
    """Create queued windows/jobs for every full window boundary newly crossed."""
    if current_processed_ms <= previous_processed_ms:
        return []
    first_seq = previous_processed_ms // WINDOW_MS
    last_complete_seq = (current_processed_ms // WINDOW_MS) - 1
    created: list[AnalysisJob] = []
    for sequence in range(first_seq, last_complete_seq + 1):
        start_ms = sequence * WINDOW_MS
        end_ms = start_ms + WINDOW_MS
        existing = (
            await session.execute(
                select(AnalysisWindow.id).where(
                    AnalysisWindow.stream_session_id == stream.id,
                    AnalysisWindow.sequence == sequence,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        window = AnalysisWindow(
            id=uuid7(),
            organization_id=stream.organization_id,
            stream_session_id=stream.id,
            sequence=sequence,
            start_ms=start_ms,
            end_ms=end_ms,
            status=WindowStatus.QUEUED,
        )
        session.add(window)
        await session.flush()
        job = AnalysisJob(
            id=uuid7(),
            organization_id=stream.organization_id,
            stream_session_id=stream.id,
            analysis_window_id=window.id,
            kind=AnalysisJobKind.TRANSCRIPTION,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        await session.flush()
        await enqueue(
            session,
            "analysis.transcribe",
            {
                "job_id": str(job.id),
                "window_id": str(window.id),
                "session_id": str(stream.id),
            },
            idempotency_key=f"analysis.transcribe:{job.id}",
            organization_id=stream.organization_id,
            queue="analysis",
        )
        created.append(job)
    return created


async def load_audio_for_window(
    session: AsyncSession, window: AnalysisWindow
) -> tuple[bytes | None, str | None]:
    """Return (audio_bytes, storage_key) for the window when a segment exists.

    Without media segments the transcription job is skipped honestly.
    """
    segment = (
        await session.execute(
            select(MediaSegment)
            .where(
                MediaSegment.stream_session_id == window.stream_session_id,
                MediaSegment.kind == SegmentKind.AUDIO,
                MediaSegment.status == SegmentStatus.AVAILABLE,
                MediaSegment.start_ms <= window.start_ms,
                MediaSegment.end_ms >= window.end_ms,
            )
            .order_by(MediaSegment.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if segment is None:
        # Fall back: any audio overlapping the window.
        segment = (
            await session.execute(
                select(MediaSegment)
                .where(
                    MediaSegment.stream_session_id == window.stream_session_id,
                    MediaSegment.kind == SegmentKind.AUDIO,
                    MediaSegment.status == SegmentStatus.AVAILABLE,
                    MediaSegment.start_ms < window.end_ms,
                    MediaSegment.end_ms > window.start_ms,
                )
                .order_by(MediaSegment.sequence)
                .limit(1)
            )
        ).scalar_one_or_none()
    if segment is None:
        return None, None
    return None, segment.storage_key


async def mark_job_skipped(
    session: AsyncSession,
    job: AnalysisJob,
    window: AnalysisWindow | None,
    *,
    code: str,
    message: str,
) -> None:
    now = datetime.now(UTC)
    job.status = JobStatus.SKIPPED
    job.error_code = code
    job.error_message = message
    job.finished_at = now
    if window is not None:
        window.status = WindowStatus.SKIPPED
        window.analyzed_at = now
    await session.flush()


async def mark_job_failed(
    session: AsyncSession,
    job: AnalysisJob,
    window: AnalysisWindow | None,
    *,
    code: str,
    message: str,
) -> None:
    now = datetime.now(UTC)
    job.status = JobStatus.FAILED
    job.error_code = code
    job.error_message = message[:1000]
    job.finished_at = now
    if window is not None:
        window.status = WindowStatus.FAILED
        window.analyzed_at = now
    await session.flush()


async def mark_job_succeeded(
    session: AsyncSession,
    job: AnalysisJob,
    window: AnalysisWindow,
    *,
    provider: str,
    model: str | None,
    audio_ms: int | None,
    cost_usd: float,
    details: dict[str, object],
) -> None:
    from decimal import Decimal

    now = datetime.now(UTC)
    cost = Decimal(str(cost_usd))
    job.status = JobStatus.SUCCEEDED
    job.provider = provider
    job.model = model
    job.audio_ms = audio_ms
    job.cost_usd = cost
    job.details = details
    job.finished_at = now
    window.status = WindowStatus.ANALYZED
    window.analyzed_at = now
    window.cost_usd = cost
    await session.flush()
