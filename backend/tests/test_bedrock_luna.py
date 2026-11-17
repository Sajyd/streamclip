"""Unit tests for Luna moment clamping / non-overlap (no Bedrock call)."""

from __future__ import annotations

from app.services.bedrock_luna import (
    CameraBox,
    ViralMoment,
    _clamp_moment,
    _dedupe_non_overlapping,
    moments_to_json,
)


def test_clamp_prefers_sixty_seconds() -> None:
    moment = _clamp_moment(
        {
            "start_ms": 10_000,
            "end_ms": 45_000,  # 35s → stretch toward 60
            "score": 0.9,
            "title": "Boom",
            "description": "desc #viral",
            "hashtags": ["#viral"],
            "words": [{"text": "hi", "start_ms": 10_000, "end_ms": 10_200}],
            "camera": {"detected": True, "x": 1600, "y": 180},
            "category": "punchline",
        }
    )
    assert moment is not None
    assert moment.end_ms - moment.start_ms == 60_000
    assert moment.camera.detected is True
    assert moment.camera.x == 1600


def test_dedupe_keeps_higher_score() -> None:
    cam = CameraBox(False, 960, 200)
    a = ViralMoment(
        start_ms=0,
        end_ms=60_000,
        score=0.5,
        title="a",
        description="",
        hashtags=[],
        words=[],
        camera=cam,
    )
    b = ViralMoment(
        start_ms=30_000,
        end_ms=90_000,
        score=0.9,
        title="b",
        description="",
        hashtags=[],
        words=[],
        camera=cam,
    )
    kept = _dedupe_non_overlapping([a, b])
    assert len(kept) == 1
    assert kept[0].title == "b"


def test_moments_to_json_shape() -> None:
    payload = moments_to_json(
        [
            ViralMoment(
                start_ms=0,
                end_ms=60_000,
                score=0.8,
                title="T",
                description="D #x",
                hashtags=["#x"],
                words=[{"text": "ok", "start_ms": 0, "end_ms": 100}],
                camera=CameraBox(True, 100, 200),
            )
        ]
    )
    assert payload[0]["camera"]["x"] == 100
    assert payload[0]["words"][0]["text"] == "ok"
