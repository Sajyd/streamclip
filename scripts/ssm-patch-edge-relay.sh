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
while true; do
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
  # Quota can return when the user subscribes without restarting OBS.
  if [ "$STATUS" = "unavailable" ] && echo "$RESP" | grep -qiE 'quota|abonnement|subscription|refus'; then
    echo "relay waiting quota path=$PATH_NAME" >&2
    sleep 15
    continue
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
# If the push to the spot stalls or drops while OBS is still publishing
# here, kill ffmpeg and open a new push. Do not wait for OBS to reconnect.
PROGRESS="/var/run/streamclip/relay_${SAFE}.progress"
rm -f "$PROGRESS"
ffmpeg -hide_banner -loglevel warning -nostats \
  -rtsp_transport tcp -fflags +genpts+igndts -use_wallclock_as_timestamps 1 \
  -i "rtsp://127.0.0.1:8554/$PATH_NAME" \
  -c copy -f flv -flvflags no_duration_filesize \
  -rw_timeout 20000000 \
  -progress "$PROGRESS" \
  "$TARGET" >>/var/log/streamclip-relay.log 2>&1 &
FF_PID=$!
LAST=0
STALL=0
while kill -0 "$FF_PID" 2>/dev/null; do
  sleep 2
  CUR=$(sed -n 's/^total_size=//p' "$PROGRESS" 2>/dev/null | tail -1)
  case "$CUR" in
    ''|*[!0-9]*) CUR=0 ;;
  esac
  if [ "$CUR" -gt "$LAST" ]; then
    LAST=$CUR
    STALL=0
  else
    STALL=$((STALL + 2))
  fi
  MAX_STALL=20
  [ "$LAST" -eq 0 ] && MAX_STALL=30
  if [ "$STALL" -ge "$MAX_STALL" ]; then
    echo "relay reconnect path=$PATH_NAME bytes=$LAST stall=$STALL" >&2
    kill -TERM "$FF_PID" 2>/dev/null || true
    sleep 1
    kill -KILL "$FF_PID" 2>/dev/null || true
    break
  fi
done
wait "$FF_PID" 2>/dev/null || echo "relay push ended path=$PATH_NAME" >&2
sleep 2
done
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
