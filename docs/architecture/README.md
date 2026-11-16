# Architecture — STREAMCLIP AI

Livrables du §24 du cahier des charges. État : **phase 1 livrée** (fondations,
auth, multi-tenant, facturation, stockage, interface). Les phases 2–5
(ingestion, transcription, intelligence vidéo, clips) ne sont pas déployées.

## 1. Architecture technique

```
[Navigateur]
    │  HTTPS (cookies HttpOnly __Host-sc_*)
    ▼
[Vercel · service web · Next.js]
    │  binding API_INTERNAL_URL + BFF_SHARED_SECRET
    ▼
[Vercel · service api · FastAPI] ── PostgreSQL (Neon, RLS)
                                 ── S3 (stream-clip, eu-north-1)
                                 ── Stripe (webhooks + Checkout)
                                 ── file de tâches Postgres
```

Pas de Redis en phase 1 : rate limiting et file de tâches sont en PostgreSQL.
L'ingestion live (MediaMTX / EC2) sera un plan de données séparé, facturé au
temps effectivement traité.

## 2. Diagramme des services

Voir aussi `vercel.json` (Services beta) :

- `web` — pages marketing, auth, tableau de bord, BFF
- `api` — REST `/api/v1/*` exposé pour webhooks, cron, health ; le reste via binding
- Cron quotidien `0 4 * * *` → `/api/v1/internal/cron/maintenance`

## 3. Schéma de base

~38 tables (identité, sessions, abonnements, quotas, tâches, audit, assets…).
Migrations Alembic `0001`–`0003`. Isolation : `SET LOCAL ROLE streamclip_app` +
`SET LOCAL app.organization_id` + politiques RLS. Défense en profondeur, pas un
bac à sable SQL.

## 4. Flux live → clip (cible, non livré)

OBS → RTMPS/SRT (clé d'ingestion STREAMCLIP) → MediaMTX → buffer court →
fenêtres d'analyse → ASR → LLM cascade → scoring multimodal → découpe FFmpeg
9:16 + sous-titres → objet S3 → bibliothèque. Compteur d'usage idempotent.

## 5. Choix IA et coûts (ordre de grandeur)

Budgets 10 % HT / heure : Starter ≈ 0,079 €/h … Business ≈ 0,041 €/h.

| Brique | Candidat | Coût indicatif |
| --- | --- | --- |
| ASR | Groq whisper-large-v3-turbo ou Parakeet auto-hébergé | ≈ 0,04 USD/h (API) |
| LLM | Nova Lite / Gemini Flash-Lite (cascade) | ≈ 0,014–0,017 USD/h |
| Compute | EC2 c7g.large spot | ≈ 0,034 USD/h |

Amazon Transcribe batch (0,36 USD/h) est **incompatible** avec la règle des 10 %
comme défaut. Les coûts doivent être mesurés avant toute ouverture commerciale.

## 6. Architecture AWS

- Compte `688567308267`, région `eu-north-1`
- Bucket `stream-clip` : Block Public Access, TLS≥1.2, lifecycle tmp/ + tag short
- IAM runtime `streamclip-production-runtime` (préfixes `tenants/`, `tmp/` uniquement)
- State Terraform distant `streamclip-tfstate-<account>`
- SES non opérationnel (sandbox) → `EMAIL_TRANSPORT=none` en prod au démarrage

## 7. Risques techniques

| Risque | Mitigation |
| --- | --- |
| Vercel Services (beta) | Fallback documenté : deux projets + rewrite |
| Hobby plan : pas d'usage commercial, cron quotidien max | Passer Pro avant ouverture commerciale |
| Coûts IA > 10 % | Mesure réelle, cascade, auto-hébergement ASR |
| Fuite cross-tenant | RLS + tests + jamais faire confiance au front |
| Webhooks Stripe manqués | Endpoint dédié, idempotence, 5xx → redelivery |
| Repo GitHub public | Aucun secret dans le dépôt ; rotation des clés collées |

## 8. Comptes externes / validations

Stripe (test fourni), AWS (iamuser2 + runtime), Neon, Vercel, GitHub.
Publication sociale (phases 8) : OAuth officiel uniquement, jamais de mot de passe
plateforme. Identité légale de l'éditeur à renseigner (`LEGAL_PUBLISHER`) avant
ouverture commerciale.

## 9. Plan de développement (phases)

| Phase | Statut |
| --- | --- |
| 1 Fondations / auth / multi-tenant / billing / UI | **Livrée** |
| 2 Ingestion RTMPS/SRT | **Plan de contrôle livré** (clés + hooks) ; MediaMTX/EC2 à déployer |
| 3 Audio / transcription | À faire |
| 4 Intelligence vidéo | À faire |
| 5 Génération de clips | À faire |
| 6 Dashboard lives/clips | Partiel (shell honnête) |
| 7 Abonnements | **Livrée** (mode test) |
| 8 Publication sociale | À faire |
| 9 Admin | Partiel (utilisateurs) |
| 10 Production | En cours (ce dépôt) |
