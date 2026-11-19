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


def test_transcribe_items_keep_word_times() -> None:
    words = onbox._words_from_transcribe_items(
        [
            {
                "type": "pronunciation",
                "start_time": "180.0",
                "end_time": "180.4",
                "alternatives": [{"content": "let's"}],
            },
            {
                "type": "pronunciation",
                "start_time": "180.4",
                "end_time": "181.0",
                "alternatives": [{"content": "go"}],
            },
            {"type": "punctuation", "alternatives": [{"content": "!"}]},
        ]
    )
    assert words == [
        {"text": "let's", "start_ms": 180_000, "end_ms": 180_400},
        {"text": "go!", "start_ms": 180_400, "end_ms": 181_000},
    ]


def test_transcribe_reads_job_word_times(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class _Body:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "results": {
                        "transcripts": [{"transcript": "let's go"}],
                        "items": [
                            {
                                "type": "pronunciation",
                                "start_time": "180.0",
                                "end_time": "181.0",
                                "alternatives": [{"content": "go"}],
                            }
                        ],
                    }
                }
            ).encode()

    class _S3:
        def get_object(self, **_kwargs):
            return {"Body": _Body()}

        def delete_object(self, **kwargs):
            seen["deleted"] = kwargs["Key"]

    class _Jobs:
        def start_transcription_job(self, **kwargs):
            seen["uri"] = kwargs["Media"]["MediaFileUri"]
            seen["languages"] = kwargs["IdentifyMultipleLanguages"]

        def get_transcription_job(self, **_kwargs):
            return {"TranscriptionJob": {"TranscriptionJobStatus": "COMPLETED"}}

        def delete_transcription_job(self, **_kwargs):
            seen["job_deleted"] = True

    def client(service, **_kwargs):
        return _S3() if service == "s3" else _Jobs()

    monkeypatch.setenv("ASR_PROVIDER", "transcribe")
    monkeypatch.setenv("S3_BUCKET", "stream-clip")
    monkeypatch.setenv("AWS_REGION", "eu-north-1")
    monkeypatch.setitem(
        __import__("sys").modules,
        "boto3",
        type("Boto", (), {"client": staticmethod(client)}),
    )

    text, words = onbox.transcribe(b"", "tmp/lives/session/seg_0001.mp4")

    assert seen["uri"] == "s3://stream-clip/tmp/lives/session/seg_0001.mp4"
    assert seen["languages"] is True
    assert text == "let's go"
    assert words == [{"text": "go", "start_ms": 180_000, "end_ms": 181_000}]
    assert seen["job_deleted"] is True


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


def test_transcribe_skips_when_provider_is_none(monkeypatch) -> None:
    monkeypatch.setenv("ASR_PROVIDER", "none")
    assert onbox.transcribe(b"abc") == ("", [])
