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
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.platform.storage.provider import StoredObject

# Matches LocalStorageProvider's chunk size: one 1 MiB buffer resident per
# stream, whatever the object weighs.
_STREAM_CHUNK_BYTES = 1024 * 1024


def _as_utc(value: datetime) -> datetime:
    """Normalize a provider timestamp to timezone-aware UTC.

    feat(#1249): botocore returns aware datetimes today, but the
    ``StoredObject`` contract is what the reconciliation's cutoff comparison
    depends on — a naive value would raise there instead of answering, so it
    is pinned here rather than assumed.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
            connect_timeout=10,
            read_timeout=60,
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
            try:
                response = self.client.get_object(Bucket=self.bucket, Key=key)
                return response["Body"].read()
            except ClientError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    raise FileNotFoundError(key) from e
                raise

        return await asyncio.to_thread(_get)

    async def copy(self, src_key: str, dst_key: str) -> None:
        """Server-side copy within the bucket.

        Uses the managed ``client.copy`` transfer rather than ``copy_object``:
        the single-request CopyObject API caps at 5 GB, and presigned uploads
        exist precisely for objects that can exceed it. The managed API falls
        back to multipart copy above that ceiling on its own.
        """

        def _copy() -> None:
            try:
                self.client.copy(
                    CopySource={"Bucket": self.bucket, "Key": src_key},
                    Bucket=self.bucket,
                    Key=dst_key,
                )
            except ClientError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    raise FileNotFoundError(src_key) from e
                raise

        await asyncio.to_thread(_copy)

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        """Read at most ``length`` bytes from byte offset ``start``."""

        def _get_range() -> bytes:
            try:
                response = self.client.get_object(
                    Bucket=self.bucket,
                    Key=key,
                    Range=f"bytes={start}-{start + length - 1}",
                )
                return response["Body"].read()
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                if code in ("404", "NoSuchKey"):
                    raise FileNotFoundError(key) from e
                # A window that starts at or past the end of the object is an
                # empty read, not an error — matches local/POSIX seek+read.
                if code in ("416", "InvalidRange", "RequestedRangeNotSatisfiable"):
                    return b""
                raise

        return await asyncio.to_thread(_get_range)

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        """Stream the whole object from ONE ``get_object``, in 1 MiB chunks.

        fix(#1540 review P1): this used to raise ``NotImplementedError`` on the
        grounds that the s3 backend always redirects. That stopped being true
        when the COG download route gained the one case it cannot delegate to
        the bucket — a resumed range whose ``If-Range`` no longer matches, which
        RFC 9110 section 13.1.5 says must be answered with the complete
        representation, and which a presigned URL cannot answer because the
        bucket does not evaluate the precondition.

        The first version of that fallback streamed through
        ``_iter_storage_range``, which issues a separate ranged ``get_object``
        per chunk: 5,120 object-store requests for a 5 GiB COG, selectable by
        any caller willing to send a stale validator, and counted by the rate
        limiter as one request. One ``get_object``, read in chunks off the
        socket, costs the same as any other full download.

        Chunked rather than ``.read()`` for the reason the local provider gives:
        a multi-GB COG must never be materialized as a single ``bytes``. The
        body is closed in a ``finally`` so a client that disconnects mid-stream
        releases its connection back to the pool instead of leaking it.
        """

        def _open():
            try:
                return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
            except ClientError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    raise FileNotFoundError(key) from e
                raise

        body = await asyncio.to_thread(_open)
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, _STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def get_range_stream(
        self, key: str, start: int, length: int
    ) -> AsyncIterator[bytes]:
        """Stream a byte window from ONE ranged ``get_object``.

        fix(#1540 review P1): this is the method whose absence produced the
        defect twice. Serving a range by calling ``get_range`` per 1 MiB chunk
        issues a separate ``GetObject`` per chunk, so an ordinary
        ``Range: bytes=0-`` against a 5 GiB COG became 5,120 serial object-store
        requests — one API request by the rate limiter's count, thousands by the
        bill's. The window is requested once here and the body is read off the
        socket in chunks, which is what a range request should cost.

        A window starting at or past the end is an empty stream rather than an
        error, matching ``get_range`` and local/POSIX seek-then-read: the caller
        has already decided what a zero-length window means.
        """

        def _open():
            try:
                return self.client.get_object(
                    Bucket=self.bucket,
                    Key=key,
                    Range=f"bytes={start}-{start + length - 1}",
                )["Body"]
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                if code in ("404", "NoSuchKey"):
                    raise FileNotFoundError(key) from e
                if code in ("416", "InvalidRange", "RequestedRangeNotSatisfiable"):
                    return None
                raise

        body = await asyncio.to_thread(_open)
        if body is None:
            return
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, _STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

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

    async def size(self, key: str) -> int:
        """Return object size in bytes via head_object."""

        def _size() -> int:
            try:
                response = self.client.head_object(Bucket=self.bucket, Key=key)
                return int(response["ContentLength"])
            except ClientError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    raise FileNotFoundError(key) from e
                raise

        return await asyncio.to_thread(_size)

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

    async def iter_object_pages(
        self, prefix: str, *, start_after: str | None = None
    ) -> AsyncIterator[list[StoredObject]]:
        """Yield ListObjectsV2 pages, each entry with its last-modified time.

        One request per page rather than a drain-then-return: a consumer that
        stops after the first page never issues the second, so a caller with a
        bounded work budget pays for a bounded number of round trips against an
        arbitrarily large prefix (fix(#1249) review r1).

        ``start_after`` becomes S3's own ``StartAfter``, so a resumed walk skips
        the earlier keys server-side rather than fetching and discarding them
        (fix(#1249) review r2). It applies to the FIRST request only —
        ListObjectsV2 ignores it once a ``ContinuationToken`` is present, and
        sending both would only invite a reader to think otherwise.
        """
        params: dict = {"Bucket": self.bucket, "Prefix": prefix}
        if start_after is not None:
            params["StartAfter"] = start_after
        while True:
            response = await asyncio.to_thread(self.client.list_objects_v2, **params)
            yield [
                StoredObject(
                    key=obj["Key"],
                    last_modified=_as_utc(obj["LastModified"]),
                )
                for obj in response.get("Contents", [])
            ]
            if not response.get("IsTruncated"):
                return
            params.pop("StartAfter", None)
            params["ContinuationToken"] = response["NextContinuationToken"]

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
        """Generate a presigned PUT URL for direct upload.

        fix(#1234): clamped to the job lifetime, same as the part URLs. The
        3600 default happens to match today's default timeout, which is
        exactly why it needed the clamp — configure the timeout lower and the
        one-shot PUT URL silently outlives the job it belongs to.
        """
        from app.core.config import settings

        expiration = min(expiration, settings.pending_job_timeout_seconds)
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
        """Generate a presigned URL for uploading a single part.

        fix(#1234): clamped to the job lifetime. A part URL that outlives the
        job it belongs to is a URL the client can still use against a row the
        pending sweep has already failed — the server was offering 7200s
        against a 3600s lifetime.
        """
        from app.core.config import settings

        expiration = min(expiration, settings.pending_job_timeout_seconds)
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
