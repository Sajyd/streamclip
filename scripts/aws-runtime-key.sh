#!/usr/bin/env bash
# Issues or rotates the access key of the restricted runtime identity.
#
#   scripts/aws-runtime-key.sh issue    # create a key, store it in .localdev/aws_runtime.env
#   scripts/aws-runtime-key.sh prune    # delete every key except the stored one
#   scripts/aws-runtime-key.sh status   # list the keys of the runtime user
#
# Rotation: `issue`, update S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY in the
# deployment, redeploy, check /api/v1/readyz?deep=true, then `prune`.
#
# The secret is written to a private file and never printed. It is kept out
# of the Terraform state on purpose. Requires administrator AWS credentials
# in the environment or in .env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMAND="${1:?usage: scripts/aws-runtime-key.sh <issue|prune|status>}"
USER_NAME="${RUNTIME_USER_NAME:-streamclip-production-runtime}"
OUTPUT="${RUNTIME_KEY_FILE:-$ROOT/.localdev/aws_runtime.env}"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

list_keys() {
  aws iam list-access-keys --user-name "$USER_NAME" \
    --query 'AccessKeyMetadata[].[AccessKeyId,Status,CreateDate]' --output text
}

case "$COMMAND" in
  status)
    list_keys
    ;;
  issue)
    count="$(aws iam list-access-keys --user-name "$USER_NAME" --query 'length(AccessKeyMetadata)' --output text)"
    if [ "$count" -ge 2 ]; then
      echo "The user already has two access keys (the IAM maximum): run 'prune' first." >&2
      exit 1
    fi
    mkdir -p "$(dirname "$OUTPUT")"
    umask 077
    # Written straight to the private file: the secret never reaches the terminal.
    aws iam create-access-key --user-name "$USER_NAME" \
      --query '[AccessKey.AccessKeyId,AccessKey.SecretAccessKey]' --output text |
      awk '{ printf "S3_ACCESS_KEY_ID=%s\nS3_SECRET_ACCESS_KEY=%s\n", $1, $2 }' >"$OUTPUT"
    chmod 600 "$OUTPUT"
    echo "New access key stored in ${OUTPUT#"$ROOT"/} ($(sed -n 's/^S3_ACCESS_KEY_ID=//p' "$OUTPUT"))."
    ;;
  prune)
    [ -f "$OUTPUT" ] || { echo "No stored key at $OUTPUT" >&2; exit 1; }
    current="$(sed -n 's/^S3_ACCESS_KEY_ID=//p' "$OUTPUT")"
    [ -n "$current" ] || { echo "Stored key file is malformed" >&2; exit 1; }
    for key_id in $(aws iam list-access-keys --user-name "$USER_NAME" \
      --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
      if [ "$key_id" != "$current" ]; then
        aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$key_id"
        echo "Deleted $key_id"
      fi
    done
    ;;
  *)
    echo "Unknown command: $COMMAND" >&2
    exit 2
    ;;
esac
