from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from app.core.async_io import run_in_thread_draining
from app.platform.storage.provider import StoredObject


# Chunk size for streaming reads (ING-03 / P2-03). 1 MiB is large enough to
# amortize syscall overhead but small enough that worst-case resident memory
# per concurrent download stays bounded.
_STREAM_CHUNK_BYTES = 1024 * 1024  # 1 MiB

# Page size for ``iter_object_pages``. Matches the ListObjectsV2 default so a
# consumer's per-page budget behaves the same on every backend (feat #1249).
_OBJECT_PAGE_SIZE = 1000


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

        # fix(#435 codex r2/r3/r4): drain the copy thread on cancellation so the caller
        # cannot leave its `with open(...)` block and close `data` mid-`copyfileobj`,
        # truncating the artifact. See app/core/async_io.py.
        return await run_in_thread_draining(_put)

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for a key."""
        path = self._resolve_contained(key)
        return await asyncio.to_thread(path.read_bytes)

    async def copy(self, src_key: str, dst_key: str) -> None:
        """Copy within the staging root, creating the destination's parents."""
        src = self._resolve_contained(src_key)
        dst = self._resolve_contained(dst_key)

        def _copy() -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        await asyncio.to_thread(_copy)

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        """Read at most ``length`` bytes from byte offset ``start``."""
        path = self._resolve_contained(key)

        def _read() -> bytes:
            with path.open("rb") as fh:
                fh.seek(start)
                return fh.read(length)

        return await asyncio.to_thread(_read)

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

    async def get_range_stream(
        self, key: str, start: int, length: int
    ) -> AsyncIterator[bytes]:
        """Stream ``length`` bytes from ``start`` off ONE open file handle.

        fix(#1540 review P1): the interesting implementation is S3's, where the
        alternative was a request per chunk. Local storage never paid that, but
        it implements the same method so the route has one call to make and the
        object stores are not a special case at the call site.

        Handle closed in a ``finally`` for the reason ``get_stream`` gives:
        a client disconnecting mid-range must not leak a descriptor.
        """
        path = self._resolve_contained(key)
        if not await asyncio.to_thread(path.exists):
            raise FileNotFoundError(f"Storage key not found: {key}")

        f = await asyncio.to_thread(open, path, "rb")
        try:
            await asyncio.to_thread(f.seek, start)
            remaining = length
            while remaining > 0:
                chunk = await asyncio.to_thread(
                    f.read, min(remaining, _STREAM_CHUNK_BYTES)
                )
                if not chunk:
                    return
                yield chunk
                remaining -= len(chunk)
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

    def _matching_files(self, prefix: str, resolved_prefix: Path) -> list[Path]:
        """Every regular file whose key starts with *prefix*. Blocking."""
        resolved_base = self.base_dir.resolve()
        if not prefix or prefix.endswith("/") or resolved_prefix == resolved_base:
            # Directory prefix: list all files recursively under it
            if not resolved_prefix.exists():
                return []
            return [p for p in resolved_prefix.rglob("*") if p.is_file()]
        # File prefix: glob in the parent directory
        parent = resolved_prefix.parent
        if not parent.exists():
            return []
        pattern = resolved_prefix.name + "*"
        return [p for p in parent.glob(pattern) if p.is_file()]

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix, relative to base_dir."""
        # SEC-026: resolve the caller-supplied prefix before touching the
        # filesystem.  Keeping this check outside the worker also ensures a
        # rejected key never reaches exists(), rglob(), or glob().
        resolved_prefix = self._resolve_contained(prefix)
        resolved_base = self.base_dir.resolve()

        def _list() -> list[str]:
            return [
                str(p.relative_to(resolved_base))
                for p in self._matching_files(prefix, resolved_prefix)
            ]

        return await asyncio.to_thread(_list)

    def _walk_in_key_order(
        self, root: Path, resolved_base: Path, start_after: str | None
    ):
        """Lazily yield ``(path, key)`` under *root* in ascending key order.

        Blocking, and a generator on purpose (fix(#1249) review r5): building
        the whole list first would put an unbounded walk in front of the first
        page, so a consumer's per-page budget bounded its SQL but neither the
        filesystem traversal nor the memory it took to hold the result. Only
        one directory level is materialized at a time, and a subtree entirely
        below ``start_after`` is skipped without being entered at all.

        Entries sort by ``name + "/"`` for directories so this matches the
        lexicographic order of the FULL keys, which is what ``start_after``
        and the S3 ``StartAfter`` it mirrors are defined against — plain name
        order disagrees whenever a directory and a file share a stem (``/`` is
        0x2F, so ``frozen/x`` sorts after ``frozen.txt``).

        Symlinks are not followed. A staging tree has none, and for a walk
        that feeds a deleter, declining to leave the tree through one is the
        posture to keep.
        """
        try:
            with os.scandir(root) as entries:
                ordered = sorted(
                    entries,
                    key=lambda e: (
                        e.name + "/" if e.is_dir(follow_symlinks=False) else e.name
                    ),
                )
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return
        for entry in ordered:
            path = Path(entry.path)
            key = str(path.relative_to(resolved_base))
            if entry.is_dir(follow_symlinks=False):
                child_prefix = key + "/"
                if (
                    start_after is not None
                    and child_prefix <= start_after
                    and not start_after.startswith(child_prefix)
                ):
                    continue  # every key in here sorts at or before the cursor
                yield from self._walk_in_key_order(path, resolved_base, start_after)
            elif entry.is_file(follow_symlinks=False):
                if start_after is not None and key <= start_after:
                    continue
                yield path, key

    def _keys_in_order(
        self,
        prefix: str,
        resolved_prefix: Path,
        resolved_base: Path,
        start_after: str | None,
    ):
        """``(path, key)`` pairs matching *prefix*, ascending, lazily."""
        if not prefix or prefix.endswith("/") or resolved_prefix == resolved_base:
            yield from self._walk_in_key_order(
                resolved_prefix, resolved_base, start_after
            )
            return
        # File prefix: one directory's glob, already bounded by construction.
        # This is the pre-delete re-read's shape — a complete key.
        parent = resolved_prefix.parent
        if not parent.exists():
            return
        for path in sorted(parent.glob(resolved_prefix.name + "*")):
            if not path.is_file():
                continue
            key = str(path.relative_to(resolved_base))
            if start_after is None or key > start_after:
                yield path, key

    async def iter_object_pages(
        self, prefix: str, *, start_after: str | None = None
    ) -> AsyncIterator[list[StoredObject]]:
        """Yield keys matching a prefix with their mtimes (feat #1249).

        Chunked into ``_OBJECT_PAGE_SIZE`` pages even though a local walk has
        no service-side paging to mirror (fix(#1249) review r2): an unbounded
        page defeats the between-pages budget the consumer relies on. The walk
        behind it is lazy, so a consumer that stops after one page has not paid
        for the rest of the tree either (review r5).
        """
        resolved_prefix = self._resolve_contained(prefix)
        resolved_base = self.base_dir.resolve()
        walker = self._keys_in_order(
            prefix, resolved_prefix, resolved_base, start_after
        )

        def _take_page() -> list[StoredObject]:
            page: list[StoredObject] = []
            for path, key in walker:
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    # Deleted between the walk and the stat. An entry that
                    # cannot be dated must not reach the caller, which would
                    # otherwise have to invent an age for it.
                    continue
                page.append(
                    StoredObject(
                        key=key,
                        last_modified=datetime.fromtimestamp(mtime, tz=timezone.utc),
                    )
                )
                if len(page) >= _OBJECT_PAGE_SIZE:
                    break
            return page

        while True:
            page = await asyncio.to_thread(_take_page)
            if not page:
                return
            yield page

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
