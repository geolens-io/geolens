"""Delete the vector quicklook images no dataset points at.

A redraw uploads its image under a fresh ``vectors/<dataset id>/`` key, moves
the dataset's pointer to it and deletes the key it replaced. A process that
dies between those steps leaves an image nothing references. This pass starts
from the objects and deletes one only when each of these holds, read again
right before the delete:

- Its key is exactly ``vectors/<lowercase uuid>/quicklook_256_<12 hex>.png``.
- It is older than ``QUICKLOOK_ORPHAN_MIN_AGE``, far longer than a draw takes
  to upload and commit its pointer, so an image a redraw is about to
  reference is never touched.
- No dataset's ``quicklook_256_uri`` names it.

It declines in multi-tenant mode without a tenant context, and while the
catalog holds no datasets at all. Every pass is
bounded, and one process at a time scans, under an advisory lock.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.originals_reconcile import _catalog_has_datasets
from app.platform.jobs.staging_reconcile import (
    _current_entry,
    _iter_leg,
    _resume_point,
    _scan_cursors,
)
from app.platform.storage.provider import StoredObject
from app.platform.storage.titiler_url import resolve_current_storage_key

log = structlog.get_logger()

QUICKLOOK_PREFIX = "vectors/"

QUICKLOOK_ORPHAN_MIN_AGE = timedelta(days=1)

_QUICKLOOK_NAME = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"/quicklook_256_[0-9a-f]{12}\.png"
)

_MAX_DELETES_PER_PASS = 200
_MAX_OBJECTS_SCANNED_PER_PASS = 20_000
# A provider that filters the resume cursor client-side still fetches the pages
# before it, and those count here.
_MAX_PAGES_PER_PASS = 100


@dataclass
class QuicklookReconcileOutcome:
    """What one pass saw and did."""

    # False when the pass declined, or another process held the pass's lock.
    ran: bool = False
    objects_listed: int = 0
    objects_deleted: int = 0
    delete_failures: int = 0
    skipped_recent: int = 0
    # A dataset points at the image.
    skipped_live: int = 0
    # Gone, rewritten or taken by a dataset between the listing and its delete.
    skipped_changed: int = 0
    # A key that is not exactly a quicklook's shape.
    skipped_unattributable: int = 0

    def budget_spent(self) -> bool:
        return self.objects_deleted + self.delete_failures >= _MAX_DELETES_PER_PASS


def _logical_key(key: str, physical_prefix: str) -> str | None:
    """``key`` as a dataset records it, or None unless it is a quicklook's."""
    if not key.startswith(physical_prefix):
        return None
    name = key[len(physical_prefix) :]
    if _QUICKLOOK_NAME.fullmatch(name) is None:
        return None
    return f"{QUICKLOOK_PREFIX}{name}"


async def _referenced(db: AsyncSession, logical_keys: set[str]) -> set[str]:
    """The ``logical_keys`` some dataset points at, in one fresh statement."""
    if not logical_keys:
        return set()
    from app.platform.extensions import get_processing_port

    dataset = get_processing_port().get_dataset_orm_class()
    rows = await db.scalars(
        select(dataset.quicklook_256_uri).where(
            dataset.quicklook_256_uri.in_(logical_keys)
        )
    )
    return set(rows)


async def _delete_if_unchanged(
    db: AsyncSession,
    storage,
    entry: StoredObject,
    logical_key: str,
    *,
    cutoff: datetime,
    now: datetime,
    outcome: QuicklookReconcileOutcome,
) -> None:
    try:
        current = await _current_entry(storage, entry.key)
        if current is None or current.last_modified >= cutoff:
            outcome.skipped_changed += 1
            return
    except Exception as exc:  # broad: best-effort per object, the pass continues
        outcome.delete_failures += 1
        log.warning(
            "Failed to re-read a quicklook no dataset owns",
            error_type=type(exc).__name__,
        )
        return
    # Outside any try: a database error ends the pass instead of deleting an
    # image whose pointer could not be checked.
    if await _referenced(db, {logical_key}):
        outcome.skipped_changed += 1
        return
    try:
        await storage.delete(entry.key)
    except Exception as exc:  # broad: best-effort per object, the pass continues
        outcome.delete_failures += 1
        log.warning(
            "Failed to delete a quicklook no dataset owns",
            error_type=type(exc).__name__,
        )
        return
    outcome.objects_deleted += 1
    log.warning(
        "Deleted a quicklook no dataset owns",
        age_seconds=int((now - current.last_modified).total_seconds()),
    )


