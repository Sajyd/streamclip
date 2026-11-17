"""Private object storage on Amazon S3.

The bucket is never public. Clients only ever receive short-lived pre-signed
URLs, issued after the API has verified that the object belongs to the
caller's organization. Keys are namespaced per tenant:

    tenants/<organization_id>/exports/...   personal-data exports (expire)
    tenants/<organization_id>/clips/...     rendered clips
    tmp/...                                 processing buffers (expire fast)
"""

import asyncio
import uuid
from typing import Any

from botocore.config import Config
from botocore.exceptions import ClientError

from app.aws.session import boto3_session
from app.core.config import Settings

EXPORTS_PREFIX = "exports"
TENANTS_PREFIX = "tenants/"
# Objects carrying this tag are removed by a bucket lifecycle rule even if
# the application never deletes them. Must match the Terraform storage module.
SHORT_RETENTION_TAG = "streamclip-retention=short"


def tenant_prefix(organization_id: uuid.UUID) -> str:
    return f"{TENANTS_PREFIX}{organization_id}/"


def tenant_key(organization_id: uuid.UUID, *parts: str) -> str:
    for part in parts:
        if not part or part.startswith("/") or ".." in part.split("/"):
            raise ValueError("Unsafe object key component")
    return tenant_prefix(organization_id) + "/".join(parts)


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        if not settings.storage_enabled:
            raise ValueError("Object storage is not configured")
        self.bucket: str = settings.s3_bucket or ""
        # Credentials come from AssumeRole (bootstrap keys never touch S3 APIs).
        self._client: Any = boto3_session(settings).client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    async def check(self) -> None:
        """Readiness probe: credentials valid, bucket reachable, access granted.

        Lists a single key under the application prefix, which is all the
        restricted runtime identity is allowed to see of the bucket.
        """
        await asyncio.to_thread(
            self._client.list_objects_v2, Bucket=self.bucket, Prefix=TENANTS_PREFIX, MaxKeys=1
        )

    async def put_object(
        self, key: str, body: bytes, *, content_type: str, short_retention: bool = False
    ) -> None:
        extra: dict[str, Any] = {"Tagging": SHORT_RETENTION_TAG} if short_retention else {}
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="AES256",
            **extra,
        )

    async def get_object(self, key: str) -> bytes:
        response = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        body = response["Body"]
        return await asyncio.to_thread(body.read)

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def object_exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def _delete_prefix(self, prefix: str) -> int:
        deleted = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                self._client.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": keys, "Quiet": True}
                )
                deleted += len(keys)
        return deleted

    async def delete_tenant_objects(self, organization_id: uuid.UUID) -> int:
        """Erase everything stored for one organization (account deletion)."""
        return await asyncio.to_thread(self._delete_prefix, tenant_prefix(organization_id))

    async def presigned_download_url(
        self, key: str, *, expires_seconds: int = 300, filename: str | None = None
    ) -> str:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if filename:
            safe = "".join(c for c in filename if c.isalnum() or c in "._- ") or "download"
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )
