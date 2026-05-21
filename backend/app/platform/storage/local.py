from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import AsyncIterator, BinaryIO


# Chunk size for streaming reads (ING-03 / P2-03). 1 MiB is large enough to
# amortize syscall overhead but small enough that worst-case resident memory
# per concurrent download stays bounded.
_STREAM_CHUNK_BYTES = 1024 * 1024  # 1 MiB


class LocalStorageProvider:
    """Storage provider wrapping local filesystem operations under a base directory."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, data: BinaryIO | bytes) -> str:
        """Store data at key. Returns the absolute path as a string."""
        dest = self.base_dir / key
        if not isinstance(data, bytes):
            data = data.read()  # read in async context before thread handoff

        def _put() -> str:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return str(dest)

        return await asyncio.to_thread(_put)

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key."""
        path = self.base_dir / key
        return await asyncio.to_thread(path.read_bytes)

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        """Stream key bytes in 1 MiB chunks (ING-03 / P2-03).

        Avoids the 5 GB resident-memory spike that ``get()`` would cause for
        a large COG download — the full file is never materialized as a
        single ``bytes`` object. Each chunk is read in a worker thread via
        ``asyncio.to_thread`` so the event loop stays responsive.

        The file handle is closed inside a ``finally:`` block so consumer
        abort (e.g. client disconnect mid-stream) does not leak file
        descriptors. Raises ``FileNotFoundError`` upfront if the key is
        missing — matches the ``get()`` exception shape so the router's
        existing ``except FileNotFoundError`` branch can stay unchanged.
        """
        path = self.base_dir / key
        if not await asyncio.to_thread(path.exists):
            raise FileNotFoundError(f"Storage key not found: {key}")

        f = await asyncio.to_thread(open, path, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(f.read, _STREAM_CHUNK_BYTES)
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(f.close)

    async def get_to_file(self, key: str, dest: Path) -> Path:
        """Copy file to dest. If src == dest, return as-is."""
        src = self.base_dir / key
        if src == dest:
            return src

        def _copy() -> Path:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return dest

        return await asyncio.to_thread(_copy)

    async def delete(self, key: str) -> None:
        """Delete a key. No error if missing."""
        path = self.base_dir / key
        await asyncio.to_thread(path.unlink, True)  # missing_ok=True

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        path = self.base_dir / key
        return await asyncio.to_thread(path.exists)

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix, relative to base_dir."""
        base_dir = self.base_dir
        prefix_str = prefix

        def _list() -> list[str]:
            if prefix_str.endswith("/"):
                # Directory prefix: list all files recursively under it
                search_dir = base_dir / prefix_str
                if not search_dir.exists():
                    return []
                return [
                    str(p.relative_to(base_dir))
                    for p in search_dir.rglob("*")
                    if p.is_file()
                ]
            # File prefix: glob in the parent directory
            prefix_path = base_dir / prefix_str
            parent = prefix_path.parent
            if not parent.exists():
                return []
            pattern = prefix_path.name + "*"
            return [
                str(p.relative_to(base_dir))
                for p in parent.glob(pattern)
                if p.is_file()
            ]

        return await asyncio.to_thread(_list)

    async def health_check(self) -> None:
        """Verify the storage directory exists."""
        exists = await asyncio.to_thread(self.base_dir.exists)
        if not exists:
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
