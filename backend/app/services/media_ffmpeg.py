"""Local FFmpeg helpers for the 5-minute segment pipeline."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from functools import lru_cache
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# Cached under /tmp so warm Vercel invocations reuse the binary.
_STATIC_CACHE_DIR = Path(os.environ.get("STREAMCLIP_FFMPEG_DIR", "/tmp/streamclip-ffmpeg"))


class FFmpegError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def require_ffmpeg() -> str:
    """Resolve an ffmpeg binary: PATH → env → imageio-ffmpeg → static download."""
    path = shutil.which("ffmpeg")
    if path:
        return path

    for key in ("FFMPEG_PATH", "IMAGEIO_FFMPEG_EXE"):
        candidate = (os.environ.get(key) or "").strip()
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate

    for candidate in ("/usr/local/bin/ffmpeg", "/opt/bin/ffmpeg"):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate

    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            log.info("ffmpeg_resolved", source="imageio_ffmpeg", path=exe)
            return exe
    except Exception as exc:  # noqa: BLE001 — optional dependency / wheel missing
        log.warning("ffmpeg_imageio_unavailable", error=str(exc))

    cached = _ensure_static_ffmpeg()
    if cached:
        log.info("ffmpeg_resolved", source="static_download", path=cached)
        return cached

    raise FFmpegError("ffmpeg not found on PATH")


# 12 frames / minute → one every 5s. Used only for Luna analysis (not the HD segment).
FRAMES_PER_MINUTE = 12
ANALYSIS_FRAME_EVERY_SEC = 60.0 / FRAMES_PER_MINUTE
ANALYSIS_FRAME_HEIGHT = 360


def _has_video_stream(video_path: Path) -> bool:
    """True when ffprobe (or ffmpeg -i) reports at least one video stream."""
    ffmpeg = require_ffmpeg()
    ffprobe = shutil.which("ffprobe") or str(Path(ffmpeg).with_name("ffprobe"))
    if Path(ffprobe).is_file():
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return "video" in (proc.stdout or "").lower()
    # Fallback: parse ffmpeg -i stderr.
    proc = subprocess.run(
        [ffmpeg, "-i", str(video_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return "Video:" in (proc.stderr or "")


def extract_frames_webp_low(
    video_path: Path,
    out_dir: Path,
    *,
    every_seconds: float = ANALYSIS_FRAME_EVERY_SEC,
    height: int = ANALYSIS_FRAME_HEIGHT,
) -> list[Path]:
    """Extract low-def WebP stills for Luna (HD segment stays untouched).

    Returns [] (no raise) when the file has no video stream or is too short —
    common for flap/partial uploads that must not park analysis.segment.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if not video_path.is_file() or video_path.stat().st_size < 10_000:
        log.warning("extract_frames_skip_tiny", path=str(video_path))
        return []
    if not _has_video_stream(video_path):
        log.warning("extract_frames_skip_no_video", path=str(video_path))
        return []

    ffmpeg = require_ffmpeg()
    pattern_webp = out_dir / "frame_%04d.webp"
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-vf",
        f"fps=1/{every_seconds},scale=-2:{height}",
        "-frames:v",
        "60",
        "-c:v",
        "libwebp",
        "-quality",
        "35",
        "-compression_level",
        "4",
        str(pattern_webp),
    ]
    try:
        _run(cmd, label="extract_frames_webp")
    except FFmpegError as exc:
        # Static builds without libwebp → JPEG fallback at the same cadence.
        log.warning("extract_frames_webp_failed", error=str(exc)[-400:])
        pattern_jpg = out_dir / "frame_%04d.jpg"
        cmd_jpg = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-vf",
            f"fps=1/{every_seconds},scale=-2:{height}",
            "-frames:v",
            "60",
            "-q:v",
            "5",
            str(pattern_jpg),
        ]
        try:
            _run(cmd_jpg, label="extract_frames_jpeg_fallback")
        except FFmpegError as exc2:
            log.warning("extract_frames_all_failed", error=str(exc2)[-400:])
            return []
        return sorted(out_dir.glob("frame_*.jpg"))
    return sorted(out_dir.glob("frame_*.webp"))


def extract_frames_480p(
    video_path: Path,
    out_dir: Path,
    *,
    every_seconds: float = ANALYSIS_FRAME_EVERY_SEC,
) -> list[Path]:
    """Backward-compatible alias → low-def WebP at 12 frames/min."""
    return extract_frames_webp_low(
        video_path, out_dir, every_seconds=every_seconds, height=ANALYSIS_FRAME_HEIGHT
    )


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


def _ensure_static_ffmpeg() -> str | None:
    """Download a static ffmpeg build into /tmp (Vercel / dedicated boxes)."""
    dest = _STATIC_CACHE_DIR / "ffmpeg"
    if dest.is_file() and os.access(dest, os.X_OK):
        return str(dest)

    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("x86_64", "amd64"):
        arch = "amd64"
    else:
        log.warning("ffmpeg_static_unsupported_arch", machine=machine)
        return None

    url = f"https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-{arch}-static.tar.xz"
    _STATIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="ffmpeg-dl-") as tmp:
            archive = Path(tmp) / "ffmpeg.tar.xz"
            log.info("ffmpeg_static_download", url=url)
            urllib.request.urlretrieve(url, archive)  # noqa: S310 — fixed HTTPS vendor URL
            with tarfile.open(archive, "r:xz") as tar:
                tar.extractall(path=tmp, filter="data")
            extracted = next(Path(tmp).glob("ffmpeg-*-static/ffmpeg"), None)
            if extracted is None or not extracted.is_file():
                return None
            dest.write_bytes(extracted.read_bytes())
            dest.chmod(0o755)
        return str(dest)
    except Exception as exc:  # noqa: BLE001 — best-effort bootstrap
        log.warning("ffmpeg_static_download_failed", error=str(exc))
        return None
