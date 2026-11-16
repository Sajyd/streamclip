# Phase 2 — Ingestion RTMPS / SRT

## Livré dans cette itération

### Plan de contrôle (API + UI)

- Création / rotation / révocation d'une clé d'ingestion STREAMCLIP (`stream_keys`)
- Secret affiché **une seule fois** (`public_id/sc_live_…`) ; seul un HMAC SHA-256 est stocké
- Hooks MediaMTX :
  - `POST /api/v1/ingest/hooks/auth` — autorise la publication (quota + concurrence)
  - `POST /api/v1/ingest/hooks/event` — déconnexion / ticks de traitement → `record_usage`
- Liste des `stream_sessions` récentes
- Capacités `ingest_keys` / `ingest_online` exposées par `/meta`
- Tableau de bord : panneau « Connexion OBS » + lives récents

### Données / quotas

- Refus à la publication si `quota.exhausted`
- Refus si `max_concurrent_streams` atteint (reprise de session ouverte autorisée)
- Ticks `processed_ms` → `UsageKind.LIVE_PROCESSING` (idempotents)

### Data plane

- Image / config MediaMTX fournie (`infrastructure/docker/mediamtx.yml`, profil compose `ingest`)
- **Pas encore** : Terraform EC2/VPC/NLB, TLS RTMPS managé, buffer FFmpeg → S3, segments

## Non livré (volontaire)

- `LIVE_PROCESSING_AVAILABLE` reste `false` (pas de clips, pas de Stripe live)
- Serveur d'ingestion public non déployé (`INGEST_PUBLIC_HOST` vide en prod pour l'instant)
- Phases 3–5 (ASR, vision, clips)

## Activer l'ingestion réelle

1. Déployer MediaMTX (compose profil `ingest` en local, EC2 ensuite)
2. `INGEST_PUBLIC_HOST`, `INGEST_HOOK_SECRET` sur l'API et MediaMTX
3. Vérifier `capabilities.ingest_online === true`
4. Publier depuis OBS → session `live` → tick → `completed`
5. Seulement après pipeline clips : `LIVE_PROCESSING_AVAILABLE = True`
