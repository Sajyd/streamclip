#!/bin/bash
# Hot-patch a running dedicated ingest EC2:
# - MediaMTX native 5-min HD record (full source fps/bitrate)
# - on-record-complete → remux copy → S3 → API
# - kill legacy ffmpeg RTSP segment loops (sparse-frame bug)
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
  HOOK=$(sed -n "s/.*HOOK='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  EVENT_URL=$(sed -n "s/.*EVENT_URL='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  S3_BUCKET=$(sed -n "s/.*S3_BUCKET='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  AWS_REGION=$(sed -n "s/.*AWS_REGION='\([^']*\)'.*/\1/p" /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 || true)
  if [ -z "${HOOK:-}" ]; then HOOK=$(sed -n 's/.*export HOOK=\(.*\)/\1/p' /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 | tr -d "'" || true); fi
  if [ -z "${EVENT_URL:-}" ]; then EVENT_URL=$(sed -n 's/.*export EVENT_URL=\(.*\)/\1/p' /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 | tr -d "'" || true); fi
  if [ -z "${S3_BUCKET:-}" ]; then S3_BUCKET=$(sed -n 's/.*export S3_BUCKET=\(.*\)/\1/p' /usr/local/bin/streamclip-on-ready 2>/dev/null | head -1 | tr -d "'" || true); fi
  # Prefer agent.env-style values already on disk if present in process env files.
  if [ -z "${HOOK:-}" ] && [ -f /etc/streamclip/agent.env ]; then . /etc/streamclip/agent.env; fi
  AWS_REGION="${AWS_REGION:-eu-north-1}"
  printf 'HOOK=%s\nEVENT_URL=%s\nS3_BUCKET=%s\nAWS_REGION=%s\n' \
    "${HOOK:-}" "${EVENT_URL:-}" "${S3_BUCKET:-}" "$AWS_REGION" > /etc/streamclip/agent.env
fi
# If agent.env exists but was empty for S3, try to recover from prior scripts.
. /etc/streamclip/agent.env
if [ -z "${S3_BUCKET:-}" ] || [ -z "${HOOK:-}" ] || [ -z "${EVENT_URL:-}" ]; then
  echo "WARN: agent.env missing fields; check /etc/streamclip/agent.env" >&2
fi

echo '__AGENT_B64__' | base64 -d > /usr/local/bin/streamclip-analysis-agent.py
chmod +x /usr/local/bin/streamclip-analysis-agent.py

# Kill legacy sparse-frame RTSP segment loops.
pkill -f streamclip-segment-loop || true
for pf in /var/run/streamclip/seg_*.pid; do
  [ -f "$pf" ] || continue
  kill "$(cat "$pf")" 2>/dev/null || true
  rm -f "$pf"
done

cat > /usr/local/bin/streamclip-on-record-complete <<'ONSEG'
#!/bin/bash
set -uo pipefail
PATH_NAME="${1:-${MTX_PATH:-}}"
SEG_PATH="${2:-${MTX_SEGMENT_PATH:-}}"
LOG="/var/log/streamclip-segment.log"
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
if [ -z "$PATH_NAME" ] || [ -z "$SEG_PATH" ] || [ ! -s "$SEG_PATH" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) record_skip path=$PATH_NAME seg=$SEG_PATH" >>"$LOG" || true
  exit 0
fi
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
SEQFILE="/var/run/streamclip/seg_${SAFE}.seq"
mkdir -p /var/run/streamclip /var/lib/streamclip/segments
SEQ=0
[ -f "$SEQFILE" ] && SEQ=$(cat "$SEQFILE" 2>/dev/null || echo 0)
OUT="/var/lib/streamclip/segments/${SAFE}_$(printf %04d "$SEQ").mp4"
if ! ffmpeg -y -i "$SEG_PATH" -c copy -movflags +faststart "$OUT" 2>>"$LOG"; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) remux_fail path=$PATH_NAME seq=$SEQ" >>"$LOG" || true
  rm -f "$OUT"
  OUT="$SEG_PATH"
fi
SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT" 2>/dev/null || echo 0)
KEY="tmp/lives/${SAFE}/seg_$(printf %04d "$SEQ").mp4"
if [ -n "${S3_BUCKET:-}" ] && [ "$SIZE" -gt 0 ]; then
  aws s3 cp "$OUT" "s3://${S3_BUCKET}/${KEY}" --region "${AWS_REGION:-eu-north-1}" || true
