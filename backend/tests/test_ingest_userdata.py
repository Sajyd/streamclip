"""EC2 user-data must stay under the RunInstances 16 KiB raw limit."""

from __future__ import annotations

from app.services.ingest_launcher import AwsSpotLauncher


def test_user_data_is_a_short_s3_bootstrap() -> None:
    launcher = AwsSpotLauncher.__new__(AwsSpotLauncher)

    class _Settings:
        s3_bucket = "stream-clip"
        s3_region = "eu-north-1"
        ingest_ec2_region = "eu-north-1"

    launcher._settings = _Settings()
    raw = launcher._user_data("tmp/boot/example").encode()
    bootstrap = launcher._bootstrap_script("eu-north-1")

    assert len(raw) <= 16384
    assert b"streamclip-bootstrap.sh" in raw
    assert "seg_${SAFE}.pid" in bootstrap
    assert "AWS_DEFAULT_REGION=eu-north-1" in bootstrap
