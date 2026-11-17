# Phase 4 — pipeline segments 5 min + highlights Remotion

## Livré

- Worker CLI `live-loop` / `segment-analyze` : record HD 5 min → S3
  `tmp/lives/<session>/` → frames 480p + ASR → Bedrock Nova Lite (Luna) →
  `highlight_candidates` JSON (score, titre, description, hashtags, words,
  camera x/y 1920x1080).
- API `GET /highlights`, `GET /highlights/{id}`, `GET .../media-url`.
- Migration `0004` : `GRANT SELECT` tenant sur `highlight_candidates`.
- Frontend `/highlights` + Remotion Player 9:16 (viewport cam optionnel).
- Terraform ingest node : FFmpeg, IAM S3 Get/Put `tmp/*` + Bedrock Converse.
- Instance cible : **t4g.small** uniquement (pas de c7g.large).

## Non livré / hors scope

- EC2 MediaMTX encore `enable_ingest_node=false` (à appliquer quand l’hôte
  public est prêt).
- `LIVE_PROCESSING_AVAILABLE` reste `false` (vente live Stripe fermée).
- Terminaison auto de l’instance en fin de live (hook stop → stop EC2) à
  brancher côté ops.
