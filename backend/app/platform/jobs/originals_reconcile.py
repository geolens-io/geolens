"""Delete the originals a deleted dataset left under ``originals/``.

A dataset delete reaps ``originals/<dataset id>/`` after its commit, but an
archive write that outlived the connection holding its job row can land
afterwards. This pass starts from the objects and deletes a prefix only when
every one of these holds, each read again right before the delete:

- Its keys are exactly ``originals/<lowercase uuid>/<name>``, nothing nested.
- No dataset has that id, and no active or unreaped ingest job names it.
- Its newest object is older than ``ORIGINALS_ORPHAN_MIN_AGE``.

It declines in multi-tenant mode without a tenant context, and while the
catalog holds no datasets at all. Every pass is bounded, and one process at a
time scans, under an advisory lock.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import Text, cast, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import (
    ACTIVE_STATUSES,
    UNREAPED_ARTIFACT_FIELDS,
    IngestJob,
)
from app.platform.jobs.staging_reconcile import (
    _current_entry,
    _iter_leg,
    _resume_point,
    _scan_cursors,
)
from app.platform.storage.provider import StoredObject
from app.platform.storage.titiler_url import resolve_current_storage_key

log = structlog.get_logger()

ORIGINALS_PREFIX = "originals/"

# Far longer than any import runs, so a write still in flight is never reaped.
ORIGINALS_ORPHAN_MIN_AGE = timedelta(days=1)

_MAX_DELETES_PER_PASS = 200
_MAX_OBJECTS_SCANNED_PER_PASS = 20_000
# Azure filters the resume cursor client-side, so the pages before it are
# fetched too; a prefix deeper than this many pages is not reached.
_MAX_PAGES_PER_PASS = 100
# A prefix holds a handful of originals; one past this is not one of ours.
_MAX_OBJECTS_PER_PREFIX = 1_000


@dataclass
class OriginalsReconcileOutcome:
    """What one pass saw and did."""

    # False when the pass declined, or another process held the pass's lock.
    ran: bool = False
    objects_listed: int = 0
    objects_deleted: int = 0
    delete_failures: int = 0
    # A dataset row or a job that can still write names the prefix.
    skipped_live: int = 0
    # The prefix's newest object is inside the grace period.
    skipped_recent: int = 0
    # Gone or rewritten between the listing and its delete.
    skipped_changed: int = 0
    # A key or prefix that is not exactly an original's shape.
    skipped_unattributable: int = 0

    def budget_spent(self) -> bool:
        return self.objects_deleted + self.delete_failures >= _MAX_DELETES_PER_PASS


def _owner_id(key: str, physical_prefix: str) -> uuid.UUID | None:
    """The dataset id of a key shaped ``{physical_prefix}{uuid}/{name}``, else None."""
    if not key.startswith(physical_prefix):
        return None
    head, slash, name = key[len(physical_prefix) :].partition("/")
    if not slash or not name or "/" in name:
        return None
    try:
        owner = uuid.UUID(head)
    except ValueError:
        return None
    return owner if str(owner) == head else None


def _dataset_model():
    from app.platform.extensions import get_processing_port

    return get_processing_port().get_dataset_orm_class()


async def _catalog_has_datasets(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(exists(select(_dataset_model().id)))))


async def _still_referenced(db: AsyncSession, dataset_id: uuid.UUID) -> bool:
    """Whether a dataset, or a job that can still write the prefix, names ``dataset_id``.

    One fresh statement, so a row committed since the listing counts. A job
    can still write while it is active or carries an artifact or follow-up
    nothing has settled; the id is matched anywhere in its metadata.
    """
    dataset = select(_dataset_model().id).where(_dataset_model().id == dataset_id)
    can_still_write = or_(
        IngestJob.status.in_(ACTIVE_STATUSES),
        *(
            IngestJob.user_metadata[field].is_not(None)
            for field in UNREAPED_ARTIFACT_FIELDS
        ),
    )
    job = select(IngestJob.id).where(
        can_still_write,
        func.strpos(cast(IngestJob.user_metadata, Text), str(dataset_id)) > 0,
    )
    return bool(await db.scalar(select(or_(exists(dataset), exists(job)))))


async def _list_prefix(storage, prefix: str) -> list[StoredObject] | None:
    """Every object under ``prefix``, or None when there are more than one prefix should hold."""
    entries: list[StoredObject] = []
    async for page in storage.iter_object_pages(prefix):
        entries.extend(page)
        if len(entries) > _MAX_OBJECTS_PER_PREFIX:
            return None
    return entries


async def _delete_if_unchanged(
    storage,
    entry: StoredObject,
    dataset_id: uuid.UUID,
    *,
    cutoff: datetime,
    now: datetime,
    outcome: OriginalsReconcileOutcome,
) -> None:
    try:
        current = await _current_entry(storage, entry.key)
        if current is None or current.last_modified >= cutoff:
            outcome.skipped_changed += 1
            return
        await storage.delete(entry.key)
    except Exception as exc:  # broad: best-effort per object, the pass continues
        outcome.delete_failures += 1
        log.warning(
            "Failed to delete an original no dataset owns",
            dataset_id=str(dataset_id),
            error_type=type(exc).__name__,
        )
        return
    outcome.objects_deleted += 1
    log.warning(
        "Deleted an original no dataset owns",
        dataset_id=str(dataset_id),
        age_seconds=int((now - current.last_modified).total_seconds()),
    )


async def _reap_prefix(
    db: AsyncSession,
    storage,
    physical_prefix: str,
    dataset_id: uuid.UUID,
    *,
    cutoff: datetime,
    now: datetime,
    outcome: OriginalsReconcileOutcome,
) -> None:
    """Delete the originals under one prefix if nothing can still use them."""
    entries = await _list_prefix(storage, f"{physical_prefix}{dataset_id}/")
    if entries is None or any(
        _owner_id(entry.key, physical_prefix) != dataset_id for entry in entries
    ):
        outcome.skipped_unattributable += 1
        return
    if not entries:
        outcome.skipped_changed += 1
        return
    if max(entry.last_modified for entry in entries) >= cutoff:
        outcome.skipped_recent += 1
        return
    # Outside any try: a database error ends the pass instead of deleting unchecked.
    if await _still_referenced(db, dataset_id):
        outcome.skipped_live += 1
        return
    for entry in sorted(entries, key=lambda entry: entry.key):
        if outcome.budget_spent():
            return
        await _delete_if_unchanged(
            storage, entry, dataset_id, cutoff=cutoff, now=now, outcome=outcome
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
    handled: set[uuid.UUID],
    outcome: OriginalsReconcileOutcome,
) -> tuple[bool, str | None]:
    """Reap the orphaned prefixes one page names.

    Returns whether the page was finished and the key the next pass resumes
    after: the page's end, or where the delete budget stopped it.
    """
    newest: dict[uuid.UUID, datetime] = {}
    last_key: dict[uuid.UUID, str] = {}
    for entry in page:
        owner = _owner_id(entry.key, physical_prefix)
        if owner is None:
            outcome.skipped_unattributable += 1
            continue
        newest[owner] = max(newest.get(owner, entry.last_modified), entry.last_modified)
        last_key[owner] = entry.key
    fresh = {owner for owner, modified in newest.items() if modified >= cutoff}
    outcome.skipped_recent += len(fresh)
    old = newest.keys() - fresh - handled
    live: set[uuid.UUID] = set()
    if old:
        dataset = _dataset_model()
        live = set(
            (await db.execute(select(dataset.id).where(dataset.id.in_(old)))).scalars()
        )
    outcome.skipped_live += len(live)

    resume_after = previous_end
    for owner in sorted(old - live):
        if outcome.budget_spent():
            return False, resume_after
        handled.add(owner)
        await _reap_prefix(
            db, storage, physical_prefix, owner, cutoff=cutoff, now=now, outcome=outcome
        )
        resume_after = last_key[owner]
    return True, page[-1].key


async def _scan(
    db: AsyncSession, storage, physical_prefix: str, *, now: datetime
) -> OriginalsReconcileOutcome:
    """The pass body, entered only with the advisory lock held.

    Scans circularly from the resume point, so every key is reached across passes.
    """
    outcome = OriginalsReconcileOutcome(ran=True)
    cutoff = now - ORIGINALS_ORPHAN_MIN_AGE
    resume_point = _resume_point(physical_prefix)
    legs: list[tuple[str | None, str | None]] = [(resume_point, None)]
    if resume_point is not None:
        legs.append((None, resume_point))

    handled: set[uuid.UUID] = set()
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
                    handled=handled,
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


async def _reconcile(db: AsyncSession, *, now: datetime) -> OriginalsReconcileOutcome:
    from app.core.db import async_session  # late-bound so a test engine applies
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.platform.storage import get_storage

    if is_multi_tenant() and current_tenant_var.get() is None:
        return OriginalsReconcileOutcome()
    physical_prefix = resolve_current_storage_key(ORIGINALS_PREFIX)

    # A session that only holds the lock, so ending it releases the lock
    # without touching ``db``'s transaction.
    async with async_session() as lock_session:
        locked = await lock_session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"originals-orphan-reconcile:{physical_prefix}"},
        )
        if not locked.scalar():
            return OriginalsReconcileOutcome()
        async with db.begin_nested():
            if not await _catalog_has_datasets(db):
                return OriginalsReconcileOutcome()
            return await _scan(db, get_storage(), physical_prefix, now=now)


async def reconcile_orphaned_originals(
    db: AsyncSession, *, now: datetime | None = None
) -> OriginalsReconcileOutcome:
    """Delete the originals under ``originals/`` that no dataset or job can still use.

    Only reads through ``db``, inside a savepoint, so a database error rolls
    back just this pass. Never raises: a failure leaves the rest for the next
    pass.
    """
    try:
        outcome = await _reconcile(db, now=now or datetime.now(timezone.utc))
    except Exception:  # broad: best-effort pass, never fails its caller
        log.warning("Originals reconciliation failed", exc_info=True)
        return OriginalsReconcileOutcome()
    if outcome.objects_deleted or outcome.delete_failures:
        log.info("Reconciled originals no dataset owns", **asdict(outcome))
    return outcome
