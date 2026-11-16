# API STREAMCLIP AI

Préfixe : `/api/v1`. Enveloppe d'erreur :

```json
{ "error": { "code": "…", "message": "…", "details": {}, "request_id": "…" } }
```

Les routes authentifiées attendent `Authorization: Bearer <access_token>`.
Le front Next.js appelle l'API uniquement côté serveur, avec en plus :

- `x-streamclip-bff-token` — secret partagé (`BFF_SHARED_SECRET`)
- `x-streamclip-client-ip` / `x-streamclip-client-ua` — IP et UA du visiteur

## Principales routes

| Méthode | Chemin | Auth | Description |
| --- | --- | --- | --- |
| GET | `/meta` | non | Capacités de la plateforme |
| GET | `/plans` | non | Catalogue (prix TTC depuis la base) |
| GET | `/healthz` | non | Vivacité |
| GET | `/readyz` | non | Base + migrations (+ stockage si `deep`) |
| POST | `/auth/register` | non | Inscription |
| POST | `/auth/login` | non | Connexion |
| POST | `/auth/refresh` | non | Rotation des jetons |
| POST | `/auth/logout` | oui | Déconnexion de la session courante |
| POST | `/auth/logout-all` | oui | Déconnexion de toutes les sessions |
| GET | `/sessions` | oui | Appareils connectés |
| DELETE | `/sessions/{id}` | oui | Révoquer une session |
| POST | `/auth/verify-email` | non | Confirmer l'e-mail |
| POST | `/auth/forgot-password` | non | Demande de réinitialisation |
| POST | `/auth/reset-password` | non | Nouveau mot de passe |
| POST | `/auth/change-password` | oui | Changer le mot de passe |
| GET | `/me` | oui | Profil + organisation + capacités |
| PATCH | `/me` | oui | Mettre à jour le profil |
| PATCH | `/organization` | admin org | Renommer l'espace |
| GET | `/notifications` | oui | Notifications |
| POST | `/notifications/read` | oui | Marquer comme lues |
| GET | `/billing/overview` | oui | Offre, quota, état |
| POST | `/billing/checkout-session` | admin org | URL Checkout Stripe |
| POST | `/billing/portal-session` | admin org | URL portail client |
| POST | `/billing/webhooks/stripe` | signature | Webhooks Stripe |
| GET/POST | `/account/exports` | admin org | Liste / demande d'export |
| GET | `/account/exports/{id}/download-url` | admin org | URL présignée |
| POST | `/account/delete` | admin org | Suppression du compte |
| GET | `/admin/users` | staff | Liste des comptes |
| POST | `/admin/users/{id}/suspend` | admin | Suspendre |
| POST | `/admin/users/{id}/reactivate` | admin | Réactiver |
| GET | `/internal/cron/maintenance` | `CRON_SECRET` | Ménage quotidien |

La source de vérité des schémas est `backend/app/schemas/api.py`.
