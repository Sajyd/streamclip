#!/usr/bin/env python3
"""On-box 5-min segment analysis for the dedicated :8080 agent.

Runs on the EC2 spot with stdlib + boto3 (installed at boot):
  frames every 5s → ASR (Groq/OpenAI-compatible) → Bedrock GPT-6 Luna →
  POST moments to the API persist hook.

Deployed as /usr/local/bin/streamclip_onbox_analyze.py alongside the agent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

# One still every 10s (≤24 per 5-min window). Keyframe-only so the decoder
# does not fight the RTMP reader on a 2 vCPU box.
FRAME_EVERY_SEC = 10
MAX_FRAMES = 24
EXTRACT_TIMEOUT_S = 60
_SEEK_SECONDS = (5, 30, 60, 120, 180, 240)
MIN_MOMENT_MS = 30_000
MAX_MOMENT_MS = 60_000
TARGET_MOMENT_MS = 60_000
DEFAULT_MODEL = "us.openai.gpt-6-luna"
DEFAULT_BEDROCK_REGION = "us-east-1"

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


def _log(msg: str) -> None:
    line = f"{__import__('time').strftime('%Y-%m-%dT%H:%M:%SZ', __import__('time').gmtime())} {msg}\n"
    try:
        with Path("/var/log/streamclip-analyze.log").open("a") as fh:
            fh.write(line)
    except OSError:
        pass


def _ffmpeg() -> str:
    for candidate in (
        shutil.which("ffmpeg"),
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("ffmpeg not found")


def _run_ffmpeg(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        _log(f"ffmpeg_timeout timeout={timeout}s")
        return None


def _jpeg_frames(out_dir: Path) -> list[Path]:
    frames = [
        path
        for path in out_dir.glob("*.jpg")
        if path.is_file() and path.stat().st_size > 500
    ]
    return sorted(frames)[:MAX_FRAMES]


def extract_frames(video: Path, out_dir: Path) -> list[Path]:
    """Sample stills without decoding every picture of the HD segment.

    A full `fps=1/5` decode of 5 minutes of 1080p returns nothing when ffmpeg
    is OOM-killed or exits on one corrupt frame, and it is what stalls RTMP.
    Keyframe sampling is enough for Luna. Any JPEG already written is kept
    even if ffmpeg's exit code is non-zero.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if not video.is_file() or video.stat().st_size < 10_000:
        return []
    ff = _ffmpeg()
    common_in = [
        "-threads",
        "1",
        "-skip_frame",
        "nokey",
        "-fflags",
        "+discardcorrupt+genpts",
        "-err_detect",
        "ignore_err",
        "-i",
        str(video),
        "-an",
    ]
    primary = [
        ff,
        "-y",
        *common_in,
        "-vf",
        (
            f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{FRAME_EVERY_SEC})',"
            "scale=-2:360"
        ),
        "-fps_mode",
        "vfr",
        "-frames:v",
        str(MAX_FRAMES),
        "-q:v",
        "8",
        str(out_dir / "frame_%04d.jpg"),
    ]
    proc = _run_ffmpeg(primary, timeout=EXTRACT_TIMEOUT_S)
    found = _jpeg_frames(out_dir)
    if len(found) >= 4:
        _log(f"extract_frames_ok count={len(found)} mode=keyframe")
        return found
    if proc is not None and proc.returncode != 0:
        _log(
            f"extract_frames_key_rc={proc.returncode} kept={len(found)} "
            f"err={(proc.stderr or '')[-300:]}"
        )
    # Live copies often have a broken timeline, so time-based select keeps
    # one frame. Step through keyframes by index instead.
    secondary = [
        ff,
        "-y",
        *common_in,
        "-vf",
        "select='not(mod(n,3))',scale=-2:360",
        "-fps_mode",
        "vfr",
        "-frames:v",
        str(MAX_FRAMES),
        "-q:v",
        "8",
        str(out_dir / "kf_%04d.jpg"),
    ]
    proc2 = _run_ffmpeg(secondary, timeout=EXTRACT_TIMEOUT_S)
    found = _jpeg_frames(out_dir)
    if len(found) >= 4:
        _log(f"extract_frames_ok count={len(found)} mode=keyframe_index")
        return found
    if proc2 is not None and proc2.returncode != 0:
        _log(
            f"extract_frames_index_rc={proc2.returncode} kept={len(found)} "
            f"err={(proc2.stderr or '')[-300:]}"
        )
    for index, seconds in enumerate(_SEEK_SECONDS):
        grab = [
            ff,
            "-y",
            "-threads",
            "1",
            "-ss",
            str(seconds),
            "-fflags",
            "+discardcorrupt+genpts",
            "-err_detect",
            "ignore_err",
            "-i",
            str(video),
            "-an",
            "-frames:v",
            "1",
            "-vf",
            "scale=-2:360",
            "-q:v",
            "8",
            str(out_dir / f"seek_{index:02d}.jpg"),
        ]
        _run_ffmpeg(grab, timeout=20)
    found = _jpeg_frames(out_dir)
    _log(f"extract_frames_done count={len(found)} bytes={video.stat().st_size}")
    return found


