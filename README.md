# STREAMCLIP

SaaS multi-tenant qui reçoit une copie de vos lives (clé d’ingestion STREAMCLIP),
analyse le contenu et prépare des clips verticaux sous-titrés.

> **Accès anticipé.** Le traitement des lives et la génération de clips ne sont
> pas encore ouverts (`live_processing: false`). Cette version livre le plan de
> contrôle : comptes, multi-tenant, abonnements Stripe (mode test), stockage S3,
> export / suppression RGPD, et l’interface associée.

## Architecture (déploiement actuel)

| Couche | Technologie |
| --- | --- |
| Web | Next.js 16 (App Router, Cache Components) sur Vercel |
| API | FastAPI (Python 3.12) sur Vercel Services (beta) |
| Base | PostgreSQL (Neon), RLS + rôle `streamclip_app` |
| Fichiers | S3 `stream-clip` (eu-north-1), identité IAM à moindre privilège |
| Paiement | Stripe Billing (catalogue + Checkout + portail + webhooks) |

Le navigateur ne parle jamais à l’API : le front agit en BFF (Server Actions /
Route Handlers) et prouve son identité avec `BFF_SHARED_SECRET`.

## Démarrage local (sans Docker)

Prérequis : Node 22, Python 3.12, `uv`, OpenSSL. Optionnel : Stripe CLI, AWS CLI.

```bash
# 1. Dépendances
cd backend && uv sync && cd ../frontend && npm ci && cd ..

# 2. Secrets opérateur (git-ignorés)
cp .env.example .env   # puis renseigner Stripe test / S3 si besoin
# scripts/aws-runtime-key.sh issue   # une fois l’identité Terraform créée

# 3. Base + migrations
scripts/dev.sh setup

# 4. Trois terminaux
scripts/dev.sh api      # http://127.0.0.1:8000
scripts/dev.sh web      # http://localhost:3000
scripts/dev.sh stripe   # relais des webhooks Stripe (mode test)
```

Commandes utiles :

```bash
scripts/dev.sh cli migrate
scripts/dev.sh cli stripe-sync
scripts/dev.sh cli promote-admin --email vous@exemple.com
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run lint && npm run typecheck && npm run build
```

## Docker Compose

```bash
docker compose up --build
docker compose exec api python -m app.cli migrate
```

Les Dockerfiles n’ont pas été exécutés sur cette machine (pas de démon Docker).
Ils sont fournis pour un environnement qui en dispose.

## Variables d’environnement

Voir [`.env.example`](.env.example). En production (Vercel, cible `production`
uniquement) :

- `ENVIRONMENT=production`, `PUBLIC_APP_URL=https://…`
- `DATABASE_URL` (Neon pooler), `DATABASE_MIGRATION_URL` (endpoint direct)
- `JWT_SIGNING_KEYS`, `BFF_SHARED_SECRET`, `CRON_SECRET`
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`
- `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
- `EMAIL_TRANSPORT=none` tant que SES n’est pas sorti du sandbox
- `API_INTERNAL_URL` est injecté par la *service binding* Vercel (ne pas le fixer)

## Infrastructure AWS

```bash
scripts/terraform.sh bootstrap apply
scripts/terraform.sh production apply
scripts/aws-runtime-key.sh issue
```

État distant : bucket `streamclip-tfstate-<account-id>`. L’utilisateur IAM
`streamclip-production-runtime` n’a accès qu’aux préfixes `tenants/` et `tmp/`.

## Offres

| Offre | Prix TTC / mois | Quota |
| --- | --- | --- |
| Free | 0 € | 1 h, 3 clips / live |
| Starter | 19 € | 20 h |
| Creator | 49 € | 60 h |
| Pro | 99 € | 150 h |
| Business | 199 € | 400 h |

Tant que le traitement des lives n’est pas livré, les clés Stripe **live** ne
peuvent pas ouvrir un Checkout (`sales_not_open`). Le mode test reste utilisable.

## Documentation

- [`docs/architecture/`](docs/architecture/) — conception, coûts, risques
- [`docs/deployment/`](docs/deployment/) — déploiement, sauvegarde, rollback
- [`docs/api/`](docs/api/) — contrat HTTP

## Licence

Propriétaire. Tous droits réservés.
