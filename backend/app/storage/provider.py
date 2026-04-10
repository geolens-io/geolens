from __future__ import annotations

import builtins
from pathlib import Path
from typing import BinaryIO, Protocol


class StorageProvider(Protocol):
    """Provider-agnostic file storage interface."""

    async def put(self, key: str, data: BinaryIO | bytes) -> str:
        """Store data at key. Returns the storage URI (path or s3://...)."""
        ...

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key."""
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

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix."""
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
        """Generate a presigned PUT URL for direct upload. Raises NotImplementedError for local storage."""
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
        """Generate a presigned URL for uploading a single part. Raises NotImplementedError for local storage."""
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
    from app.config import settings

    if settings.storage_provider == "s3":
        from app.storage.s3 import S3StorageProvider

        if not settings.s3_bucket:
            raise RuntimeError(
                "storage_provider='s3' but s3_bucket is not configured"
            )
        _storage = S3StorageProvider(
            bucket=settings.s3_bucket,
            endpoint=settings.s3_endpoint,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            allow_http=settings.s3_allow_http,
            addressing_style=settings.s3_addressing_style,
        )
    else:
        from app.storage.local import LocalStorageProvider

        _storage = LocalStorageProvider(base_dir=settings.upload_staging_dir)


def get_storage() -> StorageProvider:
    """Get the configured storage provider singleton."""
    if _storage is None:
        raise RuntimeError(
            "Storage provider not initialized. Call init_storage() first."
        )
    return _storage