def extract_audio_wav(video: Path, wav: Path) -> bool:
    ff = _ffmpeg()
    cmd = [
        ff,
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not wav.is_file():
        _log(f"extract_audio_fail rc={proc.returncode} err={(proc.stderr or '')[-300:]}")
        return False
    return True


def transcribe(audio: bytes) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI-compatible ASR (Groq whisper). Returns (text, words)."""
    provider = (os.environ.get("ASR_PROVIDER") or "none").strip().lower()
    api_key = (os.environ.get("ASR_API_KEY") or "").strip()
    if provider in ("", "none") or not api_key:
        _log("asr_skipped provider_or_key_missing")
        return "", []
    base = (os.environ.get("ASR_BASE_URL") or "https://api.groq.com/openai/v1").rstrip("/")
    model = (os.environ.get("ASR_MODEL") or "whisper-large-v3-turbo").strip()
    boundary = f"----streamclip{uuid4().hex}"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode()
        + audio
        + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="response_format"\r\n\r\nverbose_json\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="timestamp_granularities[]"\r\n\r\nword\r\n'
            f"--{boundary}--\r\n"
        ).encode()
    )
    req = urllib.request.Request(
        f"{base}/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        _log(f"asr_fail err={exc}")
        return "", []
    text = str(payload.get("text") or "")
    words: list[dict[str, Any]] = []
    for w in payload.get("words") or []:
        try:
            start_s = float(w.get("start", 0))
            end_s = float(w.get("end", start_s))
            words.append(
                {
                    "text": str(w.get("word") or w.get("text") or ""),
                    "start_ms": int(start_s * 1000),
                    "end_ms": int(end_s * 1000),
                }
            )
        except (TypeError, ValueError):
            continue
    return text, words


def _clamp_moment(raw: dict[str, Any]) -> dict[str, Any] | None:
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
    return {
        "start_ms": max(0, start),
        "end_ms": min(300_000, end),
        "score": max(0.0, min(1.0, float(raw.get("score") or 0))),
        "title": str(raw.get("title") or "Moment fort")[:200],
        "description": desc[:2000],
        "hashtags": hashtags,
        "category": str(raw.get("category") or "punchline")[:32],
        "words": words,
        "camera": {
            "detected": bool(cam_raw.get("detected")),
            "x": max(0, min(1919, int(cam_raw.get("x") or 960))),
            "y": max(0, min(1079, int(cam_raw.get("y") or 200))),
        },
    }


def _dedupe(moments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(moments, key=lambda m: (-float(m["score"]), int(m["start_ms"])))
    kept: list[dict[str, Any]] = []
    for moment in ordered:
        if any(
            not (
                int(moment["end_ms"]) <= int(k["start_ms"])
                or int(moment["start_ms"]) >= int(k["end_ms"])
            )
            for k in kept
        ):
            continue
        kept.append(moment)
    return sorted(kept, key=lambda m: int(m["start_ms"]))


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").replace("\n", " ")
    return text[:limit]


def luna_analyze(
    *,
    transcript_text: str,
    transcript_words: list[dict[str, Any]],
    frame_paths: list[Path],
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Call Bedrock GPT-6 Luna. Returns (moments, model_id, diagnostics)."""
    model = (os.environ.get("BEDROCK_MODEL") or DEFAULT_MODEL).strip()
    region = (os.environ.get("BEDROCK_REGION") or DEFAULT_BEDROCK_REGION).strip()
    diagnostics: dict[str, Any] = {
        "model": model,
        "region": region,
        "frames": len(frame_paths),
        "transcript_chars": len(transcript_text),
        "word_count": len(transcript_words),
        "transcript_preview": _clip(transcript_text, 280),
    }
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("boto3 required on dedicated box") from exc

    client = boto3.client("bedrock-runtime", region_name=region)
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
    for path in frame_paths[:MAX_FRAMES]:
        fmt = "jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "webp"
        content.append(
            {
                "image": {
                    "format": fmt,
                    "source": {"bytes": path.read_bytes()},
                }
            }
        )
    response = client.converse(
        modelId=model,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": 4096},
    )
    parts = response.get("output", {}).get("message", {}).get("content", [])
    text = " ".join(p.get("text", "") for p in parts if "text" in p)
    usage = response.get("usage") or {}
    diagnostics["stop_reason"] = response.get("stopReason")
    diagnostics["input_tokens"] = usage.get("inputTokens")
    diagnostics["output_tokens"] = usage.get("outputTokens")
    diagnostics["raw_preview"] = _clip(text, 1200)
    try:
        payload = _parse_json(text)
    except json.JSONDecodeError:
        diagnostics["parse_ok"] = False
        diagnostics["empty_reason"] = "invalid_json"
        _log(
            "luna_invalid_json "
            f"stop={diagnostics['stop_reason']} "
            f"in={diagnostics['input_tokens']} out={diagnostics['output_tokens']} "
            f"preview={diagnostics['raw_preview'][:400]}"
        )
        return [], model, diagnostics
    raw_items = payload.get("moments") or []
    if not isinstance(raw_items, list):
        raw_items = []
    diagnostics["parse_ok"] = True
    diagnostics["raw_moments"] = len(raw_items)
    moments: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            dropped.append({"reason": "not_object"})
            continue
        moment = _clamp_moment(item)
        if moment is None:
            dropped.append(
                {
                    "reason": "invalid_range",
                    "start_ms": item.get("start_ms"),
                    "end_ms": item.get("end_ms"),
                    "title": _clip(item.get("title"), 80),
                }
            )
            continue
        moments.append(moment)
    kept = _dedupe(moments)
    diagnostics["dropped"] = dropped[:8]
    diagnostics["dropped_count"] = len(dropped) + (len(moments) - len(kept))
    diagnostics["kept_moments"] = len(kept)
    if not kept:
        diagnostics["empty_reason"] = (
            "all_moments_dropped" if raw_items else "model_returned_no_moments"
        )
    else:
        diagnostics["empty_reason"] = ""
        diagnostics["moment_summaries"] = [
            {
                "title": _clip(m.get("title"), 80),
                "score": m.get("score"),
                "start_ms": m.get("start_ms"),
                "end_ms": m.get("end_ms"),
                "category": m.get("category"),
            }
            for m in kept[:8]
        ]
    _log(
        "luna_result "
        f"frames={len(frame_paths)} words={len(transcript_words)} "
        f"chars={len(transcript_text)} stop={diagnostics.get('stop_reason')} "
        f"raw={diagnostics['raw_moments']} kept={len(kept)} "
        f"dropped={diagnostics['dropped_count']} "
        f"reason={diagnostics['empty_reason']} "
        f"preview={diagnostics['raw_preview'][:400]}"
    )
    return kept, model, diagnostics


def _attach_words(
    moments: list[dict[str, Any]], words: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    for moment in moments:
        if moment.get("words"):
            continue
        moment["words"] = [
            w
            for w in words
            if w["end_ms"] >= moment["start_ms"] and w["start_ms"] <= moment["end_ms"]
        ]
    return moments


def post_analysis_result(payload: dict[str, Any]) -> bool:
    """POST analysis JSON to the API persist hook (derived from EVENT_URL)."""
    event_url = (os.environ.get("EVENT_URL") or "").strip()
    hook = (os.environ.get("HOOK") or os.environ.get("INGEST_HOOK_SECRET") or "").strip()
    if not event_url:
        _log("post_analysis_fail no_event_url")
        return False
    # .../ingest/hooks/event → .../ingest/hooks/segment-analysis
    if event_url.rstrip("/").endswith("/event"):
        url = event_url.rstrip("/")[: -len("/event")] + "/segment-analysis"
    else:
        url = event_url.rstrip("/") + "/segment-analysis"
    if "ingest_secret=" not in url and hook:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}ingest_secret={hook}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Streamclip-Ingest-Secret": hook,
        },
    )
    # The segment is deleted after this returns. Retry while the API or the
    # path back from the spot is down — the live is still recording.
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                _log(
                    f"post_analysis_ok status={resp.status} "
                    f"seq={payload.get('sequence')} attempt={attempt}"
                )
                return True
        except urllib.error.HTTPError as exc:
            err_body = exc.read()[:400] if exc.fp else b""
            _log(
                f"post_analysis_http status={exc.code} attempt={attempt} body={err_body!r}"
            )
            if 400 <= exc.code < 500 and exc.code != 429:
                return False
        except Exception as exc:  # noqa: BLE001
            _log(f"post_analysis_fail attempt={attempt} err={exc}")
        time.sleep(min(8, attempt * 2))
    return False


