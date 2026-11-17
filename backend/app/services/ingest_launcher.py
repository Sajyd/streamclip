"""Launch / terminate dedicated t4g.small spot instances for ingest.

Each organization gets its own EC2 (unique public IP). There is no shared
fallback host: if launch fails, resolve fails.
"""

from __future__ import annotations

import asyncio
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

        return boto3_session(self._settings).client("ec2")

    def _user_data(self) -> str:
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
        # Keep userdata compact; mirrors terraform ingest_node module.
        return f"""#!/bin/bash
set -euo pipefail
dnf install -y docker
dnf install -y ffmpeg || true
systemctl enable --now docker
mkdir -p /etc/mediamtx
cat >/etc/mediamtx/mediamtx.yml <<'YAML'
logLevel: info
rtmp: yes
rtmpAddress: :1935
srt: yes
srtAddress: :8890
webrtc: no
hls: no
rtsp: no
authMethod: http
authHTTPAddress: {auth_url}
authHTTPAdditionalHeaders:
  X-Streamclip-Ingest-Secret: "{hook}"
pathDefaults:
  runOnReady: curl -fsS -X POST -H "Content-Type: application/json" -H "X-Streamclip-Ingest-Secret: {hook}" -d "{{\\"event\\":\\"publisher_ready\\",\\"path\\":\\"$MTX_PATH\\",\\"protocol\\":\\"rtmp\\"}}" {event_url} || true
  runOnNotReady: curl -fsS -X POST -H "Content-Type: application/json" -H "X-Streamclip-Ingest-Secret: {hook}" -d "{{\\"event\\":\\"publisher_disconnect\\",\\"path\\":\\"$MTX_PATH\\",\\"protocol\\":\\"rtmp\\"}}" {event_url} || true
paths:
  "~^live/":
    source: publisher
YAML
docker rm -f mediamtx 2>/dev/null || true
docker run -d --name mediamtx --restart unless-stopped \
  -p 1935:1935 -p 8890:8890/udp -p 8080:8080 \
  -v /etc/mediamtx/mediamtx.yml:/mediamtx.yml:ro \
  bluenviron/mediamtx:1.11.3
"""

    async def launch(self, *, organization_id: uuid.UUID, node_name: str) -> LaunchResult:
        settings = self._settings
        if not settings.ingest_launcher_configured:
            raise RuntimeError("Ingest EC2 launcher is not configured")

        def _run() -> LaunchResult:
            client = self._client()
            kwargs: dict = {
                "ImageId": settings.ingest_ec2_ami_id,
                "InstanceType": settings.ingest_ec2_instance_type or "t4g.small",
                "MinCount": 1,
                "MaxCount": 1,
                "SubnetId": settings.ingest_ec2_subnet_id,
                "SecurityGroupIds": [settings.ingest_ec2_security_group_id],
                "UserData": self._user_data(),
                "InstanceMarketOptions": {
                    "MarketType": "spot",
                    "SpotOptions": {"InstanceInterruptionBehavior": "terminate"},
                },
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
            if settings.ingest_ec2_instance_profile:
                kwargs["IamInstanceProfile"] = {"Name": settings.ingest_ec2_instance_profile}
            response = client.run_instances(**kwargs)
            instance = response["Instances"][0]
            instance_id = instance["InstanceId"]
            waiter = client.get_waiter("instance_running")
            waiter.wait(InstanceIds=[instance_id])
            desc = client.describe_instances(InstanceIds=[instance_id])
            public_ip = desc["Reservations"][0]["Instances"][0].get("PublicIpAddress")
            if not public_ip:
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
