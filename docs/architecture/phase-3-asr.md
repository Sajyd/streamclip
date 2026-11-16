# Phase 3 — Transcription / ASR

## Livré

- Découpage automatique en fenêtres ~5 min (`AnalysisWindow`) dès que les ticks
  d'ingestion franchissent une borne
- Job `AnalysisJob(kind=transcription)` + tâche queue `analysis.transcribe`
- Fournisseurs ASR (`ASR_PROVIDER`) :
  - `none` — skip explicite
  - `console` — logue la réception audio, pas de texte inventé
  - `openai_compatible` — HTTP Groq/OpenAI si `ASR_API_KEY` est défini
- Sans segment audio : job/window en `skipped` avec `no_media_segment` (honnête)
- Drain serverless des tâches `analysis` après un tick MediaMTX

## Pas encore

- Écriture des `MediaSegment` audio depuis MediaMTX/FFmpeg
- Diarisation, LLM, highlights, clips
- `LIVE_PROCESSING_AVAILABLE` reste `false`

## Activation ASR réel

```bash
ASR_PROVIDER=openai_compatible
ASR_API_KEY=gsk_…
ASR_BASE_URL=https://api.groq.com/openai/v1
ASR_MODEL=whisper-large-v3-turbo
```

Les appels HTTP ne partent que si la clé est présente. Sans média bufferisé,
les jobs restent `skipped` jusqu'à la phase buffer.
