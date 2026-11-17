"""Local FFmpeg helpers for the 5-minute segment pipeline."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegError("ffmpeg not found on PATH")
    return path


def extract_frames_480p(
    video_path: Path,
    out_dir: Path,
    *,
    every_seconds: float = 5.0,
) -> list[Path]:
    """Extract one JPEG frame every `every_seconds` at max 480p height."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "frame_%04d.jpg"
    ffmpeg = require_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps=1/{every_seconds},scale=-2:480",
        "-q:v",
        "5",
        str(pattern),
    ]
    _run(cmd, label="extract_frames")
    return sorted(out_dir.glob("frame_*.jpg"))


def extract_audio_wav(video_path: Path, wav_path: Path) -> Path:
    ffmpeg = require_ffmpeg()
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(wav_path),
    ]
    _run(cmd, label="extract_audio")
    return wav_path


def record_segment_copy(
    input_url: str,
    out_path: Path,
    *,
    duration_sec: int = 300,
) -> Path:
    """Record `duration_sec` of live ingest into a single MP4 (stream copy)."""
    ffmpeg = require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-rw_timeout",
        "15000000",
        "-i",
        input_url,
        "-t",
        str(duration_sec),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    _run(cmd, label="record_segment")
    return out_path


def _run(cmd: list[str], *, label: str) -> None:
    log.info("ffmpeg_run", label=label, cmd=cmd[:6])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FFmpegError(f"{label} failed ({proc.returncode}): {proc.stderr[-800:]}")
