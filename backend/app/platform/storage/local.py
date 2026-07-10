from __future__ import annotations

import asyncio
import os
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

    def _resolve_contained(self, key: str) -> Path:
        """Return the resolved path for *key*, asserting it stays inside base_dir.

        Rejects:
        - Absolute keys (``/etc/passwd``).
        - Keys containing a null byte (``foo\\x00bar``).
        - Path-traversal sequences that escape base_dir (``../../etc/passwd``).

        Raises ``ValueError`` for any rejected key.  The caller should map this
        to a 400/403 HTTP response; the storage layer never reaches the
        filesystem for disallowed keys.

        SEC-026: called at the top of every IO method so none is a bypass.
        """
        if "\x00" in key:
            raise ValueError(f"Storage key contains a null byte: {key!r}")
        if os.path.isabs(key):
            raise ValueError(
                f"Storage key must be relative, got absolute path: {key!r}"
            )
        candidate = (self.base_dir / key).resolve()
        resolved_base = self.base_dir.resolve()
        if candidate != resolved_base and not candidate.is_relative_to(resolved_base):
            raise ValueError(
                f"Storage key {key!r} escapes base directory "
                f"({resolved_base}): resolved to {candidate}"
            )
        return candidate

    async def put(self, key: str, data: BinaryIO | bytes) -> str:
        """Store data at key. Returns the absolute path as a string.

        fix(#435): a file-like `data` stays file-like. This used to call `data.read()`
        on the event-loop thread before the handoff, materializing a whole COG, VRT,
        or archived original as one `bytes` object — the raster/VRT/original ingest
        paths all pass open file handles, and those artifacts can exceed the 2 GB
        production container limit. The copy now streams in 1 MiB chunks inside the
        worker thread, so resident memory is bounded and the loop never blocks.
        """
        dest = self._resolve_contained(key)

        def _put() -> str:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                dest.write_bytes(data)
            else:
                with open(dest, "wb") as out:
                    shutil.copyfileobj(data, out, _STREAM_CHUNK_BYTES)
            return str(dest)

        return await asyncio.to_thread(_put)

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key."""
        path = self._resolve_contained(key)
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
        path = self._resolve_contained(key)
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
        src = self._resolve_contained(key)
        if src == dest:
            return src

        def _copy() -> Path:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return dest

        return await asyncio.to_thread(_copy)

    async def delete(self, key: str) -> None:
        """Delete a key. No error if missing."""
        path = self._resolve_contained(key)
        await asyncio.to_thread(path.unlink, True)  # missing_ok=True

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        path = self._resolve_contained(key)
        return await asyncio.to_thread(path.exists)

    async def size(self, key: str) -> int:
        """Return file size in bytes."""
        path = self._resolve_contained(key)
        return await asyncio.to_thread(lambda: path.stat().st_size)

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
