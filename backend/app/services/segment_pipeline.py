"""5-minute live segment pipeline.

HD segment (MediaMTX record → S3) is kept full quality for highlights.
Analysis only: low-def WebP stills (12/min) + ASR transcript → Bedrock Luna.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import uuid7
from app.models.analysis import AnalysisJob, AnalysisWindow, HighlightCandidate
from app.models.enums import (
    AnalysisJobKind,
    CandidateStatus,
    EventCategory,
    JobStatus,
    SegmentKind,
    SegmentStatus,
    StreamSessionStatus,
    WindowStatus,
)
from app.models.media import MediaSegment, StreamSession
from app.services import asr as asr_service
from app.services.bedrock_luna import BedrockLuna, ViralMoment, moments_to_json
from app.services.media_ffmpeg import (
    ANALYSIS_FRAME_EVERY_SEC,
    FFmpegError,
    extract_audio_wav,
    extract_frames_webp_low,
    record_segment_copy,
)
from app.storage.s3 import ObjectStorage

log = structlog.get_logger(__name__)

WINDOW_MS = 5 * 60 * 1000
FRAME_EVERY_SEC = ANALYSIS_FRAME_EVERY_SEC
CATEGORY_MAP: dict[str, EventCategory] = {
    c.value: c for c in EventCategory
}


@dataclass(frozen=True, slots=True)
class SegmentResult:
    sequence: int
    storage_key: str
    segment_url: str | None
    moments: list[dict[str, Any]]
    frames: int
    transcript_chars: int


def live_segment_key(session_id: uuid.UUID, sequence: int) -> str:
    """HD 5-min extract under tmp/lives/<session>/ (short retention, per-live folder)."""
    return f"tmp/lives/{session_id}/seg_{sequence:04d}.mp4"


def _map_category(raw: str) -> EventCategory:
    key = (raw or "other").strip().lower().replace(" ", "_").replace("-", "_")
    return CATEGORY_MAP.get(key, EventCategory.OTHER)


async def persist_segment_analysis(
    session: AsyncSession,
    *,
    stream: StreamSession,
    sequence: int,
    storage_key: str,
    size_bytes: int,
    moments: list[ViralMoment],
    transcript_text: str,
    transcript_words: list[dict[str, Any]] | None = None,
    frames: int,
    model: str,
    provider: str,
) -> SegmentResult:
    """Write MediaSegment + AnalysisWindow + HighlightCandidates for one 5-min slice."""
    start_ms = sequence * WINDOW_MS
    end_ms = start_ms + WINDOW_MS
    now = datetime.now(UTC)

    existing_seg = (
        await session.execute(
            select(MediaSegment).where(
                MediaSegment.stream_session_id == stream.id,
                MediaSegment.kind == SegmentKind.AV,
                MediaSegment.sequence == sequence,
            )
        )
    ).scalar_one_or_none()
    if existing_seg is None:
        session.add(
            MediaSegment(
                id=uuid7(),
                organization_id=stream.organization_id,
                stream_session_id=stream.id,
                kind=SegmentKind.AV,
                sequence=sequence,
                start_ms=start_ms,
                end_ms=end_ms,
                storage_key=storage_key,
                size_bytes=size_bytes,
                status=SegmentStatus.AVAILABLE,
                # HD buffer is short-lived (cost); highlights/clips keep longer per plan.
                expires_at=now + timedelta(days=1),
            )
        )
    else:
        existing_seg.storage_key = storage_key
        existing_seg.size_bytes = size_bytes
        existing_seg.status = SegmentStatus.AVAILABLE
        existing_seg.expires_at = now + timedelta(days=1)

    window = (
        await session.execute(
            select(AnalysisWindow).where(
                AnalysisWindow.stream_session_id == stream.id,
                AnalysisWindow.sequence == sequence,
            )
        )
    ).scalar_one_or_none()
    if window is None:
        window = AnalysisWindow(
            id=uuid7(),
            organization_id=stream.organization_id,
            stream_session_id=stream.id,
            sequence=sequence,
            start_ms=start_ms,
            end_ms=end_ms,
            status=WindowStatus.ANALYZING,
        )
        session.add(window)
        await session.flush()

    window.status = WindowStatus.ANALYZED
    window.summary = transcript_text[:4000] if transcript_text else None
    window.signals = {
        "pipeline": "segment_luna",
        "storage_key": storage_key,
        "segment_url_key": storage_key,
        "frames": frames,
        "moments": len(moments),
        "transcript_words": transcript_words or [],
    }
    window.analyzed_at = now

    job = AnalysisJob(
        id=uuid7(),
        organization_id=stream.organization_id,
        stream_session_id=stream.id,
        analysis_window_id=window.id,
        kind=AnalysisJobKind.MULTIMODAL_ANALYSIS,
        status=JobStatus.SUCCEEDED,
        provider=provider,
        model=model,
        frames=frames,
        finished_at=now,
        details={
            "moments": moments_to_json(moments),
            "storage_key": storage_key,
            "transcript_words": transcript_words or [],
        },
    )
    session.add(job)

    # Replace prior candidates for this window sequence (idempotent re-runs).
    prior = (
        await session.execute(
            select(HighlightCandidate).where(
                HighlightCandidate.stream_session_id == stream.id,
                HighlightCandidate.context_start_ms == start_ms,
            )
        )
    ).scalars().all()
    for row in prior:
        row.status = CandidateStatus.SUPERSEDED

    for moment in moments:
        abs_start = start_ms + moment.start_ms
        abs_end = start_ms + moment.end_ms
        session.add(
            HighlightCandidate(
                id=uuid7(),
                organization_id=stream.organization_id,
                stream_session_id=stream.id,
                status=CandidateStatus.CANDIDATE,
                category=_map_category(moment.category),
                title=moment.title,
                summary=moment.description,
                context_start_ms=start_ms,
                start_ms=abs_start,
                payoff_ms=abs_start + (abs_end - abs_start) // 2,
                end_ms=abs_end,
                score=Decimal(str(round(moment.score, 3))),
                score_breakdown={
                    "virality": moment.score,
                    "hashtags": moment.hashtags,
                    "words": moment.words,
                    "relative_start_ms": moment.start_ms,
                    "relative_end_ms": moment.end_ms,
                    "segment_sequence": sequence,
                    "storage_key": storage_key,
                },
                verification={
                    "source": "luna",
                    "model": model,
                    "camera": {
                        "detected": moment.camera.detected,
                        "x": moment.camera.x,
                        "y": moment.camera.y,
                    },
                },
            )
        )

    # Quota / processed_ms is charged by analysis.segment after persist succeeds.
    stream.media_duration_ms = max(stream.media_duration_ms or 0, end_ms)
    stream.clips_count = (stream.clips_count or 0) + len(moments)

    return SegmentResult(
        sequence=sequence,
        storage_key=storage_key,
        segment_url=None,
        moments=moments_to_json(moments),
        frames=frames,
        transcript_chars=len(transcript_text),
    )


async def analyze_uploaded_segment(
    session: AsyncSession,
    *,
    settings: Settings,
    storage: ObjectStorage,
    stream: StreamSession,
    sequence: int,
    storage_key: str,
    size_bytes: int = 0,
) -> SegmentResult:
    """Download a 5-min HD segment already on S3 and run FFmpeg + ASR + Luna."""
    body = await storage.get_object(storage_key)
    # Tiny flap uploads (audio-only / <1s) must not park the analysis queue.
    if len(body) < 1_000_000:
        log.warning(
            "segment_reject_tiny",
            session_id=str(stream.id),
            sequence=sequence,
            size=len(body),
            storage_key=storage_key,
        )
        return await persist_segment_analysis(
            session,
            stream=stream,
            sequence=sequence,
            storage_key=storage_key,
            size_bytes=size_bytes or len(body),
            moments=[],
            transcript_text="",
            transcript_words=[],
            frames=0,
            model=settings.bedrock_model or "us.openai.gpt-6-luna",
            provider="skipped",
        )
    with tempfile.TemporaryDirectory(prefix="streamclip-seg-") as tmp:
        video_path = Path(tmp) / "segment.mp4"
        await asyncio.to_thread(video_path.write_bytes, body)
        result = await analyze_local_segment(
            session,
            settings=settings,
            storage=None,  # keep the agent-uploaded key; avoid double upload
            stream=stream,
            sequence=sequence,
            video_path=video_path,
            existing_storage_key=storage_key,
            existing_size_bytes=size_bytes or len(body),
        )
        return result


async def analyze_local_segment(
    session: AsyncSession,
    *,
    settings: Settings,
    storage: ObjectStorage | None,
    stream: StreamSession,
    sequence: int,
    video_path: Path,
    existing_storage_key: str | None = None,
    existing_size_bytes: int | None = None,
) -> SegmentResult:
    """FFmpeg frames + ASR + Bedrock + DB persist for one local MP4."""
    with tempfile.TemporaryDirectory(prefix="streamclip-seg-") as tmp:
        tmp_dir = Path(tmp)
        frames_dir = tmp_dir / "frames"
        wav_path = tmp_dir / "audio.wav"
        frames = await asyncio.to_thread(
            extract_frames_webp_low,
            video_path,
            frames_dir,
            every_seconds=FRAME_EVERY_SEC,
        )
        try:
            await asyncio.to_thread(extract_audio_wav, video_path, wav_path)
        except FFmpegError as exc:
            log.warning("extract_audio_failed", error=str(exc)[-400:])
        audio_bytes = await asyncio.to_thread(_read_audio, wav_path)

        words: list[dict[str, Any]] = []
        transcript_text = ""
        if audio_bytes:
            provider = asr_service.build_asr(settings)
            transcript = await provider.transcribe(audio_bytes, content_type="audio/wav")
            transcript_text = transcript.text
            words = [
                {"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms}
                for w in transcript.words
            ]

        model = settings.bedrock_model or "us.openai.gpt-6-luna"
        moments: list[ViralMoment] = []
        if frames:
            luna = BedrockLuna(settings)
            moments = await _run_luna(
                luna,
                transcript_text=transcript_text,
                transcript_words=words,
                frame_paths=frames,
            )

        if existing_storage_key:
            storage_key = existing_storage_key
            size_bytes = existing_size_bytes or await asyncio.to_thread(
                lambda: video_path.stat().st_size
            )
        else:
            size_bytes, body = await asyncio.to_thread(_read_video, video_path)
            storage_key = live_segment_key(stream.id, sequence)
            if storage is not None:
                await storage.put_object(
                    storage_key, body, content_type="video/mp4", short_retention=True
                )

        # Attach word-level transcript relative to each highlight (segment-relative ms).
        for moment in moments:
            if not moment.words:
                moment.words = [
                    w
                    for w in words
                    if w["end_ms"] >= moment.start_ms and w["start_ms"] <= moment.end_ms
                ]

        result = await persist_segment_analysis(
            session,
            stream=stream,
            sequence=sequence,
            storage_key=storage_key,
            size_bytes=size_bytes,
            moments=moments,
            transcript_text=transcript_text,
            transcript_words=words,
            frames=len(frames),
            model=model,
            provider="bedrock",
        )
        log.info(
            "segment_analyzed",
            session_id=str(stream.id),
            sequence=sequence,
            moments=len(moments),
            frames=len(frames),
        )
        return result


async def _run_luna(
    luna: BedrockLuna,
    *,
    transcript_text: str,
    transcript_words: list[dict[str, Any]],
    frame_paths: list[Path],
) -> list[ViralMoment]:
    return await asyncio.to_thread(
        luna.analyze,
        transcript_text=transcript_text,
        transcript_words=transcript_words,
        frame_paths=frame_paths,
    )


def _read_video(path: Path) -> tuple[int, bytes]:
    return path.stat().st_size, path.read_bytes()


def _read_audio(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def _prepare_work_file(work_dir: Path, sequence: int) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir / f"seg_{sequence:04d}.mp4"


async def record_and_analyze(
    session: AsyncSession,
    *,
    settings: Settings,
    storage: ObjectStorage | None,
    stream: StreamSession,
    sequence: int,
    input_url: str,
    work_dir: Path,
) -> SegmentResult:
    """Record `SEGMENT_SEC` from ingest, then analyze within the next window."""
    out = await asyncio.to_thread(_prepare_work_file, work_dir, sequence)
    await asyncio.to_thread(
        record_segment_copy, input_url, out, duration_sec=settings.segment_duration_sec
    )
    return await analyze_local_segment(
        session,
        settings=settings,
        storage=storage,
        stream=stream,
        sequence=sequence,
        video_path=out,
    )


async def load_live_session(session: AsyncSession, session_id: uuid.UUID) -> StreamSession | None:
    return (
        await session.execute(select(StreamSession).where(StreamSession.id == session_id))
    ).scalar_one_or_none()


def session_still_live(stream: StreamSession) -> bool:
    return stream.status in {
        StreamSessionStatus.PENDING,
        StreamSessionStatus.LIVE,
        StreamSessionStatus.INTERRUPTED,
        StreamSessionStatus.FINALIZING,
    }
