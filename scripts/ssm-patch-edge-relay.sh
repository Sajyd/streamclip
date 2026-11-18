#!/bin/bash
# Hot-patch shared edge: keep polling relay-target until per-org spot is ready
# (no 3-minute give-up during EC2 userdata / MediaMTX boot).
# Usage: INSTANCE_ID=i-xxx REGION=eu-north-1 ./scripts/ssm-patch-edge-relay.sh
set -euo pipefail
INSTANCE_ID="${INSTANCE_ID:?set INSTANCE_ID}"
REGION="${REGION:-eu-north-1}"

PARAMS=$(mktemp)
trap 'rm -f "$PARAMS"' EXIT
python3 - <<'PY' > "$PARAMS"
import json
script = r"""
set -euo pipefail
# HOOK / RELAY_URL / EVENT_URL are exported by streamclip-edge-on-ready for the relay child.

cat > /usr/local/bin/streamclip-edge-relay <<'RELAY'
#!/bin/bash
# Poll until the per-org spot is ready. runOnNotReady kills us on OBS disconnect.
PATH_NAME="$1"
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
mkdir -p /var/run/streamclip
PIDFILE="/var/run/streamclip/relay_${SAFE}.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT
TARGET=""
ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT + 1))
  RESP=$(curl -fsS -G -H "X-Streamclip-Ingest-Secret: $HOOK" \
    --data-urlencode "path=$PATH_NAME" "$RELAY_URL" || true)
  TARGET=$(printf '%s' "$RESP" | sed -n 's/.*"rtmp_push_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  STATUS=$(printf '%s' "$RESP" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  if [ "$STATUS" = "ready" ] && [ -n "$TARGET" ]; then
    break
  fi
  if [ "$STATUS" = "unavailable" ] && echo "$RESP" | grep -qiE 'quota|abonnement|subscription|refus'; then
    echo "relay forbidden for $PATH_NAME: $RESP" >&2
    exit 1
  fi
  if [ $((ATTEMPT % 20)) -eq 0 ]; then
    echo "relay waiting spot path=$PATH_NAME attempt=$ATTEMPT status=$STATUS" >&2
  fi
  sleep 3
done
curl -fsS -X POST -H Content-Type:application/json \
  -H "X-Streamclip-Ingest-Secret: $HOOK" \
  -d "{\"event\":\"publisher_ready\",\"path\":\"$PATH_NAME\",\"protocol\":\"rtmp\"}" \
  "$EVENT_URL" || true
exec ffmpeg -hide_banner -loglevel warning \
  -rtsp_transport tcp -fflags +genpts+igndts -use_wallclock_as_timestamps 1 \
  -i "rtsp://127.0.0.1:8554/$PATH_NAME" \
  -c copy -f flv -flvflags no_duration_filesize \
  "$TARGET"
RELAY
chmod +x /usr/local/bin/streamclip-edge-relay
echo edge_relay_patched
head -n 5 /usr/local/bin/streamclip-edge-relay
"""
print(json.dumps({"commands": [script]}))
PY

aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "file://$PARAMS" \
  --output json \
  --query 'Command.CommandId'
