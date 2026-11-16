"""Speech-to-text providers.

No captions are invented: without a configured provider or without audio, the
caller gets an explicit empty/skipped result — never synthetic dialogue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

AsrProviderName = Literal["none", "console", "openai_compatible"]


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    words: list[TranscriptWord] = field(default_factory=list)
    language: str | None = None
    provider: str = "none"
    model: str | None = None
    audio_ms: int | None = None
    cost_usd: float = 0.0
    skipped: bool = False
    skip_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class AsrProvider(Protocol):
    name: str

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str = "audio/wav",
        language: str | None = None,
        filename: str = "audio.wav",
    ) -> Transcript: ...


class NoneAsr:
    name = "none"

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str = "audio/wav",
        language: str | None = None,
        filename: str = "audio.wav",
    ) -> Transcript:
        return Transcript(
            text="",
            skipped=True,
            skip_reason="asr_provider_none",
            provider=self.name,
            audio_ms=None,
        )


class ConsoleAsr:
    """Local/dev: logs that audio was received, returns empty (honest)."""

    name = "console"

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str = "audio/wav",
        language: str | None = None,
        filename: str = "audio.wav",
    ) -> Transcript:
        log.info(
            "asr_console_received",
            bytes=len(audio),
            content_type=content_type,
            filename=filename,
            language=language,
        )
        return Transcript(
            text="",
            skipped=True,
            skip_reason="asr_console_no_transcript",
            provider=self.name,
            audio_ms=None,
        )


class OpenAICompatibleAsr:
    """Groq / OpenAI-compatible multipart transcriptions endpoint."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str = "audio/wav",
        language: str | None = None,
        filename: str = "audio.wav",
    ) -> Transcript:
        if not audio:
            return Transcript(
                text="",
                skipped=True,
                skip_reason="empty_audio",
                provider=self.name,
                model=self._model,
            )
        data: dict[str, str] = {
            "model": self._model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        if language:
            data["language"] = language
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/audio/transcriptions",
                headers=headers,
                data=data,
                files={"file": (filename, audio, content_type)},
            )
        if response.status_code >= 400:
            log.error(
                "asr_http_failed",
                status=response.status_code,
                body=response.text[:500],
            )
            raise RuntimeError(f"ASR HTTP {response.status_code}")
        payload = response.json()
        words: list[TranscriptWord] = []
        for item in payload.get("words") or []:
            try:
                words.append(
                    TranscriptWord(
                        text=str(item.get("word") or item.get("text") or ""),
                        start_ms=int(float(item.get("start", 0)) * 1000),
                        end_ms=int(float(item.get("end", 0)) * 1000),
                    )
                )
            except (TypeError, ValueError):
                continue
        duration = payload.get("duration")
        audio_ms = int(float(duration) * 1000) if duration is not None else None
        return Transcript(
            text=str(payload.get("text") or "").strip(),
            words=words,
            language=payload.get("language"),
            provider=self.name,
            model=self._model,
            audio_ms=audio_ms,
            raw={"keys": sorted(payload.keys())},
        )


def build_asr(settings: Settings) -> AsrProvider:
    provider = (settings.asr_provider or "none").lower()
    if provider == "console":
        return ConsoleAsr()
    if provider == "openai_compatible":
        key = settings.asr_api_key.get_secret_value() if settings.asr_api_key is not None else None
        if not key:
            log.warning("asr_openai_compatible_without_key_falling_back_to_none")
            return NoneAsr()
        return OpenAICompatibleAsr(
            api_key=key,
            base_url=settings.asr_base_url,
            model=settings.asr_model,
        )
    return NoneAsr()


def transcript_to_details(transcript: Transcript) -> dict[str, Any]:
    return {
        "text": transcript.text,
        "language": transcript.language,
        "words": [
            {"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in transcript.words
        ],
        "skipped": transcript.skipped,
        "skip_reason": transcript.skip_reason,
        "raw": transcript.raw,
    }


def details_to_json_bytes(details: dict[str, Any]) -> bytes:
    return json.dumps(details, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
