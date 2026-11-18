"""Launch / terminate dedicated t4g.small spot instances for ingest.

Each organization gets its own EC2 (unique public IP). There is no shared
fallback host: if launch fails, resolve fails.
"""

from __future__ import annotations

import asyncio
import base64
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


class SpotLauncher(Protocol):
    async def launch(self, *, organization_id: uuid.UUID, node_name: str) -> LaunchResult: ...

    async def terminate(self, *, instance_id: str) -> None: ...


class FakeSpotLauncher:
    """Deterministic unique hosts for tests / local without AWS."""

    def __init__(self) -> None:
        self.launched: dict[str, str] = {}

    async def launch(self, *, organization_id: uuid.UUID, node_name: str) -> LaunchResult:
        instance_id = f"i-fake-{organization_id.hex[:12]}"
        # Unique per org — never a shared fallback.
        host = f"{organization_id.hex[:12]}.ingest.test"
        self.launched[instance_id] = host
        return LaunchResult(instance_id=instance_id, public_hostname=host)

    async def terminate(self, *, instance_id: str) -> None:
        self.launched.pop(instance_id, None)


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

    def _user_data(self) -> str:
        """Per-org spot: MediaMTX RTMP + :8080 on-box analysis (frames/ASR/Luna).

        Vercel only receives segment acks and persisted highlight JSON — never
        runs FFmpeg / Bedrock for live segments.
        """
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
        bucket = (settings.s3_bucket or "").strip()
        region = (
            settings.ingest_ec2_region
            or settings.s3_region
            or "eu-north-1"
        )
        asr_provider = (settings.asr_provider or "none").strip()
        asr_key = (
            settings.asr_api_key.get_secret_value() if settings.asr_api_key else ""
        )
        asr_base = (settings.asr_base_url or "https://api.groq.com/openai/v1").strip()
        asr_model = (settings.asr_model or "whisper-large-v3-turbo").strip()
        bedrock_region = (settings.bedrock_region or "us-east-1").strip()
        bedrock_model = (settings.bedrock_model or "us.openai.gpt-6-luna").strip()
        # Secret on query string: MediaMTX 1.12 has no authHTTPAdditionalHeaders.
        auth_with_secret = f"{auth_url}?ingest_secret={hook}" if auth_url else ""
        # Escape single quotes for embedding in shell single-quoted strings.
        def _sq(value: str) -> str:
            return value.replace("'", "'\\''")

        hook_q = _sq(hook)
        event_q = _sq(event_url)
        bucket_q = _sq(bucket)
        region_q = _sq(region)
        auth_q = _sq(auth_with_secret)
        asr_provider_q = _sq(asr_provider)
        asr_key_q = _sq(asr_key)
        asr_base_q = _sq(asr_base)
        asr_model_q = _sq(asr_model)
        bedrock_region_q = _sq(bedrock_region)
        bedrock_model_q = _sq(bedrock_model)

        agent_path = Path(__file__).with_name("ingest_agent.py")
        agent_b64 = base64.b64encode(agent_path.read_bytes()).decode("ascii")
        onbox_path = Path(__file__).with_name("ingest_onbox_analyze.py")
        onbox_b64 = base64.b64encode(onbox_path.read_bytes()).decode("ascii")

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
cat > /etc/streamclip/agent.env <<ENV
HOOK={hook_q}
EVENT_URL={event_q}
S3_BUCKET={bucket_q}
AWS_REGION={region_q}
ASR_PROVIDER={asr_provider_q}
ASR_API_KEY={asr_key_q}
ASR_BASE_URL={asr_base_q}
ASR_MODEL={asr_model_q}
BEDROCK_REGION={bedrock_region_q}
BEDROCK_MODEL={bedrock_model_q}
ENV
chmod 600 /etc/streamclip/agent.env
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
  # Unique S3 folder per live (= stream session id written on publisher_ready).
  LIVE_ID=$(cat "$SESSIONFILE" 2>/dev/null | tr -d '[:space:]' || true)
  [ -n "$LIVE_ID" ] || LIVE_ID="$SAFE"
  PART="/var/lib/streamclip/segments/${{SAFE}}_$(printf %04d "$SEQ").partial.mp4"
  OUT="/var/lib/streamclip/segments/${{SAFE}}_$(printf %04d "$SEQ").mp4"
  ANALYZE="/var/lib/streamclip/segments/analyze_${{SAFE}}_$(printf %04d "$SEQ").mp4"
  rm -f "$PART" "$OUT" "$ANALYZE"
  # Local RTMP copy into fragmented MP4 (avoids moov stalls / sparse frames).
  # No wallclock remapping — keeps source timestamps and full bitrate.
  if ffmpeg -hide_banner -y \\
      -rw_timeout 15000000 \\
      -fflags +genpts+igndts \\
      -i "rtmp://127.0.0.1:1935/${{PATH_NAME}}" \\
      -t "$WINDOW_S" \\
      -map 0 \\
      -c copy \\
      -f mp4 -movflags frag_keyframe+empty_moov+default_base_moof \\
      "$PART" 2>>"$LOG"; then
    if ffmpeg -y -i "$PART" -c copy -movflags +faststart "$OUT" 2>>"$LOG"; then
      rm -f "$PART"
    else
      mv -f "$PART" "$OUT" 2>/dev/null || OUT="$PART"
    fi
  else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) record_fail path=$PATH_NAME seq=$SEQ" >>"$LOG" || true
    rm -f "$PART" "$OUT"
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
    if [ -n "${{S3_BUCKET:-}}" ]; then
      aws s3 cp "$OUT" "s3://${{S3_BUCKET}}/${{KEY}}" --region "${{AWS_REGION:-eu-north-1}}" || true
    fi
    # Ack upload on API (no Vercel analysis). Analysis runs on :8080 below.
    curl -fsS --max-time 15 -X POST -H "Content-Type: application/json" \\
      -H "X-Streamclip-Ingest-Secret: $HOOK" \\
      -d "{{\\"event\\":\\"segment\\",\\"path\\":\\"${{PATH_NAME}}\\",\\"protocol\\":\\"rtmp\\",\\"storage_key\\":\\"${{KEY}}\\",\\"sequence\\":${{SEQ}},\\"size_bytes\\":${{SIZE}},\\"processed_ms\\":300000}}" \\
      "$EVENT_URL" || true
    mv -f "$OUT" "$ANALYZE"
    # Hand local file to :8080 — frames / ASR / Luna on this EC2, then DB via API.
    curl -fsS --max-time 10 -X POST -H "Content-Type: application/json" \\
      -d "{{\\"video_path\\":\\"${{ANALYZE}}\\",\\"stream_session_id\\":\\"${{LIVE_ID}}\\",\\"sequence\\":${{SEQ}},\\"storage_key\\":\\"${{KEY}}\\",\\"size_bytes\\":${{SIZE}}}}" \\
      "http://127.0.0.1:8080/analyze" || \\
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) analyze_queue_fail path=$PATH_NAME seq=$SEQ" >>"$LOG" || true
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
    # Failure: start the next full 5-min capture immediately (do not sleep out the rest).
    continue
  fi