def analyze_segment_file(
    *,
    video_path: Path,
    stream_session_id: str,
    sequence: int,
    storage_key: str,
    size_bytes: int = 0,
) -> dict[str, Any]:
    """Full local pipeline for one 5-min MP4. Returns the payload posted to the API."""
    size_bytes = size_bytes or (video_path.stat().st_size if video_path.is_file() else 0)
    with tempfile.TemporaryDirectory(prefix="streamclip-onbox-") as tmp:
        tmp_dir = Path(tmp)
        frames_dir = tmp_dir / "frames"
        wav_path = tmp_dir / "audio.wav"
        frames = extract_frames(video_path, frames_dir)
        transcript_text = ""
        words: list[dict[str, Any]] = []
        if extract_audio_wav(video_path, wav_path):
            transcript_text, words = transcribe(wav_path.read_bytes())
        moments: list[dict[str, Any]] = []
        model = (os.environ.get("BEDROCK_MODEL") or DEFAULT_MODEL).strip()
        provider = "bedrock"
        diagnostics: dict[str, Any] = {
            "frames": 0,
            "transcript_chars": len(transcript_text),
            "word_count": len(words),
            "transcript_preview": _clip(transcript_text, 280),
            "model": model,
        }
        if frames or transcript_text.strip():
            try:
                moments, model, diagnostics = luna_analyze(
                    transcript_text=transcript_text,
                    transcript_words=words,
                    frame_paths=frames,
                )
                moments = _attach_words(moments, words)
                diagnostics["frames"] = len(frames)
            except Exception as exc:
                provider = "bedrock_failed"
                diagnostics["empty_reason"] = "luna_error"
                diagnostics["error"] = _clip(exc, 400)
                diagnostics["frames"] = len(frames)
                _log(f"luna_fail seq={sequence} err={exc}")
        else:
            provider = "skipped_no_media"
            diagnostics["empty_reason"] = "no_frames_no_transcript"
            diagnostics["frames"] = 0
            _log(f"skip_no_media seq={sequence} size={size_bytes}")

        payload = {
            "stream_session_id": stream_session_id,
            "sequence": sequence,
            "storage_key": storage_key,
            "size_bytes": size_bytes,
            "moments": moments,
            "transcript_text": transcript_text,
            "transcript_words": words,
            "frames": len(frames),
            "model": model,
            "provider": provider,
            "diagnostics": diagnostics,
        }
        ok = post_analysis_result(payload)
        payload["posted"] = ok
        _log(
            f"analyze_done seq={sequence} frames={len(frames)} "
            f"moments={len(moments)} words={len(words)} "
            f"chars={len(transcript_text)} provider={provider} "
            f"reason={diagnostics.get('empty_reason') or 'highlights'} "
            f"posted={ok} key={storage_key}"
        )
        return payload
