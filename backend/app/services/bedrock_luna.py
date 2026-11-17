"""Bedrock multimodal analysis with OpenAI GPT-6 Luna.

Given 480p frames + a full 5-minute transcript, returns non-overlapping viral
moments (30-60 s, prefer 60 s), word timings, virality score, title,
hashtagged description, and optional streamer-cam position on a 1920x1080 plane.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

DEFAULT_MODEL = "us.openai.gpt-6-luna"
DEFAULT_REGION = "us-east-1"
MIN_MOMENT_MS = 30_000
MAX_MOMENT_MS = 60_000
TARGET_MOMENT_MS = 60_000


@dataclass(frozen=True, slots=True)
class CameraBox:
    detected: bool
    x: int  # centre on 1920x1080
    y: int


@dataclass(frozen=True, slots=True)
class ViralMoment:
    start_ms: int
    end_ms: int
    score: float
    title: str
    description: str
    hashtags: list[str]
    words: list[dict[str, Any]]
    camera: CameraBox
    category: str = "punchline"


SYSTEM_PROMPT = """Tu analyses un extrait de live de 5 minutes (images + transcription).
Repère les moments viraux pour Shorts/TikTok/Reels.

Règles strictes:
- Chaque moment dure entre 30 et 60 secondes (préfère 60).
- Les moments ne se chevauchent pas.
- Timestamps relatifs à l'extrait (0 = début des 5 minutes), en millisecondes.
- Inclus les timings mot à mot couvrant le moment.
- Score de viralité entre 0 et 1.
- Titre accrocheur + description avec hashtags.
- Détecte si une webcam streamer est visible; si oui, donne le centre (x,y) sur un cadre 1920x1080.
- Réponds UNIQUEMENT en JSON valide, schéma:
{
  "moments": [
    {
      "start_ms": 0,
      "end_ms": 60000,
      "score": 0.8,
      "title": "...",
      "description": "... #tag",
      "hashtags": ["#tag"],
      "category": "punchline",
      "words": [{"text":"mot","start_ms":0,"end_ms":200}],
      "camera": {"detected": true, "x": 1600, "y": 220}
    }
  ]
}
Si aucun moment viral: {"moments": []}.
"""


def _clamp_moment(raw: dict[str, Any]) -> ViralMoment | None:
    try:
        start = int(raw["start_ms"])
        end = int(raw["end_ms"])
    except (KeyError, TypeError, ValueError):
        return None
    if end <= start:
        return None
    duration = end - start
    if duration < MIN_MOMENT_MS:
        end = start + MIN_MOMENT_MS
    if end - start > MAX_MOMENT_MS:
        end = start + TARGET_MOMENT_MS
    if MIN_MOMENT_MS <= (end - start) < TARGET_MOMENT_MS:
        end = min(start + TARGET_MOMENT_MS, 300_000)
    cam_raw = raw.get("camera") or {}
    camera = CameraBox(
        detected=bool(cam_raw.get("detected")),
        x=max(0, min(1919, int(cam_raw.get("x") or 960))),
        y=max(0, min(1079, int(cam_raw.get("y") or 200))),
    )
    words = []
    for w in raw.get("words") or []:
        try:
            words.append(
                {
                    "text": str(w.get("text") or ""),
                    "start_ms": int(w["start_ms"]),
                    "end_ms": int(w["end_ms"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    hashtags = [str(h) for h in (raw.get("hashtags") or [])][:12]
    desc = str(raw.get("description") or "").strip()
    if hashtags and not any(h in desc for h in hashtags):
        desc = (desc + " " + " ".join(hashtags)).strip()
    score = max(0.0, min(1.0, float(raw.get("score") or 0)))
    return ViralMoment(
        start_ms=max(0, start),
        end_ms=min(300_000, end),
        score=score,
        title=str(raw.get("title") or "Moment fort")[:200],
        description=desc[:2000],
        hashtags=hashtags,
        words=words,
        camera=camera,
        category=str(raw.get("category") or "punchline")[:32],
    )


def _dedupe_non_overlapping(moments: list[ViralMoment]) -> list[ViralMoment]:
    ordered = sorted(moments, key=lambda m: (-m.score, m.start_ms))
    kept: list[ViralMoment] = []
    for moment in ordered:
        if any(not (moment.end_ms <= k.start_ms or moment.start_ms >= k.end_ms) for k in kept):
            continue
        kept.append(moment)
    return sorted(kept, key=lambda m: m.start_ms)


def _parse_json_payload(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


class BedrockLuna:
    def __init__(self, settings: Settings) -> None:
        region = settings.bedrock_region or DEFAULT_REGION
        self.model_id = settings.bedrock_model or DEFAULT_MODEL
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def analyze(
        self,
        *,
        transcript_text: str,
        transcript_words: list[dict[str, Any]],
        frame_paths: list[Path],
        max_frames: int = 60,
    ) -> list[ViralMoment]:
        """Send frames (about 1/5s -> ~60 for 5 min) + transcript to GPT-6 Luna."""
        sampled = frame_paths[:max_frames]
        content: list[dict[str, Any]] = [
            {
                "text": (
                    f"Transcription complete ({len(transcript_words)} mots):\n"
                    f"{transcript_text[:12000]}\n\n"
                    "Mots (echantillon JSON): "
                    + json.dumps(transcript_words[:400], ensure_ascii=False)
                )
            }
        ]
        for path in sampled:
            data = path.read_bytes()
            content.append(
                {
                    "image": {
                        "format": "jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "png",
                        "source": {"bytes": data},
                    }
                }
            )

        response = self._client.converse(
            modelId=self.model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.2},
        )
        parts = response.get("output", {}).get("message", {}).get("content", [])
        text = " ".join(p.get("text", "") for p in parts if "text" in p)
        try:
            payload = _parse_json_payload(text)
        except json.JSONDecodeError:
            log.error("bedrock_luna_invalid_json", preview=text[:400])
            return []
        moments: list[ViralMoment] = []
        for item in payload.get("moments") or []:
            if isinstance(item, dict):
                moment = _clamp_moment(item)
                if moment is not None:
                    moments.append(moment)
        return _dedupe_non_overlapping(moments)


def moments_to_json(moments: list[ViralMoment]) -> list[dict[str, Any]]:
    return [
        {
            "start_ms": m.start_ms,
            "end_ms": m.end_ms,
            "score": m.score,
            "title": m.title,
            "description": m.description,
            "hashtags": m.hashtags,
            "category": m.category,
            "words": m.words,
            "camera": {"detected": m.camera.detected, "x": m.camera.x, "y": m.camera.y},
        }
        for m in moments
    ]


def encode_frame_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")
