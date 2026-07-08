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
#   (a SAS token string, a storage account key, or an azure-identity credential).

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
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient


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
                # fix(BA-24): normalize missing-object to FileNotFoundError across providers.
                raise FileNotFoundError(key) from e

        return await asyncio.to_thread(_get)

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
                # fix(BA-24): normalize missing-object to FileNotFoundError across providers.
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
