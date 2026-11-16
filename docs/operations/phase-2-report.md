# Rapport phase 2 — Ingestion (plan de contrôle)

Date : 2026-11-17 · Branche `prod` · Commits `396a929` + correctif secret

## URL

https://streamclip-phi.vercel.app

## Livré

- API clés d'ingestion (création / rotation / révocation)
- Hooks MediaMTX auth + events (quota + sessions)
- Dashboard « Connexion OBS » + lives récents
- Config MediaMTX + profil Docker Compose `ingest`
- Capacités `ingest_keys` / `ingest_online`
- 132 tests backend (dont 5 ingest)

## Vérifié en production

- Panneau OBS visible sur le tableau de bord
- Création de clé (`OBS Nora`) OK
- Badge « Serveur d'ingestion hors ligne » (pas de `INGEST_PUBLIC_HOST`)

## Pas encore

- MediaMTX / EC2 / RTMPS public
- Buffer FFmpeg → S3 / clips (`LIVE_PROCESSING_AVAILABLE` reste false)
- Terraform data plane

## Suite

1. Déployer MediaMTX + `INGEST_PUBLIC_HOST` / `INGEST_HOOK_SECRET`
2. Phase 3 : transcription / ASR sur fenêtres d'analyse
