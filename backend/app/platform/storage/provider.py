from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Protocol


@dataclass(frozen=True)
class StoredObject:
    """One object as the provider reports it right now.

    feat(#1249): the staging-orphan reconciliation needs "and how old is it"
    alongside "does it exist". ``last_modified`` is timezone-aware UTC on
    every provider — a naive value would make the caller's cutoff comparison
    raise rather than answer, so each implementation normalizes before
    returning.
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

        For checks that only inspect a bounded window of a large object (the
        presigned-completion content check reads a header and, for Parquet,
        the trailing magic) so the whole object never has to be downloaded.

        ``length`` must be positive. Returns fewer bytes than requested when
        the window runs past the end of the object. Raises FileNotFoundError
        if the key does not exist (BA-24).
        """
        ...

    def get_stream(self, key: str) -> AsyncIterator[bytes]:
        """Stream key bytes as an async iterator.

        For large files (e.g. COGs) where loading the full payload into memory
        is prohibitive. Implementations should yield in fixed-size chunks
        (typically 1 MiB) and ensure the underlying file handle is closed
        even on consumer abort. Raises FileNotFoundError if key does not exist.
        """
        ...

    def get_range_stream(
        self, key: str, start: int, length: int
    ) -> AsyncIterator[bytes]:
        """Stream a bounded window as ``get_range``, in chunks as ``get_stream``.

        fix(#1540 review P1): the COG download route needs both properties at
        once and had neither method that gives them. ``get_range`` returns
        ``bytes``, so a multi-GB range would be materialized whole; calling it
        in a loop instead — which is what the route did — turns ONE range
        request into a separate object-store request per chunk. A client asking
        for ``Range: bytes=0-`` on a 5 GiB COG cost 5,120 of them, serially,
        while the per-request rate limiter counted a single API call.

        **Implementations must issue one provider read for the whole window**
        and chunk the response as it arrives. That is what makes a range
        request cost what a range request should cost, and it is the property
        the route depends on rather than a suggestion.

        ``length`` must be positive. The stream ends early if the object is
        shorter than the window — a truncated response against a declared
        Content-Length is a transfer error every HTTP client reports, which is
        the loud failure; padding to length would be the quiet corrupt one.
        Raises FileNotFoundError if the key does not exist (BA-24).
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

        feat(#1249): ``list`` answers which keys exist; this also answers how
        old each one is, which is what tells an abandoned staging object from
        one whose upload landed a second ago.

        Pages rather than one list, and for the same reason ``get_stream``
        exists (fix(#1249) review r1): a caller that can act on a bounded
        amount of work must not have to materialize an unbounded prefix first.
        A consumer that stops early stops the provider's paging with it.

        ``start_after`` resumes a walk: only keys strictly greater than it are
        yielded, in ascending key order, so a caller with a per-pass budget can
        continue where the last one stopped instead of re-reading the front of
        the prefix forever (fix(#1249) review r2). S3 pushes it down as
        ``StartAfter``; the other backends filter, which costs them nothing
        that matters — neither can hold a presigned staging object, since
        presigned uploads refuse anything but the S3 backend at request time.

        A COMPLETE key is a valid ``prefix`` and is how a caller re-reads one
        object's timestamp immediately before acting on it. Implementations
        yield every entry whose key STARTS WITH ``prefix`` — matching ``list``
        — so a caller that means one exact object must filter for
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

        Implementations MUST clamp ``expiration`` to
        ``settings.pending_job_timeout_seconds`` (fix(#1234)), as for part URLs
        below: a URL that outlives its job is usable against a row the pending
        sweep has already failed. Raises NotImplementedError for local storage.
        """
        ...

    def generate_presigned_get_url(
        self,
        key: str,
        expiration: int = 3600,
    ) -> str:
        """Generate a presigned GET URL for download. Raises NotImplementedError for local storage."""
        ...

    def initiate_multipart_upload(
        self,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Initiate a multipart upload, returns upload_id. Raises NotImplementedError for local storage."""
        ...

    def generate_presigned_part_url(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expiration: int = 7200,
    ) -> str:
        """Generate a presigned URL for uploading a single part.

        Implementations MUST clamp ``expiration`` to
        ``settings.pending_job_timeout_seconds`` (fix(#1234)): a part URL that
        outlives its job is usable against a row the pending sweep has already
        failed. Raises NotImplementedError for local storage.
        """
        ...

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        # Use builtins.list rather than bare `list` because this class
        # defines a `list(...)` method below, and mypy treats the method
        # name as shadowing the builtin inside annotations.
        parts: "builtins.list[dict]",
    ) -> None:
        """Complete a multipart upload with the list of {ETag, PartNumber} dicts. Raises NotImplementedError for local storage."""
        ...

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """Abort an in-progress multipart upload. Raises NotImplementedError for local storage."""
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
        # CR-04 (Phase 1210): pass the account key as credential so that
        # account_url + key auth works. When connection_string is present it
        # takes precedence inside AzureBlobStorageProvider; the key is only
        # used when account_url is the sole auth parameter.
        # reveal() is called here — the raw value exists only in this local
        # variable and is passed immediately to the SDK; it is never logged.
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
