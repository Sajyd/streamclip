"""Launch / terminate dedicated t4g.medium spot instances for ingest.

Each organization gets its own EC2 (unique public IP). There is no shared
fallback host: if launch fails, resolve fails.
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import shlex
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LaunchResult:
    instance_id: str
    public_hostname: str


@dataclass(frozen=True, slots=True)
class InstanceView:
    """Live EC2 state. `missing` means AWS no longer has this instance id."""

    state: str
    public_hostname: str | None

    @property
    def usable(self) -> bool:
        return self.state in {"pending", "running"}


class SpotLauncher(Protocol):
    async def launch(self, *, organization_id: uuid.UUID, node_name: str) -> LaunchResult: ...

    async def terminate(self, *, instance_id: str) -> None: ...

    async def describe_instance(self, *, instance_id: str) -> InstanceView: ...


class FakeSpotLauncher:
    """Deterministic unique hosts for tests / local without AWS."""

    def __init__(self) -> None:
        self.launched: dict[str, str] = {}

    async def launch(self, *, organization_id: uuid.UUID, node_name: str) -> LaunchResult:
        import hashlib

        _ = organization_id
        # Stable for a given node name (relaunch) and different for each live slot.
        digest = hashlib.sha256(node_name.encode()).hexdigest()[:12]
        instance_id = f"i-fake-{digest}"
        host = f"{digest}.ingest.test"
        self.launched[instance_id] = host
        return LaunchResult(instance_id=instance_id, public_hostname=host)

    async def terminate(self, *, instance_id: str) -> None:
        self.launched.pop(instance_id, None)

    async def describe_instance(self, *, instance_id: str) -> InstanceView:
        host = self.launched.get(instance_id)
        if host is None:
            return InstanceView(state="missing", public_hostname=None)
        return InstanceView(state="running", public_hostname=host)


class AwsSpotLauncher:
    """RunInstances / TerminateInstances for per-org MediaMTX spots."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client(self):  # noqa: ANN202
        from app.aws.session import boto3_session

        return boto3_session(self._settings).client(
            "ec2",
            region_name=self._settings.ingest_ec2_region
            or self._settings.s3_region
            or "eu-north-1",
        )

    def _boot_env_text(self) -> str:
        """Shell env for the spot. Never logged and never placed in user-data."""
        settings = self._settings
        auth_url = (settings.ingest_api_auth_url or "").strip()
        event_url = (settings.ingest_api_event_url or "").strip()
        if not event_url and auth_url:
            event_url = auth_url.replace("/auth", "/event")
        hook = (
            settings.ingest_hook_secret.get_secret_value()
            if settings.ingest_hook_secret
            else ""
        )
        auth_with_secret = f"{auth_url}?ingest_secret={hook}" if auth_url else ""
        values = {
            "HOOK": hook,
            "EVENT_URL": event_url,
            "S3_BUCKET": (settings.s3_bucket or "").strip(),
            "AWS_REGION": (
                settings.ingest_ec2_region or settings.s3_region or "eu-north-1"
            ),
            "ASR_PROVIDER": (settings.asr_provider or "none").strip(),
            "ASR_API_KEY": (
                settings.asr_api_key.get_secret_value() if settings.asr_api_key else ""
            ),
            "ASR_BASE_URL": (settings.asr_base_url or "https://api.groq.com/openai/v1").strip(),
            "ASR_MODEL": (settings.asr_model or "whisper-large-v3-turbo").strip(),
            "BEDROCK_REGION": (settings.bedrock_region or "us-east-1").strip(),
            "BEDROCK_MODEL": (settings.bedrock_model or "us.openai.gpt-6-luna").strip(),
            "AUTH_HTTP_ADDRESS": auth_with_secret,
        }
        lines = []
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise RuntimeError(f"{key} contains a newline")
            lines.append(f"{key}={shlex.quote(value)}")
        return "\n".join(lines) + "\n"

    def _publish_boot_bundle(self) -> str:
        """Upload boot files under tmp/. Returns the S3 prefix.

        User-data does not contain hook, ASR, or AWS keys. The bucket's own
        encryption applies; customer-provided keys are rejected by the bucket.
        """
        settings = self._settings
        bucket = (settings.s3_bucket or "").strip()
        if not bucket:
            raise RuntimeError("S3 bucket is required to publish ingest boot scripts")
        agent = Path(__file__).with_name("ingest_agent.py").read_bytes()
        onbox = Path(__file__).with_name("ingest_onbox_analyze.py").read_bytes()
        prefix = f"tmp/boot/{secrets.token_urlsafe(24)}"
        region = settings.s3_region or settings.ingest_ec2_region or "eu-north-1"
        from app.aws.session import boto3_session

        client = boto3_session(settings).client("s3", region_name=region)

        def put(name: str, body: bytes, content_type: str) -> None:
            client.put_object(
                Bucket=bucket,
                Key=f"{prefix}/{name}",
                Body=body,
                ContentType=content_type,
            )

        put("agent.env", self._boot_env_text().encode(), "text/plain")
        put("agent.py", agent, "text/x-python")
        put("onbox.py", onbox, "text/x-python")
        put(
            "bootstrap.sh",
            self._bootstrap_script(region).encode(),
            "text/x-shellscript",
        )
        return prefix

    def _user_data(self, boot_prefix: str) -> str:
        """Per-org spot: MediaMTX RTMP + :8080 on-box analysis (frames/ASR/Luna).

        Vercel only receives segment acks and persisted highlight JSON — never
        runs FFmpeg / Bedrock for live segments.
        """
        settings = self._settings
        bucket = (settings.s3_bucket or "").strip()
        region = settings.ingest_ec2_region or settings.s3_region or "eu-north-1"

        def _sq(value: str) -> str:
            return value.replace("'", "'\\''")

        bucket_q = _sq(bucket)
        region_q = _sq(region)
        prefix_q = _sq(boot_prefix)

        # Native MediaMTX + :8080 analysis (5-min buffer → S3 → local Luna).
        # AL2023 has no ffmpeg package — install static arm64 build.
        script = f"""#!/bin/bash
set -eo pipefail
dnf install -y awscli python3 python3-pip || dnf install -y aws-cli python3 python3-pip || true
python3 -m pip install --upgrade pip || true
python3 -m pip install 'boto3>=1.34' || true
mkdir -p /etc/mediamtx /var/lib/streamclip/segments /var/run/streamclip /usr/local/bin /etc/streamclip
if ! command -v ffmpeg >/dev/null 2>&1; then
  FFDIR=$(mktemp -d)
  curl -fsSL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz" -o "$FFDIR/ffmpeg.tar.xz"
  tar -xJf "$FFDIR/ffmpeg.tar.xz" -C "$FFDIR"
  install -m 755 "$FFDIR"/ffmpeg-*-arm64-static/ffmpeg /usr/local/bin/ffmpeg
  install -m 755 "$FFDIR"/ffmpeg-*-arm64-static/ffprobe /usr/local/bin/ffprobe || true
  rm -rf "$FFDIR"
fi
ffmpeg -version | head -1
export AWS_DEFAULT_REGION='{region_q}'
S3_BUCKET='{bucket_q}'
BOOT_PREFIX='{prefix_q}'
umask 077
aws s3 cp "s3://$S3_BUCKET/$BOOT_PREFIX/agent.env" /etc/streamclip/agent.env --region "$AWS_DEFAULT_REGION"
aws s3 cp "s3://$S3_BUCKET/$BOOT_PREFIX/agent.py" /usr/local/bin/streamclip-analysis-agent.py --region "$AWS_DEFAULT_REGION"
aws s3 cp "s3://$S3_BUCKET/$BOOT_PREFIX/onbox.py" /usr/local/bin/streamclip_onbox_analyze.py --region "$AWS_DEFAULT_REGION"
chmod 600 /etc/streamclip/agent.env
chmod 700 /usr/local/bin/streamclip-analysis-agent.py /usr/local/bin/streamclip_onbox_analyze.py
aws s3 cp "s3://$S3_BUCKET/$BOOT_PREFIX/bootstrap.sh" /usr/local/bin/streamclip-bootstrap.sh --region "$AWS_DEFAULT_REGION"
chmod 700 /usr/local/bin/streamclip-bootstrap.sh
bash /usr/local/bin/streamclip-bootstrap.sh
"""
        if len(script.encode("utf-8")) > 16384:
            raise RuntimeError(
                f"EC2 user-data is {len(script.encode('utf-8'))} bytes (limit 16384)"
            )
        return script

    def _bootstrap_script(self, region: str) -> str:
        """Shell installed from S3. EC2 user-data itself cannot exceed 16 KiB."""
        region_q = region.replace("'", "'\\''")
        return f"""# Secrets stay in agent.env (root-only). Do not echo that file.
MTX_VER=1.12.3
curl -fsSL "https://github.com/bluenviron/mediamtx/releases/download/v${{MTX_VER}}/mediamtx_v${{MTX_VER}}_linux_arm64.tar.gz" \\
  | tar -xz -C /usr/local/bin mediamtx
chmod +x /usr/local/bin/mediamtx

# Continuous 5-min windows: record → S3 → :8080/analyze → immediately next window.
cat > /usr/local/bin/streamclip-segment-loop <<'AGENT'
#!/bin/bash
set -uo pipefail
PATH_NAME="$1"
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
PIDFILE="/var/run/streamclip/seg_${{SAFE}}.pid"
SEQFILE="/var/run/streamclip/seg_${{SAFE}}.seq"
LOCKFILE="/var/run/streamclip/seg_${{SAFE}}.lock"
SESSIONFILE="/var/run/streamclip/seg_${{SAFE}}.session"
LOG="/var/log/streamclip-segment.log"
WINDOW_S=300
MIN_BYTES=1000000
# Only treat an existing PID as ours if it is this segment-loop for this path.
# A stale/wrong PIDFILE must not silent-exit (agent would think recording started).
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    OLD_CMD=$(tr '\\0' ' ' < "/proc/$OLD_PID/cmdline" 2>/dev/null || true)
    if echo "$OLD_CMD" | grep -q 'streamclip-segment-loop' \\
      && echo "$OLD_CMD" | grep -Fq -- "$PATH_NAME"; then
      exit 0
    fi
    kill "$OLD_PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi
echo $$ > "$PIDFILE"
printf '%s\\n' "$PATH_NAME" > "/var/run/streamclip/seg_${{SAFE}}.path" || true
SEQ=0
[ -f "$SEQFILE" ] && SEQ=$(cat "$SEQFILE" 2>/dev/null || echo 0)
trap 'rm -f "$PIDFILE"' EXIT
# shellcheck disable=SC1091
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
while true; do
  # Do not cut another window once the plan hour is used.
  GATE_URL="${{EVENT_URL%/event}}/segment-gate"
  GATE=""
  for _try in 1 2 3; do
    GATE=$(curl -fsS --max-time 15 -G -H "X-Streamclip-Ingest-Secret: $HOOK" \\
      --data-urlencode "path=$PATH_NAME" "$GATE_URL" || true)
    [ -n "$GATE" ] && break
    sleep 2
  done
  STOP=$(printf '%s' "$GATE" | sed -n 's/.*"stop"[[:space:]]*:[[:space:]]*\\(true\\|false\\).*/\\1/p')
  RECORD_S=$(printf '%s' "$GATE" | sed -n 's/.*"record_seconds"[[:space:]]*:[[:space:]]*\\([0-9][0-9]*\\).*/\\1/p')
  if [ "$STOP" != "false" ] || [ -z "$RECORD_S" ] || [ "$RECORD_S" -le 0 ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) quota_stop path=$PATH_NAME" >>"$LOG" || true
    sleep 30
    continue
  fi
  # Unique S3 folder per live (= stream session id written on publisher_ready).
  LIVE_ID=$(cat "$SESSIONFILE" 2>/dev/null | tr -d '[:space:]' || true)
  [ -n "$LIVE_ID" ] || LIVE_ID="$SAFE"
  PART="/var/lib/streamclip/segments/${{SAFE}}_$(printf %04d "$SEQ").partial.mp4"
  OUT="/var/lib/streamclip/segments/${{SAFE}}_$(printf %04d "$SEQ").mp4"
  ANALYZE="/var/lib/streamclip/segments/analyze_${{SAFE}}_$(printf %04d "$SEQ").mp4"
  rm -f "$PART" "$OUT" "$ANALYZE"
  # Stream-copy the local RTMP. Do not ignore DTS (igndts stretches one video
  # frame across a congestion hole — picture frozen, audio still moving).
  # Keep the input queue modest: 4096 decoded-size packets plus a parallel
  # frame extract was enough to stall RTMP on 2 GiB.
  # OBS can stay connected to the edge while this reader drops or hangs
  # (librtmp often ignores -rw_timeout). Watch the file: if it stops growing,
  # kill ffmpeg and open a new read. Never exit the loop.
  ffmpeg -hide_banner -loglevel warning -y \\
      -threads 1 \\
      -thread_queue_size 1024 \\
      -analyzeduration 2000000 -probesize 5000000 \\
      -rw_timeout 20000000 \\
      -fflags +genpts+discardcorrupt \\
      -err_detect ignore_err \\
      -i "rtmp://127.0.0.1:1935/${{PATH_NAME}}" \\
      -t "$RECORD_S" \\
      -map "0:v:0" -map "0:a:0?" \\
      -c copy \\
      -avoid_negative_ts make_zero \\
      -max_muxing_queue_size 1024 \\
      -f mp4 -movflags frag_keyframe+empty_moov+default_base_moof \\
      "$PART" >>"$LOG" 2>&1 &
  FF_PID=$!
  LAST_SIZE=0
  STALL=0
  STARTED=$SECONDS
  LIMIT_S=$((RECORD_S + 45))
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
        curl -fsS --max-time 8 -X POST -H "Content-Type: application/json" \\
          -H "X-Streamclip-Ingest-Secret: $HOOK" \\
          -d "{{\\"event\\":\\"tick\\",\\"path\\":\\"${{PATH_NAME}}\\",\\"protocol\\":\\"rtmp\\",\\"processed_ms\\":1}}" \\
          "$EVENT_URL" >/dev/null 2>&1 || true
      fi
      kill -TERM "$FF_PID" 2>/dev/null || true
      sleep 1
      kill -KILL "$FF_PID" 2>/dev/null || true
      break
    fi
  done
  wait "$FF_PID" 2>/dev/null || true
  # Keep a partial window: a stall at the end must not throw away the minutes already captured.
  if [ -f "$PART" ]; then
    if timeout 60 ffmpeg -y -loglevel error -fflags +genpts -i "$PART" \\
        -map "0:v:0" -map "0:a:0?" -c copy \\
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
    SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT" 2>/dev/null || echo 0)
  fi
  if [ "$SIZE" -ge "$MIN_BYTES" ]; then
    KEY="tmp/lives/${{LIVE_ID}}/seg_$(printf %04d "$SEQ").mp4"
    exec 200>"$LOCKFILE"
    flock -x 200
    UPLOADED=1
    if [ -n "${{S3_BUCKET:-}}" ]; then
      UPLOADED=0
      for _n in 1 2 3 4 5; do
        if aws s3 cp "$OUT" "s3://${{S3_BUCKET}}/${{KEY}}" --region "${{AWS_REGION:-eu-north-1}}" --only-show-errors; then
          UPLOADED=1
          break
        fi
        sleep 2
      done
    fi
    if [ "$UPLOADED" != 1 ]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) upload_fail path=$PATH_NAME seq=$SEQ key=$KEY" >>"$LOG" || true
    fi
    # Ack only after the object is actually on S3. Analysis still runs from the local file.
    ACK=""
    if [ "$UPLOADED" = 1 ]; then
    ACK=$(curl -fsS --max-time 20 -X POST -H "Content-Type: application/json" \\
      -H "X-Streamclip-Ingest-Secret: $HOOK" \\
      -d "{{\\"event\\":\\"segment\\",\\"path\\":\\"${{PATH_NAME}}\\",\\"protocol\\":\\"rtmp\\",\\"storage_key\\":\\"${{KEY}}\\",\\"sequence\\":${{SEQ}},\\"size_bytes\\":${{SIZE}},\\"processed_ms\\":$((RECORD_S * 1000))}}" \\
      "$EVENT_URL" || true)
    fi
    if printf '%s' "$ACK" | grep -q 'quota_exhausted'; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) quota_drop path=$PATH_NAME seq=$SEQ" >>"$LOG" || true
      rm -f "$OUT" "$PART" "$ANALYZE"
      flock -u 200
      exec 200>&-
      continue
    fi
    mv -f "$OUT" "$ANALYZE"
    # Hand local file to :8080 — frames / ASR / Luna on this EC2, then DB via API.
    QUEUED=0
    for _n in 1 2 3 4 5; do
      if curl -fsS --max-time 10 -X POST -H "Content-Type: application/json" \\
        -d "{{\\"video_path\\":\\"${{ANALYZE}}\\",\\"stream_session_id\\":\\"${{LIVE_ID}}\\",\\"sequence\\":${{SEQ}},\\"storage_key\\":\\"${{KEY}}\\",\\"size_bytes\\":${{SIZE}}}}" \\
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
    # $ANALYZE is deleted by the :8080 agent after Luna finishes.
  else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) record_reject_tiny path=$PATH_NAME seq=$SEQ size=$SIZE" >>"$LOG" || true
    rm -f "$OUT" "$PART" "$ANALYZE"
    # Read died or the publisher is between relays. Retry; do not exit.
    sleep 2
    continue
  fi
done
AGENT
chmod +x /usr/local/bin/streamclip-segment-loop

# Agent binaries are fetched above (encrypted). Nothing secret is embedded here.

cat > /usr/local/bin/streamclip-on-ready <<'ONREADY'
#!/bin/bash
PATH_NAME="$1"
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
mkdir -p /var/run/streamclip /var/lib/streamclip/segments
# shellcheck disable=SC1091
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
RESP=$(curl -fsS -X POST -H "Content-Type: application/json" \\
  -H "X-Streamclip-Ingest-Secret: $HOOK" \\
  -d "{{\\"event\\":\\"publisher_ready\\",\\"path\\":\\"$PATH_NAME\\",\\"protocol\\":\\"rtmp\\"}}" \\
  "$EVENT_URL" || true)
SESSION_ID=$(printf '%s' "$RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("stream_session_id") or "")' 2>/dev/null || true)
printf '%s\\n' "$PATH_NAME" > "/var/run/streamclip/seg_${{SAFE}}.path" || true
if [ -n "$SESSION_ID" ]; then
  PREV=$(cat "/var/run/streamclip/seg_${{SAFE}}.session" 2>/dev/null | tr -d '[:space:]' || true)
  echo "$SESSION_ID" > "/var/run/streamclip/seg_${{SAFE}}.session"
  # New live → new S3 folder and sequence counter (history stays under old ids).
  if [ "$PREV" != "$SESSION_ID" ]; then
    echo 0 > "/var/run/streamclip/seg_${{SAFE}}.seq"
  fi
fi
if ! curl -fsS -X POST -H "Content-Type: application/json" \\
    -d "{{\\"path\\":\\"$PATH_NAME\\"}}" \\
    "http://127.0.0.1:8080/start"; then
  nohup /usr/local/bin/streamclip-segment-loop "$PATH_NAME" >>/var/log/streamclip-segment.log 2>&1 &
fi
ONREADY
chmod +x /usr/local/bin/streamclip-on-ready

cat > /usr/local/bin/streamclip-on-not-ready <<'OFFREADY'
#!/bin/bash
PATH_NAME="$1"
# shellcheck disable=SC1091
# Do not stop the segment loop. A publisher flap (edge relay reconnect, encoder
# stall) used to kill the recorder while OBS stayed connected, and nothing
# opened a new read. The loop reconnects to local RTMP on its own.
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
curl -fsS -X POST -H "Content-Type: application/json" \\
  -H "X-Streamclip-Ingest-Secret: $HOOK" \\
  -d "{{\\"event\\":\\"publisher_disconnect\\",\\"path\\":\\"$PATH_NAME\\",\\"protocol\\":\\"rtmp\\"}}" \\
  "$EVENT_URL" || true
OFFREADY
chmod +x /usr/local/bin/streamclip-on-not-ready

# Quote heredoc so $MTX_PATH is written literally for MediaMTX to expand at runtime.
cat > /etc/mediamtx/mediamtx.yml <<'YAML'
logLevel: info
# 1080p60 + HLS + segment ffmpeg reader. 8192 is a power of 2 and still
# absorbs a stall, without pinning most of a 4 GiB box on queued packets.
writeQueueSize: 8192
# OBS / encoder stalls longer than 15s used to drop the publisher and fire
# runOnNotReady while the agent stayed up — keep the RTMP path alive.
readTimeout: 60s
writeTimeout: 60s
rtmp: yes
rtmpAddress: :1935
srt: yes
srtAddress: :8890
webrtc: no
# Local-only HLS for dashboard/admin preview (proxied by the agent on :8080).
hls: yes
hlsAddress: 127.0.0.1:8888
hlsAlwaysRemux: yes
hlsSegmentCount: 12
hlsSegmentDuration: 2s
rtsp: yes
rtspAddress: :8554
authMethod: http
authHTTPAddress: AUTH_HTTP_ADDRESS_PLACEHOLDER
pathDefaults:
  # Timed 5-min capture is owned by streamclip-segment-loop (exact cadence).
  record: no
  runOnReady: /usr/local/bin/streamclip-on-ready $MTX_PATH
  runOnNotReady: /usr/local/bin/streamclip-on-not-ready $MTX_PATH
paths:
  all_others:
YAML
python3 - <<'PY'
import os
import shlex
from pathlib import Path
env = dict()
for line in Path("/etc/streamclip/agent.env").read_text().splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, raw = line.partition("=")
    env[key] = shlex.split(raw, posix=True)[0] if raw else ""
path = Path("/etc/mediamtx/mediamtx.yml")
text = path.read_text().replace(
    "AUTH_HTTP_ADDRESS_PLACEHOLDER", env.get("AUTH_HTTP_ADDRESS", "")
)
path.write_text(text)
os.chmod(path, 0o600)
os.chmod("/etc/streamclip/agent.env", 0o600)
PY

cat > /etc/systemd/system/streamclip-agent.service <<'UNIT'
[Unit]
Description=STREAMCLIP dedicated analysis agent (:8080)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
EnvironmentFile=-/etc/streamclip/agent.env
Environment=AWS_DEFAULT_REGION={region_q}
ExecStart=/usr/bin/python3 /usr/local/bin/streamclip-analysis-agent.py
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/mediamtx.service <<'UNIT'
[Unit]
Description=STREAMCLIP MediaMTX ingest
After=network-online.target streamclip-agent.service
Wants=network-online.target streamclip-agent.service
[Service]
Type=simple
ExecStart=/usr/local/bin/mediamtx /etc/mediamtx/mediamtx.yml
Restart=always
RestartSec=3
Environment=AWS_DEFAULT_REGION={region_q}
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now streamclip-agent
systemctl enable --now mediamtx
"""


    async def launch(self, *, organization_id: uuid.UUID, node_name: str) -> LaunchResult:
        settings = self._settings
        if not settings.ingest_launcher_configured:
            raise RuntimeError("Ingest EC2 launcher is not configured")

        def _run() -> LaunchResult:
            client = self._client()
            boot_prefix = self._publish_boot_bundle()
            raw_user_data = self._user_data(boot_prefix).encode("utf-8")
            user_data_b64 = base64.b64encode(raw_user_data).decode("ascii")
            # RunInstances rejects user-data whose raw size exceeds 16384 bytes.
            if len(raw_user_data) > 16384:
                raise RuntimeError(
                    f"EC2 user-data is {len(raw_user_data)} bytes (limit 16384). "
                    "Boot scripts must be fetched from S3."
                )
            kwargs: dict = {
                "ImageId": settings.ingest_ec2_ami_id,
                "InstanceType": settings.ingest_ec2_instance_type or "t4g.medium",
                "MinCount": 1,
                "MaxCount": 1,
                "SubnetId": settings.ingest_ec2_subnet_id,
                "SecurityGroupIds": [settings.ingest_ec2_security_group_id],
                "UserData": user_data_b64,
                "InstanceMarketOptions": {
                    "MarketType": "spot",
                    "SpotOptions": {"InstanceInterruptionBehavior": "terminate"},
                },
                "NetworkInterfaces": [
                    {
                        "DeviceIndex": 0,
                        "SubnetId": settings.ingest_ec2_subnet_id,
                        "Groups": [settings.ingest_ec2_security_group_id],
                        "AssociatePublicIpAddress": True,
                    }
                ],
                "TagSpecifications": [
                    {
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": "Name", "Value": node_name},
                            {"Key": "Role", "Value": "ingest"},
                            {"Key": "OrganizationId", "Value": str(organization_id)},
                        ],
                    }
                ],
            }
            # NetworkInterfaces and top-level SubnetId/SG conflict — drop top-level.
            kwargs.pop("SubnetId", None)
            kwargs.pop("SecurityGroupIds", None)
            if settings.ingest_ec2_instance_profile:
                kwargs["IamInstanceProfile"] = {"Name": settings.ingest_ec2_instance_profile}
            response = self._run_instances_with_failover(client, kwargs)
            instance = response["Instances"][0]
            instance_id = instance["InstanceId"]
            waiter = client.get_waiter("instance_running")
            waiter.wait(InstanceIds=[instance_id])
            # Public IP can lag a few seconds after running.
            public_ip = None
            for _ in range(12):
                desc = client.describe_instances(InstanceIds=[instance_id])
                public_ip = desc["Reservations"][0]["Instances"][0].get("PublicIpAddress")
                if public_ip:
                    break
                time.sleep(2)
            if not public_ip:
                client.terminate_instances(InstanceIds=[instance_id])
                raise RuntimeError(f"Instance {instance_id} has no public IP")
            return LaunchResult(instance_id=instance_id, public_hostname=public_ip)

        return await asyncio.to_thread(_run)

    def _candidate_subnets(self, client, primary: str) -> list[str]:
        """Public subnets in the configured VPC. Primary AZ first, then the others.

        eu-north-1b often has no t4g.medium capacity; 1a and 1c do.
        """
        try:
            described = client.describe_subnets(SubnetIds=[primary])["Subnets"][0]
            vpc_id = described["VpcId"]
            found = client.describe_subnets(
                Filters=[
                    {"Name": "vpc-id", "Values": [vpc_id]},
                    {"Name": "map-public-ip-on-launch", "Values": ["true"]},
                ]
            )["Subnets"]
        except Exception as exc:  # noqa: BLE001 — fall back to the configured subnet
            log.warning("ingest_subnet_lookup_failed", error=str(exc)[:200])
            return [primary]
        rest = [
            row["SubnetId"]
            for row in sorted(found, key=lambda row: row.get("AvailabilityZone") or "")
            if row["SubnetId"] != primary
        ]
        return [primary, *rest]

    def _run_instances_with_failover(self, client, kwargs: dict) -> dict:
        """Try spot, then on-demand, across AZs when one zone has no capacity."""
        from botocore.exceptions import ClientError

        primary = kwargs["NetworkInterfaces"][0]["SubnetId"]
        subnets = self._candidate_subnets(client, primary)
        capacity_codes = {
            "InsufficientInstanceCapacity",
            "InsufficientFreeAddressesInSubnet",
            "MaxSpotInstanceCountExceeded",
            "SpotMaxPriceTooLow",
        }
        last_error: Exception | None = None
        for spot in (True, False):
            for subnet_id in subnets:
                params = {
                    **kwargs,
                    "NetworkInterfaces": [
                        {**kwargs["NetworkInterfaces"][0], "SubnetId": subnet_id}
                    ],
                }
                if spot:
                    params["InstanceMarketOptions"] = {
                        "MarketType": "spot",
                        "SpotOptions": {"InstanceInterruptionBehavior": "terminate"},
                    }
                else:
                    params.pop("InstanceMarketOptions", None)
                try:
                    response = client.run_instances(**params)
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code not in capacity_codes:
                        raise
                    last_error = exc
                    log.warning(
                        "ingest_spot_capacity_retry",
                        subnet_id=subnet_id,
                        spot=spot,
                        code=code,
                    )
                    continue
                log.info(
                    "ingest_instance_launched",
                    subnet_id=subnet_id,
                    spot=spot,
                    instance_id=response["Instances"][0]["InstanceId"],
                )
                return response
        if last_error is not None:
            raise last_error
        raise RuntimeError("No subnet available for the ingest instance")

    async def terminate(self, *, instance_id: str) -> None:
        def _run() -> None:
            self._client().terminate_instances(InstanceIds=[instance_id])

        await asyncio.to_thread(_run)
        log.info("ingest_spot_terminated", instance_id=instance_id)

    async def describe_instance(self, *, instance_id: str) -> InstanceView:
        """Ask EC2 whether this spot still exists. A DB row is not enough."""

        def _run() -> InstanceView:
            from botocore.exceptions import ClientError

            try:
                described = self._client().describe_instances(InstanceIds=[instance_id])
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"InvalidInstanceID.NotFound", "InvalidInstanceID.Malformed"}:
                    return InstanceView(state="missing", public_hostname=None)
                raise
            reservations = described.get("Reservations") or []
            if not reservations or not reservations[0].get("Instances"):
                return InstanceView(state="missing", public_hostname=None)
            instance = reservations[0]["Instances"][0]
            state = (instance.get("State") or {}).get("Name") or "unknown"
            return InstanceView(
                state=state,
                public_hostname=instance.get("PublicIpAddress"),
            )

        return await asyncio.to_thread(_run)


_FAKE = FakeSpotLauncher()


def get_launcher(settings: Settings) -> SpotLauncher:
    """AWS launcher when configured; unique fake hosts in test/local only."""
    if settings.environment == "test":
        return _FAKE
    if settings.ingest_launcher_configured:
        return AwsSpotLauncher(settings)
    if settings.environment == "local":
        return _FAKE
    raise RuntimeError(
        "Ingest EC2 launcher is not configured "
        "(INGEST_EC2_AMI_ID / SUBNET / SECURITY_GROUP required)"
    )
