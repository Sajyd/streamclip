"""EC2 user-data must stay under both RunInstances size limits."""

from __future__ import annotations

import base64
import gzip

from botocore.handlers import base64_encode_user_data

from app.services.ingest_launcher import AwsSpotLauncher


class _Secret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


def test_user_data_is_gzipped_and_never_uploaded() -> None:
    launcher = AwsSpotLauncher.__new__(AwsSpotLauncher)

    class _Settings:
        s3_bucket = "stream-clip"
        s3_region = "eu-north-1"
        ingest_ec2_region = "eu-north-1"
        ingest_api_auth_url = "https://streamclip.fr/api/v1/ingest/hooks/auth"
        ingest_api_event_url = "https://streamclip.fr/api/v1/ingest/hooks/event"
        ingest_hook_secret = _Secret("hook-" + "a" * 40)
        asr_provider = "groq"
        asr_api_key = _Secret("gsk_" + "k" * 48)
        asr_base_url = "https://api.groq.com/openai/v1"
        asr_model = "whisper-large-v3-turbo"
        bedrock_region = "us-east-1"
        bedrock_model = "us.openai.gpt-6-luna"

    launcher._settings = _Settings()
    blob = launcher._user_data_gzip()
    script = gzip.decompress(blob).decode()

    assert blob[:2] == b"\x1f\x8b"
    assert len(blob) <= 16384
    # boto3 encodes UserData. The value EC2 receives must stay <= 25600 bytes.
    params = {"UserData": blob}
    base64_encode_user_data(params)
    encoded = params["UserData"].encode("ascii")
    assert len(encoded) <= 25600
    assert base64.b64decode(encoded) == blob
    assert "tmp/boot/" not in script
    assert "BOOT_PREFIX" not in script
    assert "aws s3 cp" not in script.split("cat > /etc/streamclip/agent.env", 1)[0]
    assert "HOOK=" in script
    assert "seg_${SAFE}.pid" in script
    assert "AWS_DEFAULT_REGION=eu-north-1" in script
    assert not hasattr(launcher, "_publish_boot_bundle")
    agent = launcher._packed_agent_source()
    onbox = launcher._packed_onbox_source()
    assert "class Handler" in agent
    assert "def _supervise_loops" in agent
    assert "def _render_html" in agent
    compile(agent, "agent.py", "exec")
    compile(onbox, "onbox.py", "exec")
    assert "mistral.voxtral-small-24b-2507" in onbox
    assert "def _supervise_loops" in agent
