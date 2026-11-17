#!/bin/bash
# Hot-patch a running dedicated ingest EC2 with :8080 analysis agent + segment loop.
# Usage: INSTANCE_ID=i-xxx REGION=eu-north-1 ./scripts/ssm-patch-dedicated-agent.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTANCE_ID="${INSTANCE_ID:?set INSTANCE_ID}"
REGION="${REGION:-eu-north-1}"
AGENT_B64="$(base64 < "$ROOT/backend/app/services/ingest_agent.py" | tr -d '\n')"

PARAMS=$(mktemp)
trap 'rm -f "$PARAMS"' EXIT
# Quoted heredoc so remote shell vars are not expanded locally.
python3 - "$AGENT_B64" <<'PY' > "$PARAMS"
import json, sys
agent_b64 = sys.argv[1]
script = r"""
set -euo pipefail
mkdir -p /etc/streamclip /var/run/streamclip /var/lib/streamclip/segments /usr/local/bin
if [ ! -f /etc/streamclip/agent.env ]; then
  # Pull env from export lines in existing on-ready (HOOK='...' form).
  HOOK=$(sed -n "s/.*HOOK='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  EVENT_URL=$(sed -n "s/.*EVENT_URL='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  S3_BUCKET=$(sed -n "s/.*S3_BUCKET='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  AWS_REGION=$(sed -n "s/.*AWS_REGION='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  if [ -z "${HOOK:-}" ]; then HOOK=$(sed -n 's/.*export HOOK=\(.*\)/\1/p' /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 | tr -d "'" || true); fi
  if [ -z "${EVENT_URL:-}" ]; then EVENT_URL=$(sed -n 's/.*export EVENT_URL=\(.*\)/\1/p' /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 | tr -d "'" || true); fi
  if [ -z "${S3_BUCKET:-}" ]; then S3_BUCKET=$(sed -n 's/.*export S3_BUCKET=\(.*\)/\1/p' /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 | tr -d "'" || true); fi
  AWS_REGION="${AWS_REGION:-eu-north-1}"
  printf 'HOOK=%s\nEVENT_URL=%s\nS3_BUCKET=%s\nAWS_REGION=%s\n' \
    "${HOOK:-}" "${EVENT_URL:-}" "${S3_BUCKET:-}" "$AWS_REGION" > /etc/streamclip/agent.env
fi
echo '__AGENT_B64__' | base64 -d > /usr/local/bin/streamclip-analysis-agent.py
chmod +x /usr/local/bin/streamclip-analysis-agent.py

cat > /usr/local/bin/streamclip-segment-loop <<'AGENT'
#!/bin/bash
# Never `set -e`: a failed segment must not kill the loop or the live.
set -uo pipefail
PATH_NAME="$1"
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
PIDFILE="/var/run/streamclip/seg_${SAFE}.pid"
SEQFILE="/var/run/streamclip/seg_${SAFE}.seq"
LOG="/var/log/streamclip-segment.log"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi
echo $$ > "$PIDFILE"
SEQ=0
[ -f "$SEQFILE" ] && SEQ=$(cat "$SEQFILE" 2>/dev/null || echo 0)
trap 'rm -f "$PIDFILE"' EXIT
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
FAILS=0
while true; do
  OUT="/var/lib/streamclip/segments/${SAFE}_$(printf %04d "$SEQ").mp4"
  rm -f "$OUT"
  if ! ffmpeg -y -rtsp_transport tcp -fflags +genpts+igndts \
      -use_wallclock_as_timestamps 1 \
      -i "rtsp://127.0.0.1:8554/${PATH_NAME}" \
      -t 300 -c copy -f mp4 -movflags +faststart "$OUT"; then
    FAILS=$((FAILS + 1))
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) record_fail path=$PATH_NAME seq=$SEQ fails=$FAILS" >>"$LOG" || true
    if [ "$FAILS" -ge 3 ]; then
      SEQ=$((SEQ + 1))
      echo "$SEQ" > "$SEQFILE" || true
      FAILS=0
    fi
    sleep 2
    continue
  fi
  if [ ! -s "$OUT" ]; then
    FAILS=$((FAILS + 1))
    if [ "$FAILS" -ge 3 ]; then
      SEQ=$((SEQ + 1))
      echo "$SEQ" > "$SEQFILE" || true
      FAILS=0
    fi
    sleep 1
    continue
  fi
  FAILS=0
  KEY="tmp/lives/${SAFE}/seg_$(printf %04d "$SEQ").mp4"
  SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT" 2>/dev/null || echo 0)
  if [ -n "${S3_BUCKET:-}" ] && [ "$SIZE" -gt 0 ]; then
    aws s3 cp "$OUT" "s3://${S3_BUCKET}/${KEY}" --region "$AWS_REGION" || true
  fi
  if [ "$SIZE" -gt 0 ]; then
    curl -fsS --max-time 15 -X POST -H "Content-Type: application/json" \
      -H "X-Streamclip-Ingest-Secret: $HOOK" \
      -d "{\"event\":\"segment\",\"path\":\"${PATH_NAME}\",\"protocol\":\"rtmp\",\"storage_key\":\"${KEY}\",\"sequence\":${SEQ},\"size_bytes\":${SIZE},\"processed_ms\":300000}" \
      "$EVENT_URL" || true
  fi
  SEQ=$((SEQ + 1))
  echo "$SEQ" > "$SEQFILE" || true
  rm -f "$OUT"
done
AGENT
chmod +x /usr/local/bin/streamclip-segment-loop

cat > /usr/local/bin/streamclip-on-ready <<'ONREADY'
#!/bin/bash
PATH_NAME="$1"
mkdir -p /var/run/streamclip /var/lib/streamclip/segments
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
curl -fsS -X POST -H "Content-Type: application/json" \
  -H "X-Streamclip-Ingest-Secret: $HOOK" \
  -d "{\"event\":\"publisher_ready\",\"path\":\"$PATH_NAME\",\"protocol\":\"rtmp\"}" \
  "$EVENT_URL" || true
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
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
curl -fsS -X POST -H "Content-Type: application/json" \
  -d "{\"path\":\"$PATH_NAME\"}" \
  "http://127.0.0.1:8080/stop" || true
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
PIDFILE="/var/run/streamclip/seg_$SAFE.pid"
if [ -f "$PIDFILE" ]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
fi
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
# Keep RTMP publishers across brief encoder stalls (was 15s → false disconnect).
if [ -f /etc/mediamtx/mediamtx.yml ]; then
  sed -i 's/^readTimeout:.*/readTimeout: 60s/' /etc/mediamtx/mediamtx.yml || true
  sed -i 's/^writeTimeout:.*/writeTimeout: 60s/' /etc/mediamtx/mediamtx.yml || true
  systemctl restart mediamtx || true
fi
# Ensure static ffmpeg is on PATH (AL2023 has no distro package).
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
systemctl daemon-reload
systemctl enable --now streamclip-agent
systemctl restart streamclip-agent
sleep 1
curl -fsS http://127.0.0.1:8080/health
ss -lntp | grep -E '1935|8080' || true
ffmpeg -version | head -1 || true
"""
print(json.dumps({"commands": [script.replace("__AGENT_B64__", agent_b64)]}))
PY

aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "file://$PARAMS" \
  --output json \
  --query 'Command.CommandId'
