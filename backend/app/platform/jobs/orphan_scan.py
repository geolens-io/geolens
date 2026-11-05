"""The resumable orphan-object scan the storage sweeps share.

Each sweep supplies its key prefix, a page handler that decides and deletes,
and the budgets. This module owns what must not differ between them: the
advisory lock, the tenant gate, the circular walk with its resume cursor, the
per-pass budgets and the provider re-read that lets a handler confirm an
object's age right before it deletes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.storage.provider import StorageProvider, StoredObject
from app.platform.storage.titiler_url import resolve_current_storage_key

# Where the next pass resumes, per physical prefix. The scan is circular, so
# this is an offset, not a window: process-local state seeded at a random
# point only decides what is looked at first, never what may be deleted.
_scan_cursors: dict[str, str | None] = {}


def resume_point(physical_prefix: str) -> str | None:
    """Where this pass starts, seeding a random point on first use."""
    if physical_prefix not in _scan_cursors:
        # Same alphabet as the uuid segment of the swept keys, so the seed
        # lands uniformly inside the keyspace rather than before/after all of it.
        _scan_cursors[physical_prefix] = f"{physical_prefix}{uuid.uuid4()}"
    return _scan_cursors[physical_prefix]


async def current_entry(
    storage: StorageProvider, physical_key: str
) -> StoredObject | None:
    """Re-read one object's last-modified time, or None if it is gone.

    Uses ``iter_object_pages`` with a COMPLETE key: the Protocol has no
    head-with-timestamp call, so a one-key prefix listing is the portable
    substitute. Filtered for an exact match since a prefix also returns siblings.
    """
    async for page in storage.iter_object_pages(physical_key):
        for entry in page:
            if entry.key == physical_key:
                return entry
    return None


async def _iter_leg(
    storage: StorageProvider,
    physical_prefix: str,
    *,
    start_after: str | None,
    stop_at: str | None,
) -> AsyncIterator[list[StoredObject]]:
    """Pages of one leg of the circular scan, bounded above by ``stop_at``.

    The wrap leg must not run past the pass's start, or it would re-examine
    keys the first leg already covered instead of ending.
    """
    async for page in storage.iter_object_pages(
        physical_prefix, start_after=start_after
    ):
        if stop_at is None:
            yield page
            continue
        bounded = [entry for entry in page if entry.key <= stop_at]
        if bounded:
            yield bounded
        if len(bounded) < len(page):
            return  # this page crossed the boundary, so the leg is done


# (storage, physical prefix, non-empty page, key the previous page ended at)
# -> (finished the page, key the next pass resumes after). Unfinished means a
# delete budget stopped the handler partway, and ends the pass.
PageHandler = Callable[
    [StorageProvider, str, list[StoredObject], "str | None"],
    Awaitable[tuple[bool, "str | None"]],
]


@dataclass(frozen=True)
class ScanProgress:
    """What the walk covered, for the sweep's outcome and log."""

    objects_listed: int
    resume_after: str | None
    stopped_early: bool


async def _walk(
    storage: StorageProvider,
    physical_prefix: str,
    handle_page: PageHandler,
    *,
    max_objects: int,
    max_pages: int | None,
) -> ScanProgress:
    start = resume_point(physical_prefix)
    # The second leg is the wrap and is skipped when the pass already begins
    # at the front, where there is nothing to wrap to.
    legs: list[tuple[str | None, str | None]] = [(start, None)]
    if start is not None:
        legs.append((None, start))

    listed = 0
    pages = 0
    last_examined: str | None = None
    stopped_early = False
    for start_after, stop_at in legs:
        async for page in _iter_leg(
            storage, physical_prefix, start_after=start_after, stop_at=stop_at
        ):
            pages += 1
            listed += len(page)
            finished = True
            if page:
                finished, last_examined = await handle_page(
                    storage, physical_prefix, page, last_examined
                )
            if (
                not finished
                or (max_pages is not None and pages >= max_pages)
                or listed >= max_objects
            ):
                stopped_early = True
                break
        if stopped_early:
            break

    # A full pass has seen the whole prefix, so the next starts at the front.
    # A stop before any key was examined leaves no cursor worth resuming from.
    _scan_cursors[physical_prefix] = (
        last_examined if stopped_early and last_examined is not None else None
    )
    return ScanProgress(listed, last_examined, stopped_early)


async def reconcile_orphan_objects(
    *,
    prefix: str,
    lock_name: str,
    handle_page: PageHandler,
    max_objects: int,
    max_pages: int | None = None,
    db: AsyncSession | None = None,
    guard: Callable[[], Awaitable[bool]] | None = None,
) -> ScanProgress | None:
    """Walk ``prefix`` once, handing each page to ``handle_page``.

    Returns None when the pass declined: multi-tenant mode without a tenant
    context, another process holding the advisory lock, or ``guard`` saying no.
    With ``db``, the walk runs in a savepoint so a database error rolls back
    only this pass. ``guard`` runs before anything is listed, inside the
    savepoint when there is one.

    The lock lives on its own session, so ending it releases the lock without
    touching the caller's transaction.
    """
    from app.core.db import async_session  # late-bound so a test engine applies
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.platform.storage import get_storage

    if is_multi_tenant() and current_tenant_var.get() is None:
        # No tenant context to scope the listing: sweeping the whole bucket
        # while RLS shows no rows would read every tenant's objects as untracked.
        return None
    physical_prefix = resolve_current_storage_key(prefix)

    async with async_session() as lock_session:
        locked = await lock_session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"{lock_name}:{physical_prefix}"},
        )
        if not locked.scalar():
            return None
        storage = get_storage()

        async def walk() -> ScanProgress | None:
            if guard is not None and not await guard():
                return None
            return await _walk(
                storage,
                physical_prefix,
                handle_page,
                max_objects=max_objects,
                max_pages=max_pages,
            )

        if db is None:
            return await walk()
        async with db.begin_nested():
            return await walk()
