"""On-box frame sampling must not require a full 1080p decode."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.services import ingest_onbox_analyze as onbox


def test_extract_frames_keeps_jpegs_when_ffmpeg_exits_nonzero(
    monkeypatch, tmp_path: Path
) -> None:
    video = tmp_path / "seg.mp4"
    video.write_bytes(b"x" * 20_000)
    out = tmp_path / "frames"
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        dest = Path(cmd[-1])
        if "%04d" in dest.name:
            dest = dest.with_name(dest.name.replace("%04d", "0001"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\xff\xd8" + b"j" * 800)
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="corrupt")

    monkeypatch.setattr(onbox, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(onbox.subprocess, "run", fake_run)

    frames = onbox.extract_frames(video, out)

    assert frames
    assert frames[0].stat().st_size > 500
    assert calls[0][calls[0].index("-skip_frame") + 1] == "nokey"
    assert "fps=" not in " ".join(calls[0])


def test_extract_frames_falls_back_to_seeks_when_keyframes_are_empty(
    monkeypatch, tmp_path: Path
) -> None:
    video = tmp_path / "seg.mp4"
    video.write_bytes(b"x" * 20_000)
    out = tmp_path / "frames"

    def fake_run(cmd, **_kwargs):
        pattern = str(cmd[-1])
        if "seek_" in pattern:
            dest = Path(pattern)
            dest.write_bytes(b"\xff\xd8" + b"k" * 800)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(onbox, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(onbox.subprocess, "run", fake_run)

    frames = onbox.extract_frames(video, out)

    assert len(frames) == len(onbox._SEEK_SECONDS)
    assert all(path.name.startswith("seek_") for path in frames)


def test_analyze_posts_frames_to_luna(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "seg.mp4"
    video.write_bytes(b"x" * 20_000)
    seen: dict[str, object] = {}

    def fake_frames(_video, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "frame_0001.jpg"
        path.write_bytes(b"\xff\xd8" + b"j" * 800)
        return [path]

    def fake_luna(**kwargs):
        seen["frames"] = list(kwargs["frame_paths"])
        seen["transcript"] = kwargs["transcript_text"]
        return (
            [],
            "us.openai.gpt-6-luna",
            {"frames": 1, "empty_reason": "model_returned_no_moments"},
        )

    monkeypatch.setattr(onbox, "extract_frames", fake_frames)
    monkeypatch.setattr(onbox, "extract_audio_wav", lambda *_a, **_k: False)
    monkeypatch.setattr(onbox, "luna_analyze", fake_luna)
    monkeypatch.setattr(
        onbox,
        "post_analysis_result",
        lambda payload: seen.update(posted=payload) or True,
    )

    payload = onbox.analyze_segment_file(
        video_path=video,
        stream_session_id="session",
        sequence=1,
        storage_key="tmp/lives/session/seg_0001.mp4",
    )

    assert len(seen["frames"]) == 1
    assert payload["frames"] == 1
    assert payload["provider"] == "bedrock"
    assert payload["posted"] is True


def test_transcribe_calls_voxtral_small(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class _Client:
        def converse(self, **kwargs):
            seen["model"] = kwargs["modelId"]
            seen["audio"] = kwargs["messages"][0]["content"][0]["audio"]["source"]["bytes"]
            seen["instruction"] = kwargs["messages"][0]["content"][1]["text"]
            return {"output": {"message": {"content": [{"text": "salut tout le monde"}]}}}

    monkeypatch.setenv("ASR_PROVIDER", "bedrock")
    monkeypatch.setenv("ASR_MODEL", "whisper-large-v3-turbo")
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setitem(__import__("sys").modules, "boto3", type("Boto", (), {
        "client": staticmethod(lambda *_a, **_k: _Client())
    }))

    text, words = onbox.transcribe(b"RIFFxxxxWAVEfmt " + b"\x00" * 44 + b"\x00\x01" * 16000)

    assert seen["model"] == onbox.DEFAULT_ASR_MODEL
    assert "Do not translate" in seen["instruction"]
    assert "language being spoken" in seen["instruction"]
    assert text == "salut tout le monde"
    assert [word["text"] for word in words] == ["salut", "tout", "le", "monde"]
    assert words[0]["start_ms"] == 0
    assert words[-1]["end_ms"] > words[0]["start_ms"]


def test_transcribe_skips_when_provider_is_none(monkeypatch) -> None:
    monkeypatch.setenv("ASR_PROVIDER", "none")
    assert onbox.transcribe(b"abc") == ("", [])
