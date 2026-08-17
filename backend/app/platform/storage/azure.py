"""Azure Blob Storage backend.

Wraps the synchronous azure-storage-blob SDK in `asyncio.to_thread` so callers
can await uploads/downloads without blocking the event loop.

Uses the native Azure SDK — NOT a MinIO S3 gateway shim. This is the canonical
implementation for STOR-01 (Phase 1210).

# Authentication
# --------------
# - Azurite (local emulator): pass the well-known dev connection_string.
# - Live Azure via connection string: pass connection_string from config.
# - Live Azure via account URL + credential: pass account_url and credential
#   (a SAS token string or a storage account key). fix(#836): azure-identity
#   credentials are NOT supported — the dependency was removed as unused;
#   managed identity would need it reintroduced plus a typed credential path.

# Key prefix convention
# ---------------------
# Tenant-aware key prefixes (tenants/{tenant_id}/) are constructed by the
# resolve_open_path() seam in titiler_url.py. This class receives the final key
# and stores it verbatim — no prefix logic here.

# VSI paths
# ---------
# This class never constructs GDAL VSI prefixes (vsis3 / vsiaz).
# All VSI prefix construction is the exclusive responsibility of
# app.platform.storage.titiler_url.resolve_open_path (STOR-02 seam).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

from app.platform.storage.provider import StoredObject


def _as_utc(value: datetime) -> datetime:
    """Normalize a provider timestamp to timezone-aware UTC (feat #1249).

    Azure returns aware datetimes; the normalization is pinned here because
    the ``StoredObject`` contract — not the SDK's current behaviour — is what
    the reconciliation's cutoff comparison relies on.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AzureBlobStorageProvider:
    """Storage provider wrapping azure-storage-blob via asyncio.to_thread.

    Uses native azure-storage-blob SDK — NOT an S3-compatible gateway.
    Tenant key prefixes follow the tenants/{tenant_id}/ convention (Phase 1209
    carry-forward); prefixes are built by resolve_open_path, not here.
    """

    def __init__(
        self,
        container: str,
        connection_string: str | None = None,
        account_url: str | None = None,
        credential: str | None = None,
    ) -> None:
        self.container = container
        if connection_string:
            self._client = BlobServiceClient.from_connection_string(connection_string)
        else:
            self._client = BlobServiceClient(
                account_url=account_url, credential=credential
            )

    async def put(self, key: str, data: BinaryIO | bytes) -> str:
        """Store data at key. Returns az://container/key URI."""

        def _put() -> None:
            blob = self._client.get_blob_client(container=self.container, blob=key)
            blob.upload_blob(data, overwrite=True)

        await asyncio.to_thread(_put)
        return f"az://{self.container}/{key}"

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key."""

        def _get() -> bytes:
            blob = self._client.get_blob_client(container=self.container, blob=key)
            try:
                downloader = blob.download_blob()
                return downloader.readall()
            except ResourceNotFoundError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                raise FileNotFoundError(key) from e

        return await asyncio.to_thread(_get)

    async def copy(self, src_key: str, dst_key: str) -> None:
        """Service-side copy within the container.

        ``requires_sync`` makes the service finish the copy before returning,
        so callers that read the destination immediately see the bytes. Azure
        bounds a synchronous copy's source size, and same-account URL copies
        depend on the destination credential authorizing the source — neither
        is exercised today, because presigned uploads (the only caller) refuse
        anything but the S3 backend at request time. This exists for protocol
        completeness; verify it against a live account before relying on it.
        """

        def _copy() -> None:
            source = self._client.get_blob_client(
                container=self.container, blob=src_key
            )
            dest = self._client.get_blob_client(container=self.container, blob=dst_key)
            try:
                dest.start_copy_from_url(source.url, requires_sync=True)
            except ResourceNotFoundError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                raise FileNotFoundError(src_key) from e

        await asyncio.to_thread(_copy)

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        """Read at most ``length`` bytes from byte offset ``start``."""

        def _get_range() -> bytes:
            blob = self._client.get_blob_client(container=self.container, blob=key)
            try:
                return blob.download_blob(offset=start, length=length).readall()
            except ResourceNotFoundError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                raise FileNotFoundError(key) from e

        return await asyncio.to_thread(_get_range)

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        """Azure streaming is served via SAS redirect; this method should never be reached.

        The router returns a SAS-signed redirect for the azure storage backend,
        so this method is unreachable in the current code path. Defining it
        explicitly satisfies the StorageProvider Protocol and surfaces a clear
        error if a future refactor accidentally invokes it on Azure.
        """
        raise NotImplementedError(
            "Azure streaming is served via SAS redirect; this method should "
            "never be reached."
        )
        yield b""  # unreachable, satisfies AsyncIterator return type

    async def get_range_stream(
        self, key: str, start: int, length: int
    ) -> AsyncIterator[bytes]:
        """Stream a byte window from ONE ``download_blob`` call.

        fix(#1540 review P1): the same amplification S3 had. Serving a range by
        calling ``get_range`` per 1 MiB chunk meant a separate download call per
        chunk, and an Azure deployment reaches this code by the ordinary path —
        managed rasters carry ``storage_backend="local"``, so their range
        requests are served here rather than redirected.

        One ``download_blob(offset, length)`` for the window, chunked as it
        arrives. Precisely: one CALL, where S3's is one REQUEST. The Azure SDK
        satisfies a download larger than its ``max_single_get_size`` with its
        own internal chunking, so a very large window is still several requests
        at the SDK's chunk size rather than one — bounded by the SDK's transfer
        strategy instead of by a loop this code writes at 1 MiB.
        """
        blob = self._client.get_blob_client(container=self.container, blob=key)

        def _open():
            try:
                return blob.download_blob(offset=start, length=length)
            except ResourceNotFoundError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                raise FileNotFoundError(key) from e
            except HttpResponseError as e:
                # A window at or past the end: Azure raises where S3 answers
                # 416 and a local seek-then-read simply reads nothing. The
                # contract is the local one, so it is normalized here —
                # MEASURED against Azurite 3.35.0, which answers this exact
                # request with ErrorCode InvalidRange while the other two
                # providers return empty.
                if getattr(e, "error_code", None) == "InvalidRange":
                    return None
                raise

        downloader = await asyncio.to_thread(_open)
        if downloader is None:
            return
        chunks = await asyncio.to_thread(downloader.chunks)
        iterator = iter(chunks)
        sentinel = object()
        while True:
            chunk = await asyncio.to_thread(next, iterator, sentinel)
            if chunk is sentinel or not chunk:
                return
            yield chunk

    async def get_to_file(self, key: str, dest: Path) -> Path:
        """Download key to a local file path. Creates parent dirs."""
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _get_to_file() -> None:
            blob = self._client.get_blob_client(container=self.container, blob=key)
            with dest.open("wb") as fh:
                downloader = blob.download_blob()
                downloader.readinto(fh)

        await asyncio.to_thread(_get_to_file)
        return dest

    async def delete(self, key: str) -> None:
        """Delete a key. No-op (no raise) on a missing key."""

        def _delete() -> None:
            try:
                blob = self._client.get_blob_client(container=self.container, blob=key)
                blob.delete_blob()
            except ResourceNotFoundError:
                pass  # missing-key is a no-op, matching the Protocol contract

        await asyncio.to_thread(_delete)

    async def exists(self, key: str) -> bool:
        """Check if a key exists via get_blob_properties."""

        def _exists() -> bool:
            try:
                blob = self._client.get_blob_client(container=self.container, blob=key)
                blob.get_blob_properties()
                return True
            except ResourceNotFoundError:
                return False

        return await asyncio.to_thread(_exists)

    async def size(self, key: str) -> int:
        """Return blob size in bytes via get_blob_properties."""

        def _size() -> int:
            blob = self._client.get_blob_client(container=self.container, blob=key)
            try:
                props = blob.get_blob_properties()
            except ResourceNotFoundError as e:
                # fix(#430 BA-24): normalize missing-object to FileNotFoundError across providers.
                raise FileNotFoundError(key) from e
            size = getattr(props, "size", None)
            if size is None:
                try:
                    size = props["size"]
                except (KeyError, TypeError):
                    size = getattr(props, "content_length", None)
            return int(size)

        return await asyncio.to_thread(_size)

    async def list(self, prefix: str) -> list[str]:
        """List blob names under a prefix."""

        def _list() -> list[str]:
            container_client = self._client.get_container_client(self.container)
            return [
                blob.name
                for blob in container_client.list_blobs(name_starts_with=prefix)
            ]

        return await asyncio.to_thread(_list)

    async def iter_object_pages(
        self, prefix: str, *, start_after: str | None = None
    ) -> AsyncIterator[list[StoredObject]]:
        """Yield blob pages under a prefix, each entry with its last-modified.

        ``by_page()`` rather than the flat iterator so a consumer that stops
        early stops the service round trips with it (fix(#1249) review r1).

        ``start_after`` is filtered client-side: Azure's flat listing takes a
        name PREFIX, not a start marker, and its own continuation tokens are
        service-issued handles rather than a key a later pass could reconstruct
        (fix(#1249) review r2). Blob listings are name-ordered, so the filter
        yields the same sequence S3's ``StartAfter`` does; only the skipped
        pages still cross the wire. Nothing this backend serves makes that
        matter — presigned uploads refuse anything but S3 at request time, so
        an Azure container holds no `staging/` objects to walk.
        """
        container_client = self._client.get_container_client(self.container)
        pages = container_client.list_blobs(name_starts_with=prefix).by_page()

        def _next_page() -> list | None:
            try:
                return list(next(pages))
            except StopIteration:
                return None

        while True:
            blobs = await asyncio.to_thread(_next_page)
            if blobs is None:
                return
            page: list[StoredObject] = []
            for blob in blobs:
                if start_after is not None and blob.name <= start_after:
                    continue
                last_modified = getattr(blob, "last_modified", None)
                if last_modified is None:
                    # feat(#1249): a blob the SDK cannot date cannot be aged,
                    # and an undatable entry must never read as "old enough to
                    # delete". Dropping it here keeps that decision out of the
                    # caller, which only ever sees datable objects.
                    continue
                page.append(
                    StoredObject(
                        key=blob.name,
                        last_modified=_as_utc(last_modified),
                    )
                )
            yield page

    async def health_check(self) -> None:
        """Verify the Azure container is reachable via get_container_properties."""

        def _hc() -> None:
            self._client.get_container_client(self.container).get_container_properties()

        await asyncio.to_thread(_hc)

    # --- Presigned / SAS URL methods ---
    # Azure uses SAS tokens instead of presigned PUT/GET URLs. These methods
    # raise NotImplementedError with SAS noted as the Azure equivalent,
    # mirroring local.py for unsupported ops. Method signatures match the
    # StorageProvider Protocol so the Protocol is fully satisfied.

    def generate_presigned_put_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expiration: int = 3600,
    ) -> str:
        """Azure uses SAS tokens, not presigned PUT URLs."""
        raise NotImplementedError(
            "Azure uses SAS tokens for direct upload. "
            "Use azure.storage.blob.generate_blob_sas() instead."
        )

    def generate_presigned_get_url(
        self,
        key: str,
        expiration: int = 3600,
    ) -> str:
        """Azure uses SAS tokens, not presigned GET URLs."""
        raise NotImplementedError(
            "Azure uses SAS tokens for download. "
            "Use azure.storage.blob.generate_blob_sas() instead."
        )

    def initiate_multipart_upload(
        self,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Azure uses block blobs (commit_block_list), not S3-style multipart."""
        raise NotImplementedError(
            "Azure uses block blobs instead of S3-style multipart uploads. "
            "Use BlobClient.stage_block() + commit_block_list() instead."
        )

    def generate_presigned_part_url(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expiration: int = 7200,
    ) -> str:
        """Azure uses block blobs (SAS), not S3-style presigned part URLs."""
        raise NotImplementedError(
            "Azure uses block blobs instead of S3-style multipart uploads."
        )

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: list[dict],
    ) -> None:
        """Azure uses block blobs (commit_block_list), not S3-style multipart."""
        raise NotImplementedError(
            "Azure uses block blobs instead of S3-style multipart uploads. "
            "Use BlobClient.commit_block_list() instead."
        )

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """Azure uses block blobs, not S3-style multipart uploads."""
        raise NotImplementedError(
            "Azure uses block blobs instead of S3-style multipart uploads."
        )