fi
if [ "$SIZE" -gt 0 ]; then
  curl -fsS --max-time 15 -X POST -H "Content-Type: application/json" \
    -H "X-Streamclip-Ingest-Secret: $HOOK" \
    -d "{\"event\":\"segment\",\"path\":\"${PATH_NAME}\",\"protocol\":\"rtmp\",\"storage_key\":\"${KEY}\",\"sequence\":${SEQ},\"size_bytes\":${SIZE},\"processed_ms\":300000}" \
    "$EVENT_URL" || true
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) record_ok path=$PATH_NAME seq=$SEQ size=$SIZE key=$KEY" >>"$LOG" || true
fi
SEQ=$((SEQ + 1))
echo "$SEQ" > "$SEQFILE" || true
rm -f "$SEG_PATH"
[ "$OUT" != "$SEG_PATH" ] && rm -f "$OUT"
ONSEG
chmod +x /usr/local/bin/streamclip-on-record-complete

cat > /usr/local/bin/streamclip-on-ready <<'ONREADY'
#!/bin/bash
PATH_NAME="$1"
mkdir -p /var/run/streamclip /var/lib/streamclip/segments
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
curl -fsS -X POST -H "Content-Type: application/json" \
  -H "X-Streamclip-Ingest-Secret: $HOOK" \
  -d "{\"event\":\"publisher_ready\",\"path\":\"$PATH_NAME\",\"protocol\":\"rtmp\"}" \
  "$EVENT_URL" || true
curl -fsS -X POST -H "Content-Type: application/json" \
  -d "{\"path\":\"$PATH_NAME\"}" \
  "http://127.0.0.1:8080/start" || true
ONREADY
chmod +x /usr/local/bin/streamclip-on-ready

cat > /usr/local/bin/streamclip-on-not-ready <<'OFFREADY'
#!/bin/bash
PATH_NAME="$1"
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
curl -fsS -X POST -H "Content-Type: application/json" \
  -d "{\"path\":\"$PATH_NAME\"}" \
  "http://127.0.0.1:8080/stop" || true
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

# Patch MediaMTX: native HD record + larger write queue. Preserve authHTTPAddress.
if [ -f /etc/mediamtx/mediamtx.yml ]; then
  AUTH_LINE=$(grep -E '^authHTTPAddress:' /etc/mediamtx/mediamtx.yml | head -1 || true)
  [ -n "${AUTH_LINE:-}" ] || AUTH_LINE='authHTTPAddress: http://127.0.0.1/'
  python3 - "$AUTH_LINE" <<'PY'
from pathlib import Path
import sys
auth = sys.argv[1]
Path("/etc/mediamtx/mediamtx.yml").write_text(
    f"""logLevel: info
writeQueueSize: 8192
readTimeout: 60s
writeTimeout: 60s
rtmp: yes
rtmpAddress: :1935
srt: yes
srtAddress: :8890
webrtc: no
hls: yes
hlsAddress: 127.0.0.1:8888
hlsAlwaysRemux: yes
hlsSegmentCount: 7
hlsSegmentDuration: 1s
rtsp: yes
rtspAddress: :8554
authMethod: http
{auth}
pathDefaults:
  record: yes
  recordPath: /var/lib/streamclip/segments/%path/%Y-%m-%d_%H-%M-%S-%f
  recordFormat: fmp4
  recordPartDuration: 1s
  recordSegmentDuration: 5m
  recordDeleteAfter: 2h
  runOnReady: /usr/local/bin/streamclip-on-ready $MTX_PATH
  runOnNotReady: /usr/local/bin/streamclip-on-not-ready $MTX_PATH
  runOnRecordSegmentComplete: /usr/local/bin/streamclip-on-record-complete $MTX_PATH $MTX_SEGMENT_PATH
paths:
  all_others:
"""
)
PY
  systemctl restart mediamtx || true
fi

systemctl daemon-reload
systemctl enable --now streamclip-agent
systemctl restart streamclip-agent
sleep 1
curl -fsS http://127.0.0.1:8080/health
ss -lntp | grep -E '1935|8080' || true
ffmpeg -version | head -1 || true
grep -E 'record:|writeQueueSize|runOnRecord' /etc/mediamtx/mediamtx.yml || true
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
