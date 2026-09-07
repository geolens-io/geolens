from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from app.core.async_io import run_in_thread_draining
from app.platform.storage.provider import StoredObject


# Chunk size for streaming reads (ING-03/P2-03): balances syscall overhead
# against per-download resident memory.
_STREAM_CHUNK_BYTES = 1024 * 1024  # 1 MiB

# Matches the ListObjectsV2 default so a consumer's per-page budget behaves
# the same on every backend (feat #1249).
_OBJECT_PAGE_SIZE = 1000


class LocalStorageProvider:
    """Storage provider wrapping local filesystem operations under a base directory."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_contained(self, key: str) -> Path:
        """Return the resolved path for *key*, asserting it stays inside base_dir.

        Rejects absolute keys, null bytes, and path-traversal that escapes
        base_dir, raising ``ValueError`` (caller maps to 400/403). SEC-026:
        called at the top of every IO method so none is a bypass.
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

        fix(#435): a file-like ``data`` stays file-like, copied in 1 MiB
        chunks inside the worker thread — not ``data.read()`` materializing a
        whole COG/VRT/original (can exceed the 2 GB container limit) as one
        ``bytes`` object.
        """
        dest = self._resolve_contained(key)

        def _write(tmp: Path, payload: BinaryIO | bytes) -> None:
            if isinstance(payload, bytes):
                tmp.write_bytes(payload)
            else:
                with open(tmp, "wb") as out:
                    shutil.copyfileobj(payload, out, _STREAM_CHUNK_BYTES)

        def _put() -> str:
            dest.parent.mkdir(parents=True, exist_ok=True)
            # fix(#1532): write beside dest, then os.replace (atomic, same
            # dir) — an ENOSPC or kill mid-copy must never leave a partial
            # file visible under the real key, unlike S3/Azure puts.
            tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex}.tmp")
            try:
                try:
                    _write(tmp, data)
                except FileNotFoundError:
                    # fix(#1532): the dir can vanish between mkdir and open if
                    # the empty-dir sweeper runs concurrently. Retry ONCE — a
                    # second disappearance means a broken volume, not a race.
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if hasattr(data, "seek"):
                        data.seek(0)
                    _write(tmp, data)
                os.replace(tmp, dest)
            except BaseException:
                # BaseException: a cancelled write (drained by the caller)
                # must still clean up its scratch file.
                tmp.unlink(missing_ok=True)
                raise
            return str(dest)

        # fix(#435): drain the copy thread on cancellation — otherwise the
        # caller's `with open(...)` can close `data` mid-copyfileobj and
        # truncate the artifact. See app/core/async_io.py.
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
        """Stream key bytes in 1 MiB chunks (ING-03/P2-03).

        Avoids materializing a large COG as one ``bytes`` object. Handle
        closed in ``finally`` so a client disconnect mid-stream doesn't leak
        an fd. Raises ``FileNotFoundError`` upfront to match ``get()``'s
        exception shape.
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

        fix(#1540): mirrors S3/Azure's one-call contract, though local never
        paid the per-chunk-request cost they did — this keeps object stores
        from being a special case at the call site. Handle closed in
        ``finally`` for the same fd-leak reason as ``get_stream``.
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
        """Delete a key. No error if missing.

        Deliberately does not remove emptied directories (fix #1532):
        pruning here raced a concurrent writer's mkdir/open. Pruning belongs
        to the subsystem that owns the prefix — see ``prune_empty_dirs``.
        """
        path = self._resolve_contained(key)
        await asyncio.to_thread(path.unlink, True)  # missing_ok=True

    async def prune_empty_dirs(self, prefix: str) -> int:
        """Remove empty directories under ``prefix``. Returns how many went.

        Offered via ``getattr``, not the Protocol — object stores have no
        directories to prune. Bottom-up; skips ``base_dir``/the prefix root;
        ignores per-directory failures (a concurrent writer using one is not
        an error).
        """
        root = self._resolve_contained(prefix)
        base = self.base_dir.resolve()

        def _prune() -> int:
            if not root.is_dir():
                return 0
            removed = 0
            for directory in sorted(
                (p for p in root.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                if directory == base or directory == root:
                    continue
                try:
                    directory.rmdir()
                    removed += 1
                except OSError:
                    continue  # not empty, or a concurrent put just used it
            return removed

        return await asyncio.to_thread(_prune)

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
        # SEC-026: resolve the prefix before touching the filesystem, outside
        # the worker, so a rejected key never reaches exists()/rglob()/glob().
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

        Blocking; a generator (fix #1249) so an unbounded walk never sits in
        front of the first page, and a subtree entirely below ``start_after``
        is never entered.

        Directories sort by ``name + "/"`` to match full-key lexicographic
        order (``frozen/x`` must sort after ``frozen.txt``, which plain name
        order gets wrong).

        Symlinks are not followed — this feeds a deleter and must never leave
        the tree through one.
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
        # File prefix: one bounded directory glob — the pre-delete re-read's shape.
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

        Chunked into ``_OBJECT_PAGE_SIZE`` pages so an unbounded page can't
        defeat the consumer's between-pages budget, even though local has no
        service-side paging to mirror. The walk is lazy, so stopping after
        one page doesn't pay for the rest of the tree.
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
                    # Deleted between walk and stat; an undatable entry must
                    # never reach the caller.
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

    # Presigned URLs are not supported for local storage.

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