async def _reap_page(
    db: AsyncSession,
    storage,
    page: list[StoredObject],
    physical_prefix: str,
    *,
    previous_end: str | None,
    cutoff: datetime,
    now: datetime,
    outcome: QuicklookReconcileOutcome,
) -> tuple[bool, str | None]:
    """Reap the orphaned quicklooks one page lists.

    Returns whether the page was finished and the key the next pass resumes
    after: the page's end, or where the delete budget stopped it.
    """
    old: dict[str, StoredObject] = {}
    for entry in page:
        logical = _logical_key(entry.key, physical_prefix)
        if logical is None:
            outcome.skipped_unattributable += 1
        elif entry.last_modified >= cutoff:
            outcome.skipped_recent += 1
        else:
            old[logical] = entry
    live = await _referenced(db, set(old))
    outcome.skipped_live += len(live)

    resume_after = previous_end
    for logical, entry in sorted(old.items(), key=lambda item: item[1].key):
        if logical in live:
            continue
        if outcome.budget_spent():
            return False, resume_after
        await _delete_if_unchanged(
            db, storage, entry, logical, cutoff=cutoff, now=now, outcome=outcome
        )
        resume_after = entry.key
    return True, page[-1].key


async def _scan(
    db: AsyncSession, storage, physical_prefix: str, *, now: datetime
) -> QuicklookReconcileOutcome:
    """The pass body, entered only with the advisory lock held.

    Scans circularly from the resume point, so every key is reached across passes.
    """
    outcome = QuicklookReconcileOutcome(ran=True)
    cutoff = now - QUICKLOOK_ORPHAN_MIN_AGE
    resume_point = _resume_point(physical_prefix)
    legs: list[tuple[str | None, str | None]] = [(resume_point, None)]
    if resume_point is not None:
        legs.append((None, resume_point))

    last_examined: str | None = None
    pages = 0
    stopped_early = False
    for start_after, stop_at in legs:
        async for page in _iter_leg(
            storage, physical_prefix, start_after=start_after, stop_at=stop_at
        ):
            pages += 1
            outcome.objects_listed += len(page)
            finished = True
            if page:
                finished, last_examined = await _reap_page(
                    db,
                    storage,
                    page,
                    physical_prefix,
                    previous_end=last_examined,
                    cutoff=cutoff,
                    now=now,
                    outcome=outcome,
                )
            if (
                not finished
                or pages >= _MAX_PAGES_PER_PASS
                or outcome.objects_listed >= _MAX_OBJECTS_SCANNED_PER_PASS
            ):
                stopped_early = True
                break
        if stopped_early:
            break

    # A stop before any key was examined leaves no cursor worth resuming from.
    _scan_cursors[physical_prefix] = last_examined if stopped_early else None
    return outcome


async def _reconcile(db: AsyncSession, *, now: datetime) -> QuicklookReconcileOutcome:
    from app.core.db import async_session  # late-bound so a test engine applies
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.platform.storage import get_storage

    if is_multi_tenant() and current_tenant_var.get() is None:
        return QuicklookReconcileOutcome()
    physical_prefix = resolve_current_storage_key(QUICKLOOK_PREFIX)

    # A session that only holds the lock, so ending it releases the lock
    # without touching ``db``'s transaction.
    async with async_session() as lock_session:
        locked = await lock_session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"quicklook-orphan-reconcile:{physical_prefix}"},
        )
        if not locked.scalar():
            return QuicklookReconcileOutcome()
        async with db.begin_nested():
            if not await _catalog_has_datasets(db):
                return QuicklookReconcileOutcome()
            return await _scan(db, get_storage(), physical_prefix, now=now)


async def reconcile_orphaned_quicklooks(
    db: AsyncSession, *, now: datetime | None = None
) -> QuicklookReconcileOutcome:
    """Delete the quicklooks under ``vectors/`` that no dataset points at.

    Only reads through ``db``, inside a savepoint, so a database error rolls
    back just this pass. Never raises: a failure leaves the rest for the next
    pass.
    """
    try:
        outcome = await _reconcile(db, now=now or datetime.now(timezone.utc))
    except Exception:  # broad: best-effort pass, never fails its caller
        log.warning("Quicklook reconciliation failed", exc_info=True)
        return QuicklookReconcileOutcome()
    if outcome.objects_deleted or outcome.delete_failures:
        log.info("Reconciled quicklooks no dataset owns", **asdict(outcome))
    return outcome
