# Phase 4 — pipeline segments 5 min + highlights Remotion

## Livré

- Worker CLI `live-loop` / `segment-analyze` : record HD 5 min → S3
  `tmp/lives/<session>/` → frames 480p + ASR → Bedrock GPT-6 Luna →
  `highlight_candidates` JSON (score, titre, description, hashtags, words,
  camera x/y 1920x1080).
- API `GET /highlights`, `GET /highlights/{id}`, `GET .../media-url`.
- Migration `0004` : `GRANT SELECT` tenant sur `highlight_candidates`.
- Frontend `/highlights` + Remotion Player 9:16 (viewport cam optionnel).
- Terraform ingest node : FFmpeg, IAM S3 Get/Put `tmp/*` + Bedrock Converse.
- Instance cible : **t4g.small** uniquement.

## Ops

- Activer EC2 : `ENABLE_INGEST_NODE=true` + `INGEST_HOOK_SECRET` +
  `INGEST_API_AUTH_URL` puis `scripts/terraform.sh production apply`.
- Puis `INGEST_PUBLIC_HOST=<eip>` + `INGEST_HOOK_SECRET` sur Vercel.
- `LIVE_PROCESSING_AVAILABLE` reste `false` (vente live Stripe fermée) jusqu’à
  validation end-to-end.
