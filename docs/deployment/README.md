# Déploiement

## Ordre recommandé

1. Appliquer Terraform (`scripts/terraform.sh production apply`) et émettre la clé runtime.
2. Pousser la branche `prod` sur GitHub.
3. Créer le projet Vercel lié au dépôt (Services beta : `vercel.json` à la racine).
4. Migrer Neon sur l'endpoint **direct** (`DATABASE_MIGRATION_URL`).
5. `python -m app.cli stripe-sync --webhook-url https://<domaine>/api/v1/billing/webhooks/stripe`
6. Définir **toutes** les variables d'environnement sur la cible `production` uniquement.
7. Déployer, vérifier `/api/v1/readyz`, inscription, Checkout test, webhook, cron.

## Sauvegarde / restauration

- **Base** : snapshots Neon (point-in-time recovery). Restauration = nouveau branchement Neon + mise à jour de `DATABASE_URL`.
- **S3** : versioning désactivé volontairement (effacement RGPD réel). Les exports ont une TTL de 7 jours.
- **Stripe** : source de vérité des abonnements ; le miroir local se reconstruit via les webhooks.

## Mise à jour

1. Merge sur `prod` → déploiement Vercel automatique.
2. Si une migration est ajoutée : `DATABASE_MIGRATION_URL=… python -m app.cli migrate` **avant** ou immédiatement après le déploiement (le `/readyz` échoue tant que la révision attendue n'est pas appliquée).
3. `stripe-sync` après tout changement de catalogue.

## Rollback

- Vercel : rollback du déploiement précédent (Services = rollback atomique web + API).
- Base : ne jamais `downgrade` en production sans procédure ; préférer une migration corrective forward-only.
- Stripe : les prix sont versionnés ; un ancien `stripe_price_id` reste facturable jusqu'au prochain sync.

## Rotation des secrets

| Secret | Procédure |
| --- | --- |
| JWT | Ajouter `kid2:secret` en tête de `JWT_SIGNING_KEYS`, déployer, retirer l'ancien kid après TTL refresh (30 j). |
| BFF / CRON | Régénérer, déployer web + API ensemble. |
| S3 runtime | `scripts/aws-runtime-key.sh issue` puis `prune`, mettre à jour Vercel. |
| Stripe webhook | Recréer l'endpoint (`stripe-sync --webhook-url …`), mettre à jour `STRIPE_WEBHOOK_SECRET`. |

## Activer l'e-mail

1. Vérifier un domaine dans SES (eu-north-1) et sortir du sandbox.
2. `EMAIL_TRANSPORT=ses`, `EMAIL_FROM=…`, `SES_REGION=eu-north-1`.
3. Vérifier qu'un enregistrement crée bien un e-mail (pas `console`).

## Passer Stripe en live

1. Livrer le pipeline live (`LIVE_PROCESSING_AVAILABLE = True`).
2. Remplacer les clés test par des clés **restricted** live + webhook live.
3. Relancer `stripe-sync` contre le compte live.
4. Vérifier `billing_test_mode: false` sur `/meta`.
