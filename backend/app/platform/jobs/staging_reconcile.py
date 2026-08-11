"""Reconcile real staging objects against ingest-job rows (fix #1249).

Every other staging reaper in this codebase starts from a ROW and asks what
object it owns. This one starts from the OBJECT and asks whether any row still
owns it — the only direction that can see an object no row references at all.

### Why reconciliation rather than a wider margin

#1235/#1236 closed the presigned-upload orphan window twice by widening the
window a sweep waits before it may act, and review round 5 of #1236 found the
residual gap in the approach itself: S3 validates a presigned signature when a
request STARTS, not when it finishes transferring, so an accepted single-part
PUT can still be writing arbitrarily long after every deadline derived from
its URL has passed. Any margin computed from elapsed time is a guess at a
transfer rate nothing enforces — widen it and the guess is merely rarer.

A HEAD-before-delete has the symmetric problem in the other direction: it
proves the object was absent when the check ran, not that it stays absent
while the delete is in flight.

Reconciliation removes the class instead of shrinking it. It never has to
decide whether some upload is "probably done"; it asks a question with a
durable answer — is there a row that owns this key? — and an object whose
answer is no is unreachable by any future PUT, because a presigned URL for
`staging/{job_id}/…` is only ever minted alongside the `ingest_jobs` row with
that id, and the retention purge deliberately keeps such a row alive until
past `MAX_PRESIGNED_URL_LIFETIME_SECONDS + _RECHECK_TRANSFER_MARGIN_SECONDS`
(see `presigned_url_may_still_be_live` in `sweep.py`). It also catches orphans
from causes no margin ever addressed: a delete that failed inside a
best-effort reaper, a row purged while its object delete errored, a worker
killed between writing an object and committing the row that names it.

### The two races, handled by construction

1. **An object uploaded after the listing snapshot.** Only objects whose
   last-modified is older than ``staging_orphan_min_age_seconds`` are ever
   candidates, and the age is re-read from the provider immediately before the
   delete — a listing entry alone is never authority for destroying anything.
   An object created or overwritten after the snapshot fails that re-read.
2. **A row that lands after the batch row query.** Absence is re-checked per
   object, immediately before that object's delete, in its own statement.
   PostgreSQL's default READ COMMITTED gives every statement a fresh snapshot,
   so the recheck sees rows committed since the batch query rather than
   replaying it.

Neither race can be closed by ordering alone — there is no atomic
"delete-if-still-unreferenced" across a database and an object store. What
makes the residue harmless is that both rechecks fail CLOSED (an ambiguous or
unreadable answer skips the object and leaves it for the next pass), and the
only thing a missed pass costs is a day of leaked bytes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.observability.metrics.jobs import staging_orphans_deleted_total
from app.platform.jobs.models import IngestJob
from app.platform.storage.provider import StoredObject
from app.platform.storage.titiler_url import resolve_current_storage_key

log = structlog.get_logger()

# The one prefix this sweep may delete under. Everything below it is written
# by the upload system and namespaced by the job that wrote it
# (`staging/{job_id}/…`, plus the `frozen/` snapshot under the same job
# segment); `manifest_sources.py` explicitly refuses operator keys here for
# that reason. Nothing outside this prefix is ever listed, so no object the
# upload system does not own can reach the delete path at all.
STAGING_PREFIX = "staging/"

# Deletes per pass. The pass holds one transaction open for its advisory lock,
# and each delete costs a row recheck plus an age re-read, so an unbounded loop
# over a pathological bucket would keep a session idle-in-transaction for a
# long time. Leftovers are not urgent — they are already-leaked bytes, and the
# sweep runs every few minutes.
_MAX_DELETES_PER_PASS = 200


@dataclass(frozen=True)
class StagingReconcileOutcome:
    """What one reconciliation pass saw and did."""

    # False when the pass declined to run at all: another process holds the
    # lock, or multi-tenant mode gave no tenant context to scope the prefix.
    ran: bool = False
    objects_listed: int = 0
    orphans_deleted: int = 0
    delete_failures: int = 0
    # Skips, each its own number because they mean different things:
    #   recent          — younger than the threshold at listing time; the
    #                     ordinary steady state on a busy instance.
    #   object_changed  — the pre-delete re-read found it gone or rewritten;
    #                     race #1 being caught.
    #   row_appeared    — the pre-delete recheck found a row; race #2.
    #   unattributable  — something under `staging/` whose owning job cannot
    #                     be named, which this sweep declines to touch.
    skipped_recent: int = 0
    skipped_object_changed: int = 0
    skipped_row_appeared: int = 0
    skipped_unattributable: int = 0

    def as_log_fields(self) -> dict[str, int]:
        """Flatten to structlog kwargs."""
        return {
            "objects_listed": self.objects_listed,
            "orphans_deleted": self.orphans_deleted,
            "delete_failures": self.delete_failures,
            "skipped_recent": self.skipped_recent,
            "skipped_object_changed": self.skipped_object_changed,
            "skipped_row_appeared": self.skipped_row_appeared,
            "skipped_unattributable": self.skipped_unattributable,
        }


def _job_id_from_key(logical_key: str) -> uuid.UUID | None:
    """Extract the owning job id from a `staging/{job_id}/…` key.

    Returns None for anything that is not shaped like a job-owned staging key
    — including `staging/{job_id}` with no trailing segment, which names no
    object this sweep put there. An unparseable key is never deleted: this
    sweep only destroys objects it can positively attribute to an absent row,
    and "I cannot tell whose this is" is not that.
    """
    parts = logical_key.split("/")
    if len(parts) < 3 or parts[0] != "staging" or not parts[-1]:
        return None
    try:
        return uuid.UUID(parts[1])
    except ValueError:
        return None


async def _job_row_exists(db: AsyncSession, job_id: uuid.UUID) -> bool:
    """Is there still an ``ingest_jobs`` row with this id, right now?

    A fresh statement rather than a reuse of the batch query's result on
    purpose: under READ COMMITTED every statement takes its own snapshot, so
    this sees rows committed since that query — which is exactly the race it
    exists to catch. Core select over the id column, never an ORM object load,
    so the session's identity map cannot answer from a stale instance.
    """
    result = await db.execute(select(IngestJob.id).where(IngestJob.id == job_id))
    return result.first() is not None


async def _current_entry(storage, physical_key: str) -> StoredObject | None:
    """Re-read one object's last-modified time, or None if it is gone.

    ``list_objects`` with a COMPLETE key rather than a directory prefix: the
    Protocol has no head-with-timestamp call, and a prefix listing of one exact
    key is the portable way to ask every provider the same question. The result
    is filtered for an exact match because a prefix listing also returns
    siblings whose keys merely start with this one.
    """
    for entry in await storage.list_objects(physical_key):
        if entry.key == physical_key:
            return entry
    return None


async def reconcile_orphaned_staging_objects(
    db: AsyncSession, *, now: datetime | None = None
) -> StagingReconcileOutcome:
    """Delete staging objects that no ``ingest_jobs`` row tracks.

    Read-only against ``db`` — the only mutation is on the object store, and
    the caller's session is neither committed nor rolled back here. That is
    deliberate rather than incidental: a rollback expires every instance in
    the caller's identity map regardless of ``expire_on_commit``, so a sweep
    that still holds ORM objects would find them unloadable afterwards. The
    advisory lock therefore lives on a session of this function's own.

    The lock is what makes the counter honest. Every API worker runs its own
    copy of the sweeper loop, and each would otherwise list the same prefix and
    count the same delete, reporting N times the truth under
    ``UVICORN_WORKERS>1`` — the same fabricated-number class #1240 existed to
    remove. It also keeps the provider LIST to one per interval per tenant
    rather than one per worker. Transaction-scoped, so a process that dies
    mid-pass releases it with its connection rather than wedging every future
    pass.

    Never raises: a provider or database failure mid-pass leaves whatever it
    has not reached for the next cycle. Nothing downstream depends on this
    having run, and the sweep it is wired into must survive it.
    """
    now = now or datetime.now(timezone.utc)
    try:
        return await _reconcile(db, now=now)
    except Exception as exc:  # broad: best-effort pass, never fails its caller
        log.warning(
            "Staging orphan reconciliation failed",
            error=str(exc),
            exc_info=True,
        )
        return StagingReconcileOutcome(ran=False)


async def _reconcile(db: AsyncSession, *, now: datetime) -> StagingReconcileOutcome:
    """The pass itself. See the wrapper above for the error and lock contract."""
    from app.core.db import async_session  # late-bound for tests, as #909 does
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.platform.storage import get_storage

    if is_multi_tenant() and current_tenant_var.get() is None:
        # No tenant context, no tenant namespace to scope the listing to.
        # Declining is the only safe answer: the alternative would sweep the
        # whole bucket while the session's RLS shows it no rows at all, which
        # reads every tenant's objects as untracked. Same fail-closed posture
        # as `_stale_generation_storage_keys` in sweep.py.
        return StagingReconcileOutcome(ran=False)

    # Resolves the ACTIVE tenant's namespace in multi-tenant mode, so the
    # listing can never cross a tenant boundary.
    physical_prefix = resolve_current_storage_key(STAGING_PREFIX)

    # A session that exists only to hold the lock. It touches no table, so RLS
    # and tenant context are irrelevant to it; every row read below goes
    # through the caller's already tenant-scoped ``db``. Leaving the context
    # ends its transaction and releases the lock, and it does so without
    # committing or rolling back anything the caller owns.
    async with async_session() as lock_session:
        locked = await lock_session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"staging-orphan-reconcile:{physical_prefix}"},
        )
        if not locked.scalar():
            return StagingReconcileOutcome(ran=False)
        return await _reconcile_locked(
            db, now=now, physical_prefix=physical_prefix, storage=get_storage()
        )


async def _reconcile_locked(
    db: AsyncSession,
    *,
    now: datetime,
    physical_prefix: str,
    storage,
) -> StagingReconcileOutcome:
    """The pass body, entered only with the advisory lock held."""
    # Clock skew between this process and the object store is immaterial at a
    # threshold measured in hours, which is one more reason the threshold is
    # not a tuned estimate of transfer duration.
    cutoff = now - timedelta(seconds=settings.staging_orphan_min_age_seconds)
    listed = await storage.list_objects(physical_prefix)

    skipped_recent = 0
    skipped_unattributable = 0
    candidates: list[tuple[str, uuid.UUID]] = []
    for entry in listed:
        # Defensive: a provider that returned a key outside the prefix it was
        # asked for must not be trusted to name a deletable object.
        if not entry.key.startswith(physical_prefix):
            skipped_unattributable += 1
            continue
        logical_key = STAGING_PREFIX + entry.key[len(physical_prefix) :]
        job_id = _job_id_from_key(logical_key)
        if job_id is None:
            skipped_unattributable += 1
            continue
        if entry.last_modified >= cutoff:
            skipped_recent += 1
            continue
        candidates.append((entry.key, job_id))

    if not candidates:
        return StagingReconcileOutcome(
            ran=True,
            objects_listed=len(listed),
            skipped_recent=skipped_recent,
            skipped_unattributable=skipped_unattributable,
        )

    # One query for the common case (everything is tracked); the per-object
    # recheck below is the authority, this only avoids paying for it per object
    # on a healthy bucket.
    live_ids = set(
        (
            await db.execute(
                select(IngestJob.id).where(
                    IngestJob.id.in_({job_id for _key, job_id in candidates})
                )
            )
        ).scalars()
    )

    deleted = 0
    failures = 0
    skipped_object_changed = 0
    skipped_row_appeared = 0
    for physical_key, job_id in sorted(candidates):
        if job_id in live_ids:
            continue
        if deleted + failures >= _MAX_DELETES_PER_PASS:
            break
        # Deliberately OUTSIDE the try below. A database error here is not a
        # per-object problem to count and move past — it leaves the
        # transaction unusable, so every remaining candidate would "fail" on a
        # recheck that never ran. Let it reach the wrapper and end the pass.
        if await _job_row_exists(db, job_id):
            skipped_row_appeared += 1
            continue
        try:
            entry = await _current_entry(storage, physical_key)
            if entry is None or entry.last_modified >= cutoff:
                # Gone already, or rewritten since the listing. Either way
                # this pass has nothing it can honestly delete.
                skipped_object_changed += 1
                continue
            await storage.delete(physical_key)
        except Exception:  # broad: best-effort per object, the pass continues
            failures += 1
            log.warning(
                "Failed to delete orphaned staging object",
                storage_key=physical_key,
                job_id=str(job_id),
            )
            continue
        deleted += 1
        log.warning(
            "Deleted orphaned staging object with no ingest job row",
            storage_key=physical_key,
            job_id=str(job_id),
            last_modified=entry.last_modified.isoformat(),
            age_seconds=int((now - entry.last_modified).total_seconds()),
        )

    if deleted:
        # After the deletes returned, never before: the counter records
        # completed deletions, not intentions.
        staging_orphans_deleted_total.inc(deleted)

    return StagingReconcileOutcome(
        ran=True,
        objects_listed=len(listed),
        orphans_deleted=deleted,
        delete_failures=failures,
        skipped_recent=skipped_recent,
        skipped_object_changed=skipped_object_changed,
        skipped_row_appeared=skipped_row_appeared,
        skipped_unattributable=skipped_unattributable,
    )
