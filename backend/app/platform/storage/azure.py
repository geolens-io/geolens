"""Azure Blob Storage backend.

Wraps the synchronous azure-storage-blob SDK in `asyncio.to_thread` so callers
can await uploads/downloads without blocking the event loop. Uses the native
Azure SDK, not a MinIO S3 gateway shim (STOR-01).

Auth: connection_string, or account_url + credential (SAS token or account
key). fix(#836): azure-identity credentials are not supported.

Key prefixes (tenants/{tenant_id}/) and VSI paths (vsis3/vsiaz) are built by
titiler_url.resolve_open_path (STOR-02); this class stores keys verbatim.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

from app.core.async_io import run_in_thread_draining
from app.platform.storage.provider import StoredObject


def _as_utc(value: datetime) -> datetime:
    """Normalize a timestamp to timezone-aware UTC (feat #1249).

    Azure already returns aware datetimes; this pins the ``StoredObject``
    contract that reconciliation's cutoff comparison depends on.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AzureBlobStorageProvider:
    """Storage provider wrapping azure-storage-blob via asyncio.to_thread.

    Key prefixes are built by resolve_open_path, not here.
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
        """Store data at key. Returns az://container/key URI.

        fix(#1532): drained on cancellation — a bare ``to_thread`` would return
        while the upload kept running, racing cleanup (undo-delete, closed
        source handle, orphaned staged blocks).
        """

        def _put() -> None:
            blob = self._client.get_blob_client(container=self.container, blob=key)
            blob.upload_blob(data, overwrite=True)

        await run_in_thread_draining(_put)
        return f"az://{self.container}/{key}"

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key."""

        def _get() -> bytes:
            blob = self._client.get_blob_client(container=self.container, blob=key)
            try:
                downloader = blob.download_blob()
                return downloader.readall()
            except ResourceNotFoundError as e:
                # fix(#430): normalize missing-object to FileNotFoundError.
                raise FileNotFoundError(key) from e

        return await asyncio.to_thread(_get)

    async def copy(self, src_key: str, dst_key: str) -> None:
        """Service-side copy within the container.

        ``requires_sync`` finishes the copy before returning so a caller that
        reads the destination immediately sees the bytes. Azure bounds the
        source size for a synchronous copy; untested against a live account
        since no current caller reaches this path.
        """

        def _copy() -> None:
            source = self._client.get_blob_client(
                container=self.container, blob=src_key
            )
            dest = self._client.get_blob_client(container=self.container, blob=dst_key)
            try:
                dest.start_copy_from_url(source.url, requires_sync=True)
            except ResourceNotFoundError as e:
                # fix(#430): normalize missing-object to FileNotFoundError.
                raise FileNotFoundError(src_key) from e

        await asyncio.to_thread(_copy)

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        """Read at most ``length`` bytes from byte offset ``start``."""

        def _get_range() -> bytes:
            blob = self._client.get_blob_client(container=self.container, blob=key)
            try:
                return blob.download_blob(offset=start, length=length).readall()
            except ResourceNotFoundError as e:
                # fix(#430): normalize missing-object to FileNotFoundError.
                raise FileNotFoundError(key) from e

        return await asyncio.to_thread(_get_range)

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        """Stream a whole blob from ONE ``download_blob`` call.

        fix(#1532): this method IS reachable (managed assets take the LOCAL
        branch, whose GET calls this) — never reintroduce a NotImplementedError
        here. Raising mid-iteration would truncate an in-flight
        ``StreamingResponse`` instead of failing cleanly.
        """
        blob = self._client.get_blob_client(container=self.container, blob=key)

        def _open():
            try:
                return blob.download_blob()
            except ResourceNotFoundError as e:
                # fix(#430): normalize missing-object to FileNotFoundError.
                raise FileNotFoundError(key) from e

        downloader = await asyncio.to_thread(_open)
        chunks = await asyncio.to_thread(downloader.chunks)
        iterator = iter(chunks)
        sentinel = object()
        while True:
            chunk = await asyncio.to_thread(next, iterator, sentinel)
            if chunk is sentinel or not chunk:
                return
            yield chunk

    async def get_range_stream(
        self, key: str, start: int, length: int
    ) -> AsyncIterator[bytes]:
        """Stream a byte window from ONE ``download_blob`` call.

        fix(#1540): avoids the per-1-MiB-chunk amplification ``get_range``
        looping would cause. One call for the window; the SDK may still split
        a window past ``max_single_get_size`` into several requests, but that
        is its own transfer strategy, not a loop this code writes.
        """
        blob = self._client.get_blob_client(container=self.container, blob=key)

        def _open():
            try:
                return blob.download_blob(offset=start, length=length)
            except ResourceNotFoundError as e:
                # fix(#430): normalize missing-object to FileNotFoundError.
                raise FileNotFoundError(key) from e
            except HttpResponseError as e:
                # Azure raises InvalidRange past EOF where S3/local read empty
                # (measured on Azurite 3.35.0); normalize to the local contract.
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
                # fix(#430): normalize missing-object to FileNotFoundError.
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

        ``by_page()`` (fix(#1249)) so a consumer that stops early stops the
        service round trips with it. ``start_after`` is filtered client-side:
        Azure's flat listing takes a name prefix, not a start marker, and its
        continuation tokens can't be reconstructed as a key by a later pass.
        Listings are name-ordered, so this yields the same sequence as S3's
        ``StartAfter``; only the skipped pages still cross the wire.
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
                    # feat(#1249): skip undatable blobs here so the caller
                    # never has to treat one as "old enough to delete".
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

    # Azure uses SAS tokens, not presigned PUT/GET URLs; these methods raise
    # NotImplementedError naming the SAS equivalent, mirroring local.py.

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
