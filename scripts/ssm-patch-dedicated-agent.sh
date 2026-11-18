#!/bin/bash
# Hot-patch dedicated per-org ingest EC2:
# - 5-min RTMP segment loop → S3 → :8080/analyze (on-box frames/ASR/Luna)
# - Refresh :8080 agent + onbox analyzer
# - Disable MediaMTX native record
# Usage: INSTANCE_ID=i-xxx REGION=eu-north-1 ./scripts/ssm-patch-dedicated-agent.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTANCE_ID="${INSTANCE_ID:?set INSTANCE_ID}"
REGION="${REGION:-eu-north-1}"
AGENT_B64="$(base64 < "$ROOT/backend/app/services/ingest_agent.py" | tr -d '\n')"
ONBOX_B64="$(base64 < "$ROOT/backend/app/services/ingest_onbox_analyze.py" | tr -d '\n')"

PARAMS=$(mktemp)
trap 'rm -f "$PARAMS"' EXIT
python3 - "$AGENT_B64" "$ONBOX_B64" <<'PY' > "$PARAMS"
import json, sys
agent_b64, onbox_b64 = sys.argv[1], sys.argv[2]
script = r"""
set -euo pipefail
mkdir -p /etc/streamclip /var/run/streamclip /var/lib/streamclip/segments /usr/local/bin
if [ ! -f /etc/streamclip/agent.env ]; then
  HOOK=$(sed -n "s/.*HOOK='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  EVENT_URL=$(sed -n "s/.*EVENT_URL='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  S3_BUCKET=$(sed -n "s/.*S3_BUCKET='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  AWS_REGION=$(sed -n "s/.*AWS_REGION='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  AWS_REGION="${AWS_REGION:-eu-north-1}"
  printf 'HOOK=%s\nEVENT_URL=%s\nS3_BUCKET=%s\nAWS_REGION=%s\n' \
    "${HOOK:-}" "${EVENT_URL:-}" "${S3_BUCKET:-}" "$AWS_REGION" > /etc/streamclip/agent.env
fi
. /etc/streamclip/agent.env || true

python3 -m pip install --upgrade 'boto3>=1.34' >/tmp/streamclip-pip.log 2>&1 || true

echo '__AGENT_B64__' | base64 -d > /usr/local/bin/streamclip-analysis-agent.py
chmod +x /usr/local/bin/streamclip-analysis-agent.py
echo '__ONBOX_B64__' | base64 -d > /usr/local/bin/streamclip_onbox_analyze.py
chmod +x /usr/local/bin/streamclip_onbox_analyze.py

# Stop old recorders (MediaMTX record hooks + any prior loops).
pkill -f streamclip-segment-loop || true
pkill -f streamclip-on-record-complete || true
for pf in /var/run/streamclip/seg_*.pid; do
  [ -f "$pf" ] || continue
  kill "$(cat "$pf")" 2>/dev/null || true
  rm -f "$pf"
done
rm -f /usr/local/bin/streamclip-on-record-complete

cat > /usr/local/bin/streamclip-segment-loop <<'AGENT'
#!/bin/bash
set -uo pipefail
PATH_NAME="$1"
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
PIDFILE="/var/run/streamclip/seg_${SAFE}.pid"
SEQFILE="/var/run/streamclip/seg_${SAFE}.seq"
LOCKFILE="/var/run/streamclip/seg_${SAFE}.lock"
SESSIONFILE="/var/run/streamclip/seg_${SAFE}.session"
LOG="/var/log/streamclip-segment.log"
WINDOW_S=300
MIN_BYTES=1000000
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    OLD_CMD=$(tr '\0' ' ' < "/proc/$OLD_PID/cmdline" 2>/dev/null || true)
    if echo "$OLD_CMD" | grep -q 'streamclip-segment-loop' \
      && echo "$OLD_CMD" | grep -Fq -- "$PATH_NAME"; then
      exit 0
    fi
    kill "$OLD_PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi
echo $$ > "$PIDFILE"
printf '%s\n' "$PATH_NAME" > "/var/run/streamclip/seg_${SAFE}.path" || true
SEQ=0
[ -f "$SEQFILE" ] && SEQ=$(cat "$SEQFILE" 2>/dev/null || echo 0)
trap 'rm -f "$PIDFILE"' EXIT
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
while true; do
  LIVE_ID=$(cat "$SESSIONFILE" 2>/dev/null | tr -d '[:space:]' || true)
  [ -n "$LIVE_ID" ] || LIVE_ID="$SAFE"
  PART="/var/lib/streamclip/segments/${SAFE}_$(printf %04d "$SEQ").partial.mp4"
  OUT="/var/lib/streamclip/segments/${SAFE}_$(printf %04d "$SEQ").mp4"
  ANALYZE="/var/lib/streamclip/segments/analyze_${SAFE}_$(printf %04d "$SEQ").mp4"
  rm -f "$PART" "$OUT" "$ANALYZE"
  # No +igndts: that flag stretches one video frame across a congestion hole.
  # OBS can stay connected while this reader drops or hangs. If the partial
  # stops growing, kill ffmpeg and open a new read. Never exit the loop.
  ffmpeg -hide_banner -loglevel warning -y \
      -threads 1 \
      -thread_queue_size 1024 \
      -analyzeduration 2000000 -probesize 5000000 \
      -rw_timeout 20000000 \
      -fflags +genpts+discardcorrupt \
      -err_detect ignore_err \
      -i "rtmp://127.0.0.1:1935/${PATH_NAME}" \
      -t "$WINDOW_S" \
      -map "0:v:0" -map "0:a:0?" \
      -c copy \
      -avoid_negative_ts make_zero \
      -max_muxing_queue_size 1024 \
      -f mp4 -movflags frag_keyframe+empty_moov+default_base_moof \
      "$PART" >>"$LOG" 2>&1 &
  FF_PID=$!
  LAST_SIZE=0
  STALL=0
  STARTED=$SECONDS
  LIMIT_S=$((WINDOW_S + 45))
  while kill -0 "$FF_PID" 2>/dev/null; do
    sleep 2
    SIZE_NOW=0
    if [ -f "$PART" ]; then
      SIZE_NOW=$(stat -c%s "$PART" 2>/dev/null || echo 0)
    fi
    if [ "$SIZE_NOW" -gt "$LAST_SIZE" ]; then
      LAST_SIZE=$SIZE_NOW
      STALL=0
    else
      STALL=$((STALL + 2))
    fi
    ELAPSED=$((SECONDS - STARTED))
    if [ "$LAST_SIZE" -eq 0 ]; then
      MAX_STALL=20
    else
      MAX_STALL=15
    fi
    if [ "$STALL" -ge "$MAX_STALL" ] || [ "$ELAPSED" -ge "$LIMIT_S" ]; then
      if [ "$STALL" -ge "$MAX_STALL" ]; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) record_reconnect path=$PATH_NAME seq=$SEQ size=$LAST_SIZE stall=$STALL" >>"$LOG" || true
        curl -fsS --max-time 8 -X POST -H "Content-Type: application/json" \
          -H "X-Streamclip-Ingest-Secret: $HOOK" \
          -d "{\"event\":\"tick\",\"path\":\"${PATH_NAME}\",\"protocol\":\"rtmp\",\"processed_ms\":1}" \
          "$EVENT_URL" >/dev/null 2>&1 || true
      fi
      kill -TERM "$FF_PID" 2>/dev/null || true
      sleep 1
      kill -KILL "$FF_PID" 2>/dev/null || true
      break
    fi
  done
  wait "$FF_PID" 2>/dev/null || true
  if [ -f "$PART" ]; then
    if timeout 60 ffmpeg -y -loglevel error -fflags +genpts -i "$PART" \
        -map "0:v:0" -map "0:a:0?" -c copy \
        -avoid_negative_ts make_zero -movflags +faststart "$OUT" >>"$LOG" 2>&1; then
      rm -f "$PART"
    else
      mv -f "$PART" "$OUT" 2>/dev/null || OUT=""
    fi
  else
    OUT=""
  fi
  SIZE=0
  if [ -n "$OUT" ] && [ -f "$OUT" ]; then
    SIZE=$(stat -c%s "$OUT" 2>/dev/null || echo 0)
  fi
  if [ "$SIZE" -ge "$MIN_BYTES" ]; then
    KEY="tmp/lives/${LIVE_ID}/seg_$(printf %04d "$SEQ").mp4"
    exec 200>"$LOCKFILE"
    flock -x 200
    UPLOADED=1
    if [ -n "${S3_BUCKET:-}" ]; then
      UPLOADED=0
      for _n in 1 2 3 4 5; do
        if aws s3 cp "$OUT" "s3://${S3_BUCKET}/${KEY}" --region "${AWS_REGION:-eu-north-1}" --only-show-errors; then
          UPLOADED=1
          break
        fi
        sleep 2
      done
    fi
    if [ "$UPLOADED" != 1 ]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) upload_fail path=$PATH_NAME seq=$SEQ key=$KEY" >>"$LOG" || true
    fi
    if [ "$UPLOADED" = 1 ]; then
    curl -fsS --max-time 20 -X POST -H "Content-Type: application/json" \
      -H "X-Streamclip-Ingest-Secret: $HOOK" \
      -d "{\"event\":\"segment\",\"path\":\"${PATH_NAME}\",\"protocol\":\"rtmp\",\"storage_key\":\"${KEY}\",\"sequence\":${SEQ},\"size_bytes\":${SIZE},\"processed_ms\":300000}" \
      "$EVENT_URL" || true
    fi
    mv -f "$OUT" "$ANALYZE"
    QUEUED=0
    for _n in 1 2 3 4 5; do
      if curl -fsS --max-time 10 -X POST -H "Content-Type: application/json" \
        -d "{\"video_path\":\"${ANALYZE}\",\"stream_session_id\":\"${LIVE_ID}\",\"sequence\":${SEQ},\"storage_key\":\"${KEY}\",\"size_bytes\":${SIZE}}" \
        "http://127.0.0.1:8080/analyze"; then
        QUEUED=1
        break
      fi
      sleep 2
    done
    if [ "$QUEUED" != 1 ]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) analyze_queue_fail path=$PATH_NAME seq=$SEQ" >>"$LOG" || true
    fi
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) record_ok path=$PATH_NAME seq=$SEQ size=$SIZE key=$KEY" >>"$LOG" || true
    SEQ=$((SEQ + 1))
    echo "$SEQ" > "$SEQFILE" || true
    flock -u 200
    exec 200>&-
    rm -f "$PART"
  else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) record_reject_tiny path=$PATH_NAME seq=$SEQ size=$SIZE" >>"$LOG" || true
    rm -f "$OUT" "$PART" "$ANALYZE"
    sleep 2
    continue
  fi
done
AGENT
chmod +x /usr/local/bin/streamclip-segment-loop

cat > /usr/local/bin/streamclip-on-ready <<'ONREADY'
#!/bin/bash
PATH_NAME="$1"
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
mkdir -p /var/run/streamclip /var/lib/streamclip/segments
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
RESP=$(curl -fsS -X POST -H "Content-Type: application/json" \
  -H "X-Streamclip-Ingest-Secret: $HOOK" \
  -d "{\"event\":\"publisher_ready\",\"path\":\"$PATH_NAME\",\"protocol\":\"rtmp\"}" \
  "$EVENT_URL" || true)
SESSION_ID=$(printf '%s' "$RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("stream_session_id") or "")' 2>/dev/null || true)
printf '%s\n' "$PATH_NAME" > "/var/run/streamclip/seg_${SAFE}.path" || true
if [ -n "$SESSION_ID" ]; then
  PREV=$(cat "/var/run/streamclip/seg_${SAFE}.session" 2>/dev/null | tr -d '[:space:]' || true)
  echo "$SESSION_ID" > "/var/run/streamclip/seg_${SAFE}.session"
  if [ "$PREV" != "$SESSION_ID" ]; then
    echo 0 > "/var/run/streamclip/seg_${SAFE}.seq"
  fi
fi
if ! curl -fsS -X POST -H "Content-Type: application/json" \
    -d "{\"path\":\"$PATH_NAME\"}" \
    "http://127.0.0.1:8080/start"; then
  nohup /usr/local/bin/streamclip-segment-loop "$PATH_NAME" >>/var/log/streamclip-segment.log 2>&1 &
fi
ONREADY
chmod +x /usr/local/bin/streamclip-on-ready

cat > /usr/local/bin/streamclip-on-not-ready <<'OFFREADY'
#!/bin/bash
PATH_NAME="$1"
# Do not stop the segment loop. A publisher flap used to kill the recorder
# while OBS stayed connected, and nothing opened a new read.
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
curl -fsS -X POST -H "Content-Type: application/json" \
  -H "X-Streamclip-Ingest-Secret: $HOOK" \
  -d "{\"event\":\"publisher_disconnect\",\"path\":\"$PATH_NAME\",\"protocol\":\"rtmp\"}" \
  "$EVENT_URL" || true
OFFREADY
chmod +x /usr/local/bin/streamclip-on-not-ready

cat > /etc/systemd/system/streamclip-agent.service <<'UNIT'
[Unit]
Description=STREAMCLIP dedicated analysis agent (:8080)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
EnvironmentFile=-/etc/streamclip/agent.env
ExecStart=/usr/bin/python3 /usr/local/bin/streamclip-analysis-agent.py
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT

if ! command -v ffmpeg >/dev/null 2>&1; then
  FFDIR=$(mktemp -d)
  ARCH=$(uname -m)
  case "$ARCH" in
    aarch64|arm64) FFARCH=arm64 ;;
    *) FFARCH=amd64 ;;
  esac
  curl -fsSL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${FFARCH}-static.tar.xz" -o "$FFDIR/ffmpeg.tar.xz"
  tar -xJf "$FFDIR/ffmpeg.tar.xz" -C "$FFDIR"
  install -m 755 "$FFDIR"/ffmpeg-*-static/ffmpeg /usr/local/bin/ffmpeg
  install -m 755 "$FFDIR"/ffmpeg-*-static/ffprobe /usr/local/bin/ffprobe || true
  rm -rf "$FFDIR"
fi

if [ -f /etc/mediamtx/mediamtx.yml ]; then
  AUTH_LINE=$(grep -E '^authHTTPAddress:' /etc/mediamtx/mediamtx.yml | head -1 || true)
  [ -n "${AUTH_LINE:-}" ] || AUTH_LINE='authHTTPAddress: http://127.0.0.1/'
  python3 -c 'import pathlib,sys; auth=sys.argv[1]; pathlib.Path("/etc/mediamtx/mediamtx.yml").write_text("logLevel: info\nwriteQueueSize: 8192\nreadTimeout: 60s\nwriteTimeout: 60s\nrtmp: yes\nrtmpAddress: :1935\nsrt: yes\nsrtAddress: :8890\nwebrtc: no\nhls: yes\nhlsAddress: 127.0.0.1:8888\nhlsAlwaysRemux: yes\nhlsSegmentCount: 12\nhlsSegmentDuration: 2s\nrtsp: yes\nrtspAddress: :8554\nauthMethod: http\n"+auth+"\npathDefaults:\n  record: no\n  runOnReady: /usr/local/bin/streamclip-on-ready $MTX_PATH\n  runOnNotReady: /usr/local/bin/streamclip-on-not-ready $MTX_PATH\npaths:\n  all_others:\n")' "$AUTH_LINE"
  systemctl restart mediamtx || true
fi

systemctl daemon-reload
systemctl enable --now streamclip-agent
systemctl restart streamclip-agent
sleep 1
curl -fsS http://127.0.0.1:8080/health
ss -lntp | grep -E '1935|8080' || true
ffmpeg -version | head -1 || true
grep -E 'record:|writeQueueSize|runOnReady' /etc/mediamtx/mediamtx.yml || true
test -x /usr/local/bin/streamclip-segment-loop && echo segment_loop_ok
test -f /usr/local/bin/streamclip_onbox_analyze.py && echo onbox_ok
"""
print(json.dumps({
    "commands": [
        script.replace("__AGENT_B64__", agent_b64).replace("__ONBOX_B64__", onbox_b64)
    ]
}))
PY

aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "file://$PARAMS" \
  --output json \
  --query 'Command.CommandId'