done
AGENT
chmod +x /usr/local/bin/streamclip-segment-loop

echo '{agent_b64}' | base64 -d > /usr/local/bin/streamclip-analysis-agent.py
chmod +x /usr/local/bin/streamclip-analysis-agent.py
echo '{onbox_b64}' | base64 -d > /usr/local/bin/streamclip_onbox_analyze.py
chmod +x /usr/local/bin/streamclip_onbox_analyze.py

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
[ -f /etc/streamclip/agent.env ] && . /etc/streamclip/agent.env
curl -fsS -X POST -H "Content-Type: application/json" \\
  -d "{{\\"path\\":\\"$PATH_NAME\\"}}" \\
  "http://127.0.0.1:8080/stop" || true
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
PIDFILE="/var/run/streamclip/seg_$SAFE.pid"
if [ -f "$PIDFILE" ]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
fi
curl -fsS -X POST -H "Content-Type: application/json" \\
  -H "X-Streamclip-Ingest-Secret: $HOOK" \\
  -d "{{\\"event\\":\\"publisher_disconnect\\",\\"path\\":\\"$PATH_NAME\\",\\"protocol\\":\\"rtmp\\"}}" \\
  "$EVENT_URL" || true
OFFREADY
chmod +x /usr/local/bin/streamclip-on-not-ready

# Quote heredoc so $MTX_PATH is written literally for MediaMTX to expand at runtime.
cat > /etc/mediamtx/mediamtx.yml <<'YAML'
logLevel: info
# 1080p60 + HLS + segment ffmpeg reader: large write queue (power of 2).
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
hlsSegmentCount: 7
hlsSegmentDuration: 1s
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
sed -i "s|AUTH_HTTP_ADDRESS_PLACEHOLDER|{auth_q}|" /etc/mediamtx/mediamtx.yml

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
        return script

    async def launch(self, *, organization_id: uuid.UUID, node_name: str) -> LaunchResult:
        settings = self._settings
        if not settings.ingest_launcher_configured:
            raise RuntimeError("Ingest EC2 launcher is not configured")

        def _run() -> LaunchResult:
            client = self._client()
            user_data_b64 = base64.b64encode(self._user_data().encode("utf-8")).decode("ascii")
            kwargs: dict = {
                "ImageId": settings.ingest_ec2_ami_id,
                "InstanceType": settings.ingest_ec2_instance_type or "t4g.small",
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
            response = client.run_instances(**kwargs)
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

    async def terminate(self, *, instance_id: str) -> None:
        def _run() -> None:
            self._client().terminate_instances(InstanceIds=[instance_id])

        await asyncio.to_thread(_run)
        log.info("ingest_spot_terminated", instance_id=instance_id)


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
