#!/usr/bin/env python3
"""On-box 5-min segment analysis for the dedicated :8080 agent.

Runs on the EC2 spot with stdlib + boto3 (installed at boot):
  keyframes at fixed times → Amazon Transcribe (word times) → Bedrock GPT-6 Luna →
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

# One still every 10s (≤24 per 5-min window). Keyframe-only so the decoder
# does not fight the RTMP reader on a 2 vCPU box.
FRAME_EVERY_SEC = 10
MAX_FRAMES = 30
EXTRACT_TIMEOUT_S = 20
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
- start_ms et end_ms sont relatifs au début de cet extrait, en millisecondes.
- Le JSON words donne start_ms/end_ms de chaque mot. Le JSON frames donne time_ms de chaque image.
- Place le moment sur les mots de la réaction (un cri, un let's go, un rire, une explosion).
- S'il n'y a pas de réaction claire: {"moments": []}.
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


def extract_frames(video: Path, out_dir: Path) -> list[tuple[Path, int]]:
    """One JPEG at 0s, 10s, 20s, … on the finished segment file.

    Each still is sought on its own. A finished MP4 is not the live RTMP read,
    so this does not stall the recorder. The timestamp is the position asked
    for, in milliseconds from the start of the segment.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if not video.is_file() or video.stat().st_size < 10_000:
        return []
    ff = _ffmpeg()
    found: list[tuple[Path, int]] = []
    for index in range(MAX_FRAMES):
        time_ms = index * FRAME_EVERY_SEC * 1000
        dest = out_dir / f"t{time_ms:07d}.jpg"
        grab = [
            ff,
            "-y",
            "-threads",
            "1",
            "-ss",
            f"{time_ms / 1000:.3f}",
            "-i",
            str(video),
            "-an",
            "-frames:v",
            "1",
            "-vf",
            "scale=-2:360",
            "-q:v",
            "8",
            str(dest),
        ]
        _run_ffmpeg(grab, timeout=EXTRACT_TIMEOUT_S)
        if not dest.is_file() or dest.stat().st_size <= 500:
            break
        found.append((dest, time_ms))
    _log(
        "extract_frames_ok "
        f"count={len(found)} every_s={FRAME_EVERY_SEC} "
        f"times={[time_ms for _, time_ms in found]}"
    )
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


