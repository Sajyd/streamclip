# Rapport de fin de phase 1 — STREAMCLIP

Date : 2026-11-16 · Branche : `prod` · Commit initial : `eb1bcb4`

## URL de production

**https://streamclip-phi.vercel.app**

(alias équipe : `streamclip-sajyds-projects.vercel.app`.  
`streamclip.vercel.app` appartient à un **autre** projet Vercel plus ancien — ne pas l'utiliser.)

## Ce qui est construit et vérifié

| Zone | État |
| --- | --- |
| Schéma PostgreSQL (~39 tables), Alembic 0001–0003, RLS | OK (Neon migré) |
| API FastAPI (auth, sessions, RBAC, audit, rate limit, tâches, billing, RGPD) | OK |
| Tests backend | 127 passed, 5 skipped (live opt-in) |
| Frontend Next.js (landing, auth, dashboard, billing, settings, admin) | OK |
| Stripe mode **test** (catalogue, Checkout, portail, webhook prod) | OK |
| S3 `stream-clip` + identité IAM runtime | OK (`readyz?deep=true` → storage ok) |
| Déploiement Vercel Services (web + api) depuis GitHub `prod` | OK |
| Inscription réelle en production (`nora.prod@example.com` → dashboard Free) | OK |

## Limites honnêtes (à ne pas dissimuler)

1. **Traitement live / clips non ouverts** (`LIVE_PROCESSING_AVAILABLE = false`). L'UI l'affiche.
2. **Paiements en mode test** uniquement. Les clés live ne peuvent pas ouvrir un Checkout tant que le live n'est pas livré.
3. **E-mail** : `EMAIL_TRANSPORT=none` (SES sandbox). Pas d'e-mail de vérification réel en prod pour l'instant.
4. **Plan Vercel Hobby** : usage commercial interdit par les conditions Vercel ; cron quotidien max. Passer Pro avant ouverture commerciale.
5. **Vercel Services** est en **beta**.
6. **Identité légale** (`LEGAL_PUBLISHER`) non renseignée — pages légales le signalent.
7. **Repo GitHub public** : aucun secret dans le dépôt ; rotation si une clé a fuité ailleurs.
8. Phases 2–5 (ingestion, ASR, vision, clips) et 8 (publication sociale) **non construites**.
9. Dockerfiles fournis mais **non exécutés** ici (pas de démon Docker sur la machine de build).

## Commandes utiles

```bash
scripts/dev.sh setup && scripts/dev.sh api && scripts/dev.sh web
cd backend && uv run pytest -q
scripts/terraform.sh production apply
scripts/aws-runtime-key.sh issue
# Depuis backend/, contre Neon :
python -m app.cli migrate
python -m app.cli stripe-sync --webhook-url https://streamclip-phi.vercel.app/api/v1/billing/webhooks/stripe
```

## Suite recommandée

1. Domaine custom + Vercel Pro si usage commercial.
2. SES hors sandbox + `EMAIL_TRANSPORT=ses`.
3. Phase 2 : MediaMTX / ingestion RTMPS-SRT.
4. Mesure réelle des coûts IA avant toute bascule Stripe live.
