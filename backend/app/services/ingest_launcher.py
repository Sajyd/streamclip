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
        """MediaMTX 1.12 + on-box 5-min HD segment loop → S3 → API analysis."""
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

        # Native MediaMTX so runOn* can call host ffmpeg / aws / curl.
        script = f"""#!/bin/bash
set -eo pipefail
dnf install -y ffmpeg || echo "ffmpeg unavailable"
dnf install -y awscli || dnf install -y aws-cli || true
mkdir -p /etc/mediamtx /var/lib/streamclip/segments /var/run/streamclip /usr/local/bin
export AWS_DEFAULT_REGION='{region_q}'
MTX_VER=1.12.3
curl -fsSL "https://github.com/bluenviron/mediamtx/releases/download/v${{MTX_VER}}/mediamtx_v${{MTX_VER}}_linux_arm64.tar.gz" \\
  | tar -xz -C /usr/local/bin mediamtx
chmod +x /usr/local/bin/mediamtx

cat > /usr/local/bin/streamclip-segment-loop <<'AGENT'
#!/bin/bash
set -eo pipefail
PATH_NAME="$1"
SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
PIDFILE="/var/run/streamclip/seg_${{SAFE}}.pid"
SEQFILE="/var/run/streamclip/seg_${{SAFE}}.seq"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi
echo $$ > "$PIDFILE"
SEQ=0
[ -f "$SEQFILE" ] && SEQ=$(cat "$SEQFILE")
trap 'rm -f "$PIDFILE"' EXIT
while true; do
  OUT="/var/lib/streamclip/segments/${{SAFE}}_$(printf %04d "$SEQ").mp4"
  rm -f "$OUT"
  if ! ffmpeg -y -rw_timeout 15000000 -i "rtmp://127.0.0.1/${{PATH_NAME}}" \\
      -t 300 -c copy -f mp4 -movflags +faststart "$OUT"; then
    sleep 2
    continue
  fi
  if [ ! -s "$OUT" ]; then
    sleep 1
    continue
  fi
  KEY="tmp/lives/${{SAFE}}/seg_$(printf %04d "$SEQ").mp4"
  SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT")
  if [ -n "$S3_BUCKET" ]; then
    aws s3 cp "$OUT" "s3://${{S3_BUCKET}}/${{KEY}}" --region "$AWS_REGION" || true
  fi
  curl -fsS -X POST -H "Content-Type: application/json" \\
    -H "X-Streamclip-Ingest-Secret: $HOOK" \\
    -d "{{\\"event\\":\\"segment\\",\\"path\\":\\"${{PATH_NAME}}\\",\\"protocol\\":\\"rtmp\\",\\"storage_key\\":\\"${{KEY}}\\",\\"sequence\\":${{SEQ}},\\"size_bytes\\":${{SIZE}},\\"processed_ms\\":300000}}" \\
    "$EVENT_URL" || true
  SEQ=$((SEQ + 1))
  echo "$SEQ" > "$SEQFILE"
  rm -f "$OUT"
done
AGENT
chmod +x /usr/local/bin/streamclip-segment-loop

cat > /usr/local/bin/streamclip-on-ready <<'ONREADY'
#!/bin/bash
PATH_NAME="$1"
export HOOK='{hook_q}' EVENT_URL='{event_q}' S3_BUCKET='{bucket_q}' AWS_REGION='{region_q}'
curl -fsS -X POST -H "Content-Type: application/json" \\
  -H "X-Streamclip-Ingest-Secret: $HOOK" \\
  -d "{{\\"event\\":\\"publisher_ready\\",\\"path\\":\\"$PATH_NAME\\",\\"protocol\\":\\"rtmp\\"}}" \\
  "$EVENT_URL" || true
nohup /usr/local/bin/streamclip-segment-loop "$PATH_NAME" >>/var/log/streamclip-segment.log 2>&1 &
ONREADY
chmod +x /usr/local/bin/streamclip-on-ready

cat > /usr/local/bin/streamclip-on-not-ready <<'OFFREADY'
#!/bin/bash
PATH_NAME="$1"
export HOOK='{hook_q}' EVENT_URL='{event_q}'
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

cat > /etc/mediamtx/mediamtx.yml <<YAML
logLevel: info
rtmp: yes
rtmpAddress: :1935
srt: yes
srtAddress: :8890
webrtc: no
hls: no
rtsp: no
authMethod: http
authHTTPAddress: '{auth_q}'
pathDefaults:
  runOnReady: /usr/local/bin/streamclip-on-ready $MTX_PATH
  runOnNotReady: /usr/local/bin/streamclip-on-not-ready $MTX_PATH
paths:
  all_others:
YAML

cat > /etc/systemd/system/mediamtx.service <<'UNIT'
[Unit]
Description=STREAMCLIP MediaMTX ingest
After=network-online.target
Wants=network-online.target
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
