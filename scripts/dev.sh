#!/usr/bin/env bash
# Run STREAMCLIP AI on this machine, without Docker.
#
#   scripts/dev.sh setup     # local database + roles + migrations (run once)
#   scripts/dev.sh api       # API on http://127.0.0.1:8000 (auto-reload)
#   scripts/dev.sh web       # web application on http://localhost:3000
#   scripts/dev.sh stripe    # forward Stripe test-mode webhooks to the local API
#   scripts/dev.sh cli ...   # python -m app.cli ... against the local database
#
# Local-only secrets are generated once into .localdev/dev.env (git-ignored).
# Optional integrations are read from .env (Stripe test keys, S3 bucket) and
# .localdev/aws_runtime.env (the restricted S3 identity); without them the
# application runs with those features reported as unavailable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="$ROOT/.localdev"
DEV_ENV="$LOCAL_DIR/dev.env"
PG_PORT="${PG_PORT:-55432}"
OWNER_ROLE="streamclip_owner"
OWNER_PASSWORD="streamclip"
DATABASE="streamclip_dev"

random_secret() {
  openssl rand -base64 48 | tr -d '\n=' | tr '+/' '-_'
}

ensure_dev_env() {
  if [ -f "$DEV_ENV" ]; then
    return
  fi
  mkdir -p "$LOCAL_DIR"
  (
    umask 077
    {
      echo "JWT_SIGNING_KEYS=local:$(random_secret)"
      echo "BFF_SHARED_SECRET=$(random_secret)"
      echo "CRON_SECRET=$(random_secret)"
    } >"$DEV_ENV"
  )
  echo "Generated local secrets in ${DEV_ENV#"$ROOT"/}" >&2
}

load_env() {
  ensure_dev_env
  set -a
  # shellcheck disable=SC1090,SC1091
  {
    [ -f "$ROOT/.env" ] && . "$ROOT/.env"
    [ -f "$LOCAL_DIR/aws_runtime.env" ] && . "$LOCAL_DIR/aws_runtime.env"
    . "$DEV_ENV"
  }
  set +a
  # The operator's administrator credentials never reach the application.
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN LIVE_DATABASE_URL
  export ENVIRONMENT="local"
  export PUBLIC_APP_URL="http://localhost:3000"
  export DATABASE_URL="postgresql://$OWNER_ROLE:$OWNER_PASSWORD@127.0.0.1:$PG_PORT/$DATABASE"
  export EMAIL_TRANSPORT="${EMAIL_TRANSPORT:-console}"
  export API_INTERNAL_URL="http://127.0.0.1:8000"
  if [ -n "${S3_BUCKET:-}" ]; then
    export S3_REGION="${S3_REGION:-${AWS_REGION:-}}"
  fi
}

python_bin() {
  if [ ! -x "$ROOT/backend/.venv/bin/python" ]; then
    echo "Missing backend/.venv: run 'cd backend && uv sync' first." >&2
    exit 1
  fi
  echo "$ROOT/backend/.venv/bin/python"
}

cmd="${1:-}"
[ $# -gt 0 ] && shift
case "$cmd" in
  setup)
    "$ROOT/scripts/dev-postgres.sh" start
    "$ROOT/scripts/dev-postgres.sh" psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$OWNER_ROLE') THEN
    CREATE ROLE $OWNER_ROLE LOGIN PASSWORD '$OWNER_PASSWORD' CREATEROLE BYPASSRLS;
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE $DATABASE OWNER $OWNER_ROLE'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$DATABASE')\gexec
SQL
    load_env
    cd "$ROOT/backend"
    "$(python_bin)" -m app.cli migrate
    ;;
  api)
    load_env
    cd "$ROOT/backend"
    exec "$(python_bin)" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload "$@"
    ;;
  web)
    load_env
    cd "$ROOT/frontend"
    exec npm run dev -- "$@"
    ;;
  web-start)
    # Production build served locally (what Vercel runs).
    load_env
    cd "$ROOT/frontend"
    npm run build
    exec npm run start -- "$@"
    ;;
  stripe)
    load_env
    if [ -z "${STRIPE_SECRET_KEY:-}" ]; then
      echo "STRIPE_SECRET_KEY is not set in .env" >&2
      exit 1
    fi
    case "$STRIPE_SECRET_KEY" in
      sk_test_* | rk_test_*) ;;
      *)
        echo "Refusing to forward webhooks with a live Stripe key." >&2
        exit 1
        ;;
    esac
    # The signing secret of the CLI listener is stable for this account: it is
    # stored once so that the API can verify forwarded events.
    if ! grep -q '^STRIPE_WEBHOOK_SECRET=' "$DEV_ENV"; then
      secret="$(stripe listen --api-key "$STRIPE_SECRET_KEY" --print-secret)"
      (umask 077 && echo "STRIPE_WEBHOOK_SECRET=$secret" >>"$DEV_ENV")
      echo "Stored the local webhook signing secret; restart 'scripts/dev.sh api'." >&2
    fi
    exec stripe listen --api-key "$STRIPE_SECRET_KEY" \
      --forward-to "http://127.0.0.1:8000/api/v1/billing/webhooks/stripe" "$@"
    ;;
  cli)
    load_env
    cd "$ROOT/backend"
    exec "$(python_bin)" -m app.cli "$@"
    ;;
  *)
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
