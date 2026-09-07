from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Protocol


@dataclass(frozen=True)
class StoredObject:
    """One object as the provider reports it right now.

    feat(#1249): ``last_modified`` is timezone-aware UTC on every provider —
    a naive value would make the caller's cutoff comparison raise instead of
    answer.
    """

    key: str
    last_modified: datetime


class StorageProvider(Protocol):
    """Provider-agnostic file storage interface."""

    async def put(self, key: str, data: BinaryIO | bytes) -> str:
        """Store data at key. Returns the storage URI (path or s3://...)."""
        ...

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key.

        Raises FileNotFoundError if the key does not exist (BA-24).
        """
        ...

    async def copy(self, src_key: str, dst_key: str) -> None:
        """Copy an object within this backend, overwriting ``dst_key``.

        Server-side wherever the provider supports it — the bytes must not
        round-trip through this process, because callers use this to snapshot
        multi-GB uploads. Raises FileNotFoundError if ``src_key`` does not
        exist (BA-24).
        """
        ...

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        """Retrieve at most ``length`` bytes starting at byte offset ``start``.

        For checking a bounded window of a large object (e.g. a header, or
        Parquet's trailing magic) without downloading it whole. ``length``
        must be positive; returns fewer bytes if the window runs past the
        object's end. Raises FileNotFoundError if the key does not exist
        (BA-24).
        """
        ...

    def get_stream(self, key: str) -> AsyncIterator[bytes]:
        """Stream key bytes as an async iterator.

        For large files (e.g. COGs) where loading the full payload into
        memory is prohibitive. Implementations must yield fixed-size chunks
        and close the underlying handle even on consumer abort. Raises
        FileNotFoundError if the key does not exist.
        """
        ...

    def get_range_stream(
        self, key: str, start: int, length: int
    ) -> AsyncIterator[bytes]:
        """Stream a bounded window as ``get_range``, in chunks as ``get_stream``.

        fix(#1540): implementations MUST issue ONE provider read for the
        whole window and chunk the response as it arrives — looping
        ``get_range`` per chunk turns one range request into one request per
        chunk, invisible to the per-request rate limiter.

        ``length`` must be positive. The stream ends early if the object is
        shorter than the window — never pad to length, which trades a loud
        transfer error for a silent corruption. Raises FileNotFoundError if
        the key does not exist (BA-24).
        """
        ...

    async def get_to_file(self, key: str, dest: Path) -> Path:
        """Download key to a local file path. For ogr2ogr consumption."""
        ...

    async def delete(self, key: str) -> None:
        """Delete a key. No error if key doesn't exist."""
        ...

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        ...

    async def size(self, key: str) -> int:
        """Return the stored object size in bytes.

        Raises FileNotFoundError if the key does not exist (BA-24: all providers
        normalize their native not-found error to FileNotFoundError).
        """
        ...

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix."""
        ...

    def iter_object_pages(
        self, prefix: str, *, start_after: str | None = None
    ) -> AsyncIterator["builtins.list[StoredObject]"]:
        """Yield objects under a prefix one provider page at a time.

        feat(#1249): also answers how old each key is, distinguishing an
        abandoned staging object from one whose upload just landed.

        Paged (fix #1249) so a caller with a bounded per-pass budget never
        has to materialize an unbounded prefix first; stopping early stops
        the provider's paging with it.

        ``start_after`` resumes an ascending walk, yielding only keys
        strictly greater than it, so a caller can continue where the last
        pass stopped instead of re-reading the front of the prefix forever.

        A COMPLETE key is a valid ``prefix``: implementations yield every
        entry whose key STARTS WITH ``prefix`` (matching ``list``), so a
        caller meaning one exact object must filter for
        ``entry.key == key`` rather than trusting the page length.
        """
        ...

    async def health_check(self) -> None:
        """Verify the storage backend is reachable. Raise on failure."""
        ...

    def generate_presigned_put_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expiration: int = 3600,
    ) -> str:
        """Generate a presigned PUT URL for direct upload.

        MUST clamp ``expiration`` to ``settings.pending_job_timeout_seconds``
        (fix #1234), as for part URLs below — a longer-lived URL is usable
        against a row the pending sweep already failed. Raises
        NotImplementedError for local storage.
        """
        ...

    def generate_presigned_get_url(
        self,
        key: str,
        expiration: int = 3600,
    ) -> str:
        """Generate a presigned GET URL for download.

        Raises NotImplementedError for local storage.
        """
        ...

    def initiate_multipart_upload(
        self,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Initiate a multipart upload, returns upload_id.

        Raises NotImplementedError for local storage.
        """
        ...

    def generate_presigned_part_url(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expiration: int = 7200,
    ) -> str:
        """Generate a presigned URL for uploading a single part.

        MUST clamp ``expiration`` to ``settings.pending_job_timeout_seconds``
        (fix #1234), same reason as the put URL above. Raises
        NotImplementedError for local storage.
        """
        ...

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        # builtins.list, not bare `list`: this class defines a `list(...)`
        # method that shadows the builtin name inside annotations.
        parts: "builtins.list[dict]",
    ) -> None:
        """Complete a multipart upload with a list of {ETag, PartNumber} dicts.

        Raises NotImplementedError for local storage.
        """
        ...

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """Abort an in-progress multipart upload.

        Raises NotImplementedError for local storage.
        """
        ...


_storage: StorageProvider | None = None


def init_storage() -> None:
    """Initialize the storage provider singleton. Called once at startup."""
    global _storage
    from app.core.config import reveal, settings

    if settings.storage_provider == "s3":
        from app.platform.storage.s3 import S3StorageProvider

        if not settings.s3_bucket:
            raise RuntimeError("storage_provider='s3' but s3_bucket is not configured")
        _storage = S3StorageProvider(
            bucket=settings.s3_bucket,
            endpoint=settings.s3_endpoint,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=reveal(settings.s3_secret_access_key),
            allow_http=settings.s3_allow_http,
            addressing_style=settings.s3_addressing_style,
        )
    elif settings.storage_provider == "azure":
        from app.platform.storage.azure import AzureBlobStorageProvider

        if not settings.azure_storage_container:
            raise RuntimeError(
                "storage_provider='azure' but azure_storage_container is not configured"
            )
        # CR-04: connection_string takes precedence over account_url+key
        # inside AzureBlobStorageProvider. reveal() here is passed straight
        # to the SDK and never logged.
        _storage = AzureBlobStorageProvider(
            container=settings.azure_storage_container,
            connection_string=reveal(settings.azure_storage_connection_string),
            account_url=settings.azure_storage_account_url,
            credential=reveal(settings.azure_storage_account_key),
        )
    else:
        from app.platform.storage.local import LocalStorageProvider

        _storage = LocalStorageProvider(base_dir=settings.upload_staging_dir)


def get_storage() -> StorageProvider:
    """Get the configured storage provider singleton."""
    if _storage is None:
        raise RuntimeError(
            "Storage provider not initialized. Call init_storage() first."
        )
    return _storage
