"""S3-compatible storage backend.

Wraps the synchronous boto3 client in `asyncio.to_thread` so callers can
await uploads/downloads without blocking the event loop. Works with native
AWS S3, MinIO, GCS via the S3-compatible API, DigitalOcean Spaces, and any
other S3-compatible provider — addressing style and endpoint URL are both
configurable via env vars.

# Endpoint behavior
# -----------------
# - Native AWS S3: leave `endpoint` unset; boto3 picks the regional endpoint.
# - MinIO/local: set `endpoint=http://minio:9000` and `allow_http=True`.
# - GCS: set `endpoint=https://storage.googleapis.com`, `region=auto`, and
#   use HMAC keys (NOT GCP service account keys) as access_key_id/secret.
#
# # Addressing style
# `path` (`http://endpoint/bucket/key`) is required for MinIO. `virtual`
# (`http://bucket.endpoint/key`) is required for some AWS S3 buckets in
# certain regions. `auto` lets the SDK decide — usually correct for AWS.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class S3StorageProvider:
    """Storage provider wrapping boto3 S3 client via asyncio.to_thread."""

    def __init__(
        self,
        bucket: str,
        endpoint: str | None = None,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        allow_http: bool = False,
        addressing_style: str = "auto",
    ) -> None:
        self.bucket = bucket

        endpoint_url = None
        if endpoint:
            if not endpoint.startswith("http://") and not endpoint.startswith(
                "https://"
            ):
                scheme = "http" if allow_http else "https"
                endpoint_url = f"{scheme}://{endpoint}"
            else:
                endpoint_url = endpoint

        config = Config(
            s3={"addressing_style": addressing_style},
            retries={"max_attempts": 3, "mode": "adaptive"},
        )

        kwargs: dict = {
            "service_name": "s3",
            "region_name": region,
            "config": config,
        }
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key_id:
            kwargs["aws_access_key_id"] = access_key_id
        if secret_access_key:
            kwargs["aws_secret_access_key"] = secret_access_key

        self.client = boto3.client(**kwargs)

    async def put(self, key: str, data: BinaryIO | bytes) -> str:
        """Store data at key. Returns s3://bucket/key URI."""
        if isinstance(data, bytes):
            await asyncio.to_thread(
                self.client.put_object, Bucket=self.bucket, Key=key, Body=data
            )
        else:
            await asyncio.to_thread(self.client.upload_fileobj, data, self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key."""

        def _get():
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        return await asyncio.to_thread(_get)

    async def get_to_file(self, key: str, dest: Path) -> Path:
        """Download key to a local file path. Creates parent dirs."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self.client.download_file, self.bucket, key, str(dest))
        return dest

    async def delete(self, key: str) -> None:
        """Delete a key. S3 silently ignores missing keys."""
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        """Check if a key exists via head_object."""

        def _exists():
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    return False
                raise

        return await asyncio.to_thread(_exists)

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix."""

        def _list():
            keys = []
            params = {"Bucket": self.bucket, "Prefix": prefix}
            while True:
                response = self.client.list_objects_v2(**params)
                keys.extend(obj["Key"] for obj in response.get("Contents", []))
                if not response.get("IsTruncated"):
                    break
                params["ContinuationToken"] = response["NextContinuationToken"]
            return keys

        return await asyncio.to_thread(_list)

    async def health_check(self) -> None:
        """Verify the S3 bucket is reachable via head_bucket."""
        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)

    # --- Presigned URL methods (synchronous -- router wraps in asyncio.to_thread) ---

    def generate_presigned_put_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expiration: int = 3600,
    ) -> str:
        """Generate a presigned PUT URL for direct upload."""
        return self.client.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expiration,
        )

    def generate_presigned_get_url(
        self,
        key: str,
        expiration: int = 3600,
    ) -> str:
        """Generate a presigned GET URL for download."""
        return self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expiration,
        )

    def initiate_multipart_upload(
        self,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Initiate a multipart upload, returns upload_id."""
        response = self.client.create_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            ContentType=content_type,
        )
        return response["UploadId"]

    def generate_presigned_part_url(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expiration: int = 7200,
    ) -> str:
        """Generate a presigned URL for uploading a single part."""
        return self.client.generate_presigned_url(
            ClientMethod="upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expiration,
        )

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: list[dict],
    ) -> None:
        """Complete a multipart upload with the list of {ETag, PartNumber} dicts."""
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """Abort an in-progress multipart upload."""
        self.client.abort_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
        )
