"""FFmpeg resolver must work without a system binary (Vercel / CI)."""

from __future__ import annotations

from pathlib import Path

from app.services import media_ffmpeg


def test_require_ffmpeg_resolves_somewhere(monkeypatch, tmp_path: Path) -> None:
    media_ffmpeg.require_ffmpeg.cache_clear()
    monkeypatch.setattr(media_ffmpeg.shutil, "which", lambda _name: None)
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.delenv("IMAGEIO_FFMPEG_EXE", raising=False)
    monkeypatch.setattr(media_ffmpeg, "_STATIC_CACHE_DIR", tmp_path / "ffmpeg-cache")

    # Prefer imageio-ffmpeg wheel when PATH is empty.
    path = media_ffmpeg.require_ffmpeg()
    assert path
    assert Path(path).is_file()
    media_ffmpeg.require_ffmpeg.cache_clear()
