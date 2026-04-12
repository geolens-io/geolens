from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO


class LocalStorageProvider:
    """Storage provider wrapping local filesystem operations under a base directory."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, data: BinaryIO | bytes) -> str:
        """Store data at key. Returns the absolute path as a string."""
        dest = self.base_dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            dest.write_bytes(data)
        else:
            with open(dest, "wb") as f:
                while chunk := data.read(8192):
                    f.write(chunk)
        return str(dest)

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key."""
        return (self.base_dir / key).read_bytes()

    async def get_to_file(self, key: str, dest: Path) -> Path:
        """Copy file to dest. If src == dest, return as-is."""
        src = self.base_dir / key
        if src != dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        return dest if src != dest else src

    async def delete(self, key: str) -> None:
        """Delete a key. No error if missing."""
        (self.base_dir / key).unlink(missing_ok=True)

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        return (self.base_dir / key).exists()

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix, relative to base_dir."""
        if prefix.endswith("/"):
            # Directory prefix: list all files recursively under it
            search_dir = self.base_dir / prefix
            if not search_dir.exists():
                return []
            return [
                str(p.relative_to(self.base_dir))
                for p in search_dir.rglob("*")
                if p.is_file()
            ]
        # File prefix: glob in the parent directory
        prefix_path = self.base_dir / prefix
        parent = prefix_path.parent
        if not parent.exists():
            return []
        pattern = prefix_path.name + "*"
        return [
            str(p.relative_to(self.base_dir))
            for p in parent.glob(pattern)
            if p.is_file()
        ]

    async def health_check(self) -> None:
        """Verify the storage directory exists."""
        if not self.base_dir.exists():
            raise RuntimeError(f"Storage directory does not exist: {self.base_dir}")

    # --- Presigned URL stubs (not supported for local storage) ---

    def generate_presigned_put_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expiration: int = 3600,
    ) -> str:
        raise NotImplementedError("Presigned URLs are only supported with S3 storage")

    def generate_presigned_get_url(
        self,
        key: str,
        expiration: int = 3600,
    ) -> str:
        raise NotImplementedError("Presigned URLs are only supported with S3 storage")

    def initiate_multipart_upload(
        self,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        raise NotImplementedError("Presigned URLs are only supported with S3 storage")

    def generate_presigned_part_url(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expiration: int = 7200,
    ) -> str:
        raise NotImplementedError("Presigned URLs are only supported with S3 storage")

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: list[dict],
    ) -> None:
        raise NotImplementedError("Presigned URLs are only supported with S3 storage")

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        raise NotImplementedError("Presigned URLs are only supported with S3 storage")
