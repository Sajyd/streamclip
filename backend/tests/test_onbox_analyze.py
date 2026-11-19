"""On-box frames are taken at fixed times, and Luna receives that clock."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.services import ingest_onbox_analyze as onbox


def test_extract_frames_seeks_every_ten_seconds(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "seg.mp4"
    video.write_bytes(b"x" * 20_000)
    out = tmp_path / "frames"
    seeks: list[str] = []

    def fake_run(cmd, **_kwargs):
        seeks.append(cmd[cmd.index("-ss") + 1])
        dest = Path(cmd[-1])
        seconds = float(seeks[-1])
        if seconds <= 20:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"\xff\xd8" + bytes([int(seconds)]) + b"j" * 800)
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="corrupt")

    monkeypatch.setattr(onbox, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(onbox.subprocess, "run", fake_run)

    frames = onbox.extract_frames(video, out)

    assert [time_ms for _path, time_ms in frames] == [0, 10_000, 20_000]
    assert frames[0][0].stat().st_size > 500
    assert "fps=" not in " ".join(str(part) for part in seeks)


def test_luna_timeline_keeps_word_and_frame_clocks(tmp_path: Path) -> None:
    frames = []
    for time_ms, marker in ((0, b"a"), (10_000, b"a"), (20_000, b"b")):
        path = tmp_path / f"t{time_ms}.jpg"
        path.write_bytes(b"\xff\xd8" + marker * 800)
        frames.append((path, time_ms))
    words = [
        {"text": "quiet", "start_ms": 170_000, "end_ms": 171_000},
        {"text": "gooooo", "start_ms": 180_000, "end_ms": 181_000},
    ]
    content = onbox._luna_content("quiet then gooooo", words, frames)
    timeline = json.loads(content[0]["text"])

    assert timeline["frames"] == [
        {"index": 1, "time_ms": 0},
        {"index": 2, "time_ms": 10_000},
        {"index": 3, "time_ms": 20_000},
    ]
    assert timeline["words"][1] == {"text": "gooooo", "start_ms": 180_000, "end_ms": 181_000}
    images = [block for block in content if "image" in block]
    assert len(images) == 2


def test_word_times_shift_to_the_chunk_offset() -> None:
    words = onbox._timed_words("let's gooooo", duration_ms=2_000, offset_ms=180_000)
    assert words[0]["start_ms"] == 180_000
    assert words[-1]["end_ms"] == 182_000


def test_analyze_posts_frames_to_luna(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "seg.mp4"
    video.write_bytes(b"x" * 20_000)
    seen: dict[str, object] = {}

    def fake_frames(_video, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "frame_0001.jpg"
        path.write_bytes(b"\xff\xd8" + b"j" * 800)
        return [(path, 0)]

    def fake_luna(**kwargs):
        seen["frames"] = list(kwargs["frames"])
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
    assert "no intelligible speech" in seen["instruction"]
    assert text == "salut tout le monde"
    assert [word["text"] for word in words] == ["salut", "tout", "le", "monde"]
    assert words[0]["start_ms"] == 0
    assert words[-1]["end_ms"] > words[0]["start_ms"]


def test_transcribe_skips_when_provider_is_none(monkeypatch) -> None:
    monkeypatch.setenv("ASR_PROVIDER", "none")
    assert onbox.transcribe(b"abc") == ("", [])