def _words_from_transcribe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Amazon Transcribe items. Times are seconds from the start of the segment."""
    words: list[dict[str, Any]] = []
    for item in items:
        content = str(((item.get("alternatives") or [{}])[0]).get("content") or "")
        if not content:
            continue
        if item.get("type") == "punctuation" and words:
            words[-1]["text"] = f"{words[-1]['text']}{content}"
            continue
        try:
            start_ms = int(float(item["start_time"]) * 1000)
            end_ms = int(float(item["end_time"]) * 1000)
        except (KeyError, TypeError, ValueError):
            continue
        words.append({"text": content, "start_ms": start_ms, "end_ms": max(start_ms + 1, end_ms)})
    return words


def transcribe(audio: bytes, storage_key: str = "") -> tuple[str, list[dict[str, Any]]]:
    """Amazon Transcribe. Each word has start_ms/end_ms from the start of the segment."""
    provider = (os.environ.get("ASR_PROVIDER") or "transcribe").strip().lower()
    if provider in ("", "none"):
        _log("asr_skipped provider_none")
        return "", []
    bucket = (os.environ.get("S3_BUCKET") or "").strip()
    region = (os.environ.get("AWS_REGION") or "eu-north-1").strip()
    key = storage_key.strip().lstrip("/")
    if not bucket or (not key and not audio):
        _log("asr_skipped no_media")
        return "", []
    try:
        import boto3  # type: ignore[import-untyped]

        s3 = boto3.client("s3", region_name=region)
        jobs = boto3.client("transcribe", region_name=region)
    except Exception as exc:  # noqa: BLE001
        _log(f"asr_fail err={exc}")
        return "", []
    uploaded = ""
    if not key:
        uploaded = f"tmp/asr/{int(time.time() * 1000)}.wav"
        key = uploaded
        s3.put_object(Bucket=bucket, Key=key, Body=audio, ContentType="audio/wav")
    job_name = f"sc-{int(time.time() * 1000)}"
    out_key = f"tmp/asr/{job_name}.json"
    try:
        jobs.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": f"s3://{bucket}/{key}"},
            IdentifyMultipleLanguages=True,
            LanguageOptions=["fr-FR", "en-US", "en-GB", "es-ES", "de-DE"],
            OutputBucketName=bucket,
            OutputKey=out_key,
        )
        status = "IN_PROGRESS"
        failure = ""
        for _ in range(90):
            job = jobs.get_transcription_job(TranscriptionJobName=job_name)["TranscriptionJob"]
            status = job.get("TranscriptionJobStatus") or ""
            if status in ("COMPLETED", "FAILED"):
                failure = str(job.get("FailureReason") or "")
                break
            time.sleep(2)
        if status != "COMPLETED":
            _log(f"asr_fail status={status} reason={failure[:240]}")
            return "", []
        try:
            raw = s3.get_object(Bucket=bucket, Key=out_key)["Body"].read()
        except Exception:  # noqa: BLE001
            out_key = f"{out_key}.json"
            raw = s3.get_object(Bucket=bucket, Key=out_key)["Body"].read()
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        _log(f"asr_fail err={exc}")
        return "", []
    finally:
        try:
            jobs.delete_transcription_job(TranscriptionJobName=job_name)
        except Exception:  # noqa: BLE001
            pass
        for extra in (out_key, uploaded):
            if not extra:
                continue
            try:
                s3.delete_object(Bucket=bucket, Key=extra)
            except Exception:  # noqa: BLE001
                pass
    results = payload.get("results") or {}
    words = _words_from_transcribe_items(results.get("items") or [])
    text = " ".join(part.get("transcript", "") for part in results.get("transcripts") or []).strip()
    if not text:
        text = " ".join(word["text"] for word in words).strip()
    _log(
        f"asr_ok words={len(words)} chars={len(text)} "
        f"first_ms={words[0]['start_ms'] if words else 0} "
        f"last_ms={words[-1]['end_ms'] if words else 0} text={_clip(text, 240)}"
    )
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


def _converse_text(response: dict[str, Any]) -> str:
    parts = response.get("output", {}).get("message", {}).get("content", [])
    return " ".join(
        part.get("text", "") for part in parts if isinstance(part, dict) and "text" in part
    ).strip()


def _luna_timeline(
    transcript_text: str,
    transcript_words: list[dict[str, Any]],
    frames: list[tuple[Path, int]],
) -> str:
    """JSON clock Luna uses to place a highlight inside the segment."""
    payload = {
        "words": [
            {
                "text": str(word.get("text") or ""),
                "start_ms": int(word["start_ms"]),
                "end_ms": int(word["end_ms"]),
            }
            for word in transcript_words[:2000]
            if "start_ms" in word and "end_ms" in word
        ],
        "frames": [
            {"index": index + 1, "time_ms": time_ms} for index, (_, time_ms) in enumerate(frames)
        ],
        "transcript": transcript_text[:12000],
    }
    return json.dumps(payload, ensure_ascii=False)


def _luna_content(
    transcript_text: str,
    transcript_words: list[dict[str, Any]],
    frames: list[tuple[Path, int]],
) -> list[dict[str, Any]]:
    """Timeline JSON, then each distinct JPEG labeled with its segment time.

    Repeating the same JPEG several times makes Bedrock bill 2 input tokens and
    ignore the transcript. Identical bytes are sent once; every timestamp stays
    in the JSON.
    """
    content: list[dict[str, Any]] = [
        {"text": _luna_timeline(transcript_text, transcript_words, frames)}
    ]
    seen: set[bytes] = set()
    for _path, time_ms in frames:
        data = _path.read_bytes()
        if data in seen:
            continue
        seen.add(data)
        content.append({"text": f"frame at {time_ms} ms"})
        content.append({"image": {"format": "jpeg", "source": {"bytes": data}}})
    return content


def luna_analyze(
    *,
    transcript_text: str,
    transcript_words: list[dict[str, Any]],
    frames: list[tuple[Path, int]],
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Call Bedrock GPT-6 Luna. Returns (moments, model_id, diagnostics)."""
    model = (os.environ.get("BEDROCK_MODEL") or DEFAULT_MODEL).strip()
    region = (os.environ.get("BEDROCK_REGION") or DEFAULT_BEDROCK_REGION).strip()
    frame_times = [time_ms for _, time_ms in frames]
    diagnostics: dict[str, Any] = {
        "model": model,
        "region": region,
        "frames": len(frames),
        "frame_times_ms": frame_times,
        "transcript_chars": len(transcript_text),
        "word_count": len(transcript_words),
        "transcript_preview": _clip(transcript_text, 280),
        "word_start_ms": transcript_words[0]["start_ms"] if transcript_words else 0,
        "word_end_ms": transcript_words[-1]["end_ms"] if transcript_words else 0,
    }
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("boto3 required on dedicated box") from exc

    client = boto3.client("bedrock-runtime", region_name=region)
    content = _luna_content(transcript_text, transcript_words, frames)
    response = client.converse(
        modelId=model,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": 4096},
    )
    text = _converse_text(response)
    usage = response.get("usage") or {}
    diagnostics["stop_reason"] = response.get("stopReason")
    diagnostics["input_tokens"] = usage.get("inputTokens")
    diagnostics["output_tokens"] = usage.get("outputTokens")
    diagnostics["raw_preview"] = _clip(text, 1200)
    diagnostics["unique_frames"] = sum(1 for block in content if "image" in block)
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
        f"frames={len(frames)} unique={diagnostics['unique_frames']} "
        f"in={diagnostics['input_tokens']} words={len(transcript_words)} "
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
            transcript_text, words = transcribe(wav_path.read_bytes(), storage_key)
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
                    frames=frames,
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
