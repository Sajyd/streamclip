"""AWS sessions via STS AssumeRole.

Bootstrap credentials (S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY) are only used
to call sts:AssumeRole. Every service client (S3, EC2, Bedrock) uses the
temporary role credentials — never the long-lived key directly.
"""

from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.credentials import RefreshableCredentials
from botocore.session import get_session as get_botocore_session

from app.core.config import Settings

_SESSION_CACHE: dict[str, tuple[float, Any]] = {}
_SESSION_TTL_SEC = 45 * 60  # refresh before the typical 1h expiry


def _bootstrap_client(settings: Settings, service: str):
    access = settings.s3_access_key_id
    secret = settings.s3_secret_access_key
    region = (
        settings.ingest_ec2_region
        or settings.s3_region
        or settings.bedrock_region
        or "eu-north-1"
    )
    kwargs: dict[str, Any] = {"region_name": region}
    if access is not None and secret is not None:
        kwargs["aws_access_key_id"] = access.get_secret_value()
        kwargs["aws_secret_access_key"] = secret.get_secret_value()
    return boto3.client(service, **kwargs)


def assume_role_credentials(settings: Settings) -> dict[str, str]:
    role_arn = (settings.aws_role_arn or "").strip()
    if not role_arn:
        raise RuntimeError("AWS_ROLE_ARN is required for AssumeRole")
    sts = _bootstrap_client(settings, "sts")
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=settings.aws_role_session_name or "streamclip-api",
        DurationSeconds=min(settings.aws_role_duration_seconds or 3600, 3600),
    )
    creds = response["Credentials"]
    return {
        "access_key": creds["AccessKeyId"],
        "secret_key": creds["SecretAccessKey"],
        "token": creds["SessionToken"],
        "expiry_time": creds["Expiration"].isoformat(),
    }


def boto3_session(settings: Settings) -> boto3.Session:
    """Return a boto3 Session whose credentials come from AssumeRole."""
    role_arn = (settings.aws_role_arn or "").strip()
    region = (
        settings.ingest_ec2_region
        or settings.s3_region
        or settings.bedrock_region
        or "eu-north-1"
    )
    if not role_arn:
        # Local/test without a role: fall back to bootstrap keys only.
        access = settings.s3_access_key_id
        secret = settings.s3_secret_access_key
        if access is None or secret is None:
            return boto3.Session(region_name=region)
        return boto3.Session(
            aws_access_key_id=access.get_secret_value(),
            aws_secret_access_key=secret.get_secret_value(),
            region_name=region,
        )

    cache_key = f"{role_arn}:{region}"
    now = time.time()
    cached = _SESSION_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    def refresh() -> dict[str, str]:
        return assume_role_credentials(settings)

    metadata = refresh()
    refreshable = RefreshableCredentials.create_from_metadata(
        metadata=metadata,
        refresh_using=refresh,
        method="sts-assume-role",
    )
    botocore_session = get_botocore_session()
    botocore_session._credentials = refreshable  # noqa: SLF001 - intentional
    botocore_session.set_config_variable("region", region)
    session = boto3.Session(botocore_session=botocore_session, region_name=region)
    _SESSION_CACHE[cache_key] = (now + _SESSION_TTL_SEC, session)
    return session


def client(settings: Settings, service: str, **kwargs: Any):
    return boto3_session(settings).client(service, **kwargs)
