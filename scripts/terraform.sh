#!/usr/bin/env bash
# Runs Terraform for one target with the configuration taken from the local,
# git-ignored .env file, so that no account-specific value lives in the repo.
#
#   scripts/terraform.sh bootstrap apply       # once per AWS account
#   scripts/terraform.sh production plan
#   scripts/terraform.sh production apply
#
# Requires administrator AWS credentials (AWS_ACCESS_KEY_ID /
# AWS_SECRET_ACCESS_KEY) in the environment or in .env. Those credentials are
# only used here, on the operator's machine: the application runs with the
# restricted identity created by this configuration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:?usage: scripts/terraform.sh <bootstrap|production> <terraform arguments...>}"
shift
[ "$#" -ge 1 ] || { echo "Missing terraform command (init, plan, apply, output...)" >&2; exit 2; }

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

TERRAFORM="${TERRAFORM_BIN:-}"
if [ -z "$TERRAFORM" ]; then
  if [ -x "$ROOT/.tools/terraform/terraform" ]; then
    TERRAFORM="$ROOT/.tools/terraform/terraform"
  else
    TERRAFORM="$(command -v terraform)" || { echo "terraform is not installed" >&2; exit 127; }
  fi
fi

REGION="${S3_REGION:-${AWS_REGION:-}}"
[ -n "$REGION" ] || { echo "S3_REGION (or AWS_REGION) is not set" >&2; exit 2; }
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
STATE_BUCKET="${TERRAFORM_STATE_BUCKET:-streamclip-tfstate-${ACCOUNT_ID}}"

export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
export TF_IN_AUTOMATION=1
export TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-$ROOT/.tools/terraform/plugin-cache}"
mkdir -p "$TF_PLUGIN_CACHE_DIR"
export TF_VAR_aws_region="$REGION"

case "$TARGET" in
  bootstrap)
    DIR="$ROOT/infrastructure/terraform/bootstrap"
    export TF_VAR_state_bucket_name="$STATE_BUCKET"
    INIT_ARGS=()
    ;;
  production)
    DIR="$ROOT/infrastructure/terraform/environments/$TARGET"
    : "${S3_BUCKET:?S3_BUCKET is not set}"
    export TF_VAR_bucket_name="$S3_BUCKET"
    # Optional MediaMTX ingest node (t4g.small). Defaults on when secrets are present.
    if [ -n "${ENABLE_INGEST_NODE:-}" ]; then
      export TF_VAR_enable_ingest_node="$ENABLE_INGEST_NODE"
    fi
    if [ -n "${INGEST_API_AUTH_URL:-}" ]; then
      export TF_VAR_ingest_api_auth_url="$INGEST_API_AUTH_URL"
    fi
    if [ -n "${INGEST_API_EVENT_URL:-}" ]; then
      export TF_VAR_ingest_api_event_url="$INGEST_API_EVENT_URL"
    fi
    if [ -n "${INGEST_HOOK_SECRET:-}" ]; then
      export TF_VAR_ingest_hook_secret="$INGEST_HOOK_SECRET"
    fi
    INIT_ARGS=(-backend-config="bucket=$STATE_BUCKET" -backend-config="region=$REGION")
    ;;
  *)
    echo "Unknown target: $TARGET" >&2
    exit 2
    ;;
esac

if [ "$1" = "init" ]; then
  shift
  exec "$TERRAFORM" -chdir="$DIR" init -input=false ${INIT_ARGS[@]+"${INIT_ARGS[@]}"} "$@"
fi

# ${array[@]+...}: an empty array is an error under `set -u` with the bash 3.2 shipped by macOS.
"$TERRAFORM" -chdir="$DIR" init -input=false ${INIT_ARGS[@]+"${INIT_ARGS[@]}"} >/dev/null
exec "$TERRAFORM" -chdir="$DIR" "$@"
