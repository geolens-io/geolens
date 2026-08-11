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
durable answer — does any row still reference this key? — and an object whose
answer is no is unreachable by any future PUT, because a presigned URL for
`staging/{job_id}/…` is only ever minted alongside the `ingest_jobs` row with
that id, and the retention purge deliberately keeps such a row alive until
past `MAX_PRESIGNED_URL_LIFETIME_SECONDS + _RECHECK_TRANSFER_MARGIN_SECONDS`
(see `presigned_url_may_still_be_live` in `sweep.py`). It also catches orphans
from causes no margin ever addressed: a delete that failed inside a
best-effort reaper, a row purged while its object delete errored, a worker
killed between writing an object and committing the row that names it.

"Any row", not "the row whose id is in the key" — see `_reference_clause` for
why fan-out makes that distinction load-bearing rather than pedantic.

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
from typing import NamedTuple

import structlog
from sqlalchemy import or_, select, text
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

# Two budgets, both checked between provider pages, because the pass holds a
# transaction (and its connection) open for its advisory lock the whole time
# and a `staging/` prefix has no upper bound on an unhealthy deployment
# (fix(#1249) review r1). Leftovers are not urgent — they are already-leaked
# bytes, and the sweep runs every few minutes.
#
# Deletes: each one costs a row recheck plus an age re-read, so this bounds
# how long the lock is held once there IS work.
_MAX_DELETES_PER_PASS = 200
# Objects examined: bounds the walk when there is NOT. Without it a prefix of
# a million tracked-and-old objects would be paged through in full every
# cycle to delete nothing.
_MAX_OBJECTS_SCANNED_PER_PASS = 20_000

# Where the next pass resumes, per physical prefix (fix(#1249) review r2). A
# cap without a cursor is not a bound, it is a blind spot: every pass would
# re-walk the same lexicographically first window, and an orphan sorting after
# a window full of tracked, recent, or unattributable keys would never be
# reached at all.
#
# Advanced to the last key examined when a pass stops on a budget, and CLEARED
# when a walk reaches the end of the prefix — a completed walk has seen
# everything, so the next one starts at the front again.
#
# Process-local rather than a new persisted row, seeded at a RANDOM point the
# first time a process walks a given prefix. Both halves of that matter. Per
# process is enough because every pass is independently correct — the cursor
# only decides where to look first, never what may be deleted — so the worst a
# lost cursor costs is re-examining keys that were already cheap to skip. And
# seeding randomly is what keeps that true under `UVICORN_MAX_REQUESTS`
# recycling: a worker that restarts more often than a full walk completes would,
# from a fixed start, never reach the tail — the exact starvation the cursor
# exists to remove, reintroduced by the restart. From a random start, every
# region of the prefix is equally likely to be walked first, so coverage does
# not depend on any process living long enough to earn it.
_scan_cursors: dict[str, str | None] = {}


def _resume_point(physical_prefix: str) -> str | None:
    """Where this pass starts, seeding a random point on first use."""
    if physical_prefix not in _scan_cursors:
        # A uuid in the same alphabet as the job segment of every staging key,
        # so the seed lands uniformly inside the keyspace rather than before
        # or after all of it.
        _scan_cursors[physical_prefix] = f"{physical_prefix}{uuid.uuid4()}"
    return _scan_cursors[physical_prefix]


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


class _Candidate(NamedTuple):
    """One page entry the pass may act on, in the two forms it needs.

    The provider reports PHYSICAL keys (tenant-namespaced in multi-tenant
    mode); ``ingest_jobs.file_path`` and ``user_metadata->>'s3_key'``
    deliberately persist the tenant-agnostic LOGICAL form. Carrying both is
    what keeps the reference check from comparing one against the other.
    Ordered by physical key first so ``sorted()`` walks a page in provider
    order, which is what the resume cursor assumes.
    """

    physical_key: str
    logical_key: str
    job_id: uuid.UUID


@dataclass
class _Tally:
    """Mutable accumulator for one pass; frozen into the outcome at the end.

    The pass runs page by page and every helper contributes to the same
    numbers, so the counters are carried rather than returned and re-summed —
    which is how a helper's contribution gets dropped without anything failing.
    """

    objects_listed: int = 0
    orphans_deleted: int = 0
    delete_failures: int = 0
    skipped_recent: int = 0
    skipped_object_changed: int = 0
    skipped_row_appeared: int = 0
    skipped_unattributable: int = 0

    def as_log_fields(self) -> dict[str, int]:
        return self.freeze().as_log_fields()

    def freeze(self) -> StagingReconcileOutcome:
        return StagingReconcileOutcome(
            ran=True,
            objects_listed=self.objects_listed,
            orphans_deleted=self.orphans_deleted,
            delete_failures=self.delete_failures,
            skipped_recent=self.skipped_recent,
            skipped_object_changed=self.skipped_object_changed,
            skipped_row_appeared=self.skipped_row_appeared,
            skipped_unattributable=self.skipped_unattributable,
        )


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


def _reference_clause(job_id: uuid.UUID | None, logical_keys: set[str]):
    """Every way an ``ingest_jobs`` row can still need a staging object.

    fix(#1249 review r3, codex P1): the key's own job segment is NOT the whole
    ownership story, and the case that proves it is fan-out. ``create_fan_out_
    jobs`` clones the parent's ``file_path`` onto every child, so a child's
    only input is the PARENT's ``staging/{parent_id}/frozen/...`` object. The
    parent row reaches the retention cutoff on its own schedule — the purge's
    survivor query is what keeps the OBJECT alive for a still-pending,
    running, or retryable-failed child, not the parent's row. Reconciling on
    ``IngestJob.id`` alone would look up the purged parent, find nothing, and
    delete the input the child (or its retry) is about to read.

    So the question is "does any row still reference this key", asked of both
    columns that can hold one: ``file_path`` (the bound input, cloned onto
    fan-out children) and ``user_metadata->>'s3_key'`` (the client-writable
    upload key, also cloned wholesale onto children). Those are the only two
    places in the schema a `staging/` key is ever stored.

    Both comparisons are against the LOGICAL key. The provider reports
    physical keys, which carry the ``tenants/{id}/`` namespace in multi-tenant
    mode, while these columns deliberately persist the tenant-agnostic form.
    """
    clauses = [
        IngestJob.file_path.in_(logical_keys),
        IngestJob.user_metadata["s3_key"].astext.in_(logical_keys),
    ]
    if job_id is not None:
        clauses.insert(0, IngestJob.id == job_id)
    return or_(*clauses)


async def _staging_reference_exists(
    db: AsyncSession, job_id: uuid.UUID, logical_key: str
) -> bool:
    """Does any ``ingest_jobs`` row still need this staging object, right now?

    A fresh statement rather than a reuse of the batch query's result on
    purpose: under READ COMMITTED every statement takes its own snapshot, so
    this sees rows committed since that query — which is exactly the race it
    exists to catch. Core select over the id column, never an ORM object load,
    so the session's identity map cannot answer from a stale instance.
    """
    result = await db.execute(
        select(IngestJob.id).where(_reference_clause(job_id, {logical_key}))
    )
    return result.first() is not None


async def _current_entry(storage, physical_key: str) -> StoredObject | None:
    """Re-read one object's last-modified time, or None if it is gone.

    ``iter_object_pages`` with a COMPLETE key rather than a directory prefix:
    the Protocol has no head-with-timestamp call, and a prefix listing of one
    exact key is the portable way to ask every provider the same question. The
    entries are filtered for an exact match because a prefix listing also
    returns siblings whose keys merely start with this one.
    """
    async for page in storage.iter_object_pages(physical_key):
        for entry in page:
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
    """The pass body, entered only with the advisory lock held.

    Page at a time, and both budgets below are checked between pages, so the
    pass never holds more than one provider page in memory and never issues
    another listing round trip once it has enough work (fix(#1249) review r1).
    A pass that stops on a budget leaves a cursor behind so the next one
    resumes where it stopped rather than re-walking the same window forever
    (review r2 — see ``_scan_cursors``).
    """
    # Clock skew between this process and the object store is immaterial at a
    # threshold measured in hours, which is one more reason the threshold is
    # not a tuned estimate of transfer duration.
    cutoff = now - timedelta(seconds=settings.staging_orphan_min_age_seconds)
    tally = _Tally()
    last_examined: str | None = None
    stopped_early = False

    async for page in storage.iter_object_pages(
        physical_prefix, start_after=_resume_point(physical_prefix)
    ):
        tally.objects_listed += len(page)
        if page:
            # Pages arrive in ascending key order, so the last entry is the
            # high-water mark whether or not this page produced any deletes.
            last_examined = page[-1].key
        candidates = _page_candidates(
            page, physical_prefix=physical_prefix, cutoff=cutoff, tally=tally
        )
        if candidates:
            unfinished_at = await _delete_page_orphans(
                db,
                candidates,
                now=now,
                cutoff=cutoff,
                storage=storage,
                tally=tally,
            )
            if unfinished_at is not None:
                # The delete budget ran out partway through this page. Resume
                # from the last candidate actually PROCESSED, not from the end
                # of the page, so the ones it never reached are not skipped
                # until the walk wraps.
                last_examined = unfinished_at
        if (
            tally.orphans_deleted + tally.delete_failures >= _MAX_DELETES_PER_PASS
            or tally.objects_listed >= _MAX_OBJECTS_SCANNED_PER_PASS
        ):
            stopped_early = True
            log.info(
                "Staging orphan reconciliation stopped at its per-pass budget",
                resume_after=last_examined,
                **tally.as_log_fields(),
            )
            break

    # A completed walk has seen everything after its start point, so the next
    # pass begins at the front. Only a budget stop carries a resume point, and
    # only when the walk actually got somewhere — a budget stop with no page
    # yielded would otherwise clear the cursor and undo the pass's progress.
    if stopped_early and last_examined is not None:
        _scan_cursors[physical_prefix] = last_examined
    else:
        _scan_cursors[physical_prefix] = None

    if tally.orphans_deleted:
        # After the deletes returned, never before: the counter records
        # completed deletions, not intentions.
        staging_orphans_deleted_total.inc(tally.orphans_deleted)

    return tally.freeze()


def _page_candidates(
    page: list[StoredObject],
    *,
    physical_prefix: str,
    cutoff: datetime,
    tally: "_Tally",
) -> list["_Candidate"]:
    """Which entries on one page are old enough and attributable."""
    candidates: list[_Candidate] = []
    for entry in page:
        # Defensive: a provider that returned a key outside the prefix it was
        # asked for must not be trusted to name a deletable object.
        if not entry.key.startswith(physical_prefix):
            tally.skipped_unattributable += 1
            continue
        logical_key = STAGING_PREFIX + entry.key[len(physical_prefix) :]
        job_id = _job_id_from_key(logical_key)
        if job_id is None:
            tally.skipped_unattributable += 1
            continue
        if entry.last_modified >= cutoff:
            tally.skipped_recent += 1
            continue
        candidates.append(_Candidate(entry.key, logical_key, job_id))
    return candidates


async def _delete_page_orphans(
    db: AsyncSession,
    candidates: list["_Candidate"],
    *,
    now: datetime,
    cutoff: datetime,
    storage,
    tally: "_Tally",
) -> str | None:
    """Delete the unreferenced candidates from ONE page.

    Returns the last key it PROCESSED if the delete budget stopped it partway,
    so the caller can resume there rather than past the candidates it never
    reached; ``None`` when the whole page was worked through.
    """
    # One query per page, never per pass: the bound id/key sets are the page
    # the provider chose (1000 entries on S3 and Azure), so these expanding INs
    # can never approach the driver's bind-parameter ceiling no matter how
    # large the orphan backlog grows (fix(#1249) review r1). The per-object
    # recheck below is the authority; this only avoids paying for it per object
    # on a healthy bucket.
    logical_keys = {candidate.logical_key for candidate in candidates}
    referenced_rows = (
        await db.execute(
            select(
                IngestJob.id,
                IngestJob.file_path,
                IngestJob.user_metadata["s3_key"].astext,
            ).where(
                or_(
                    IngestJob.id.in_({c.job_id for c in candidates}),
                    IngestJob.file_path.in_(logical_keys),
                    IngestJob.user_metadata["s3_key"].astext.in_(logical_keys),
                )
            )
        )
    ).all()
    live_ids = {row_id for row_id, _file_path, _s3_key in referenced_rows}
    referenced_keys = {
        key
        for _row_id, file_path, s3_key in referenced_rows
        for key in (file_path, s3_key)
        if key
    }

    processed: str | None = None
    for candidate in sorted(candidates):
        physical_key, logical_key, job_id = candidate
        if job_id in live_ids or logical_key in referenced_keys:
            continue
        if tally.orphans_deleted + tally.delete_failures >= _MAX_DELETES_PER_PASS:
            return processed
        processed = physical_key
        # Deliberately OUTSIDE the try below. A database error here is not a
        # per-object problem to count and move past — it leaves the
        # transaction unusable, so every remaining candidate would "fail" on a
        # recheck that never ran. Let it reach the wrapper and end the pass.
        if await _staging_reference_exists(db, job_id, logical_key):
            tally.skipped_row_appeared += 1
            continue
        try:
            entry = await _current_entry(storage, physical_key)
            if entry is None or entry.last_modified >= cutoff:
                # Gone already, or rewritten since the listing. Either way
                # this pass has nothing it can honestly delete.
                tally.skipped_object_changed += 1
                continue
            await storage.delete(physical_key)
        except Exception:  # broad: best-effort per object, the pass continues
            tally.delete_failures += 1
            log.warning(
                "Failed to delete orphaned staging object",
                storage_key=physical_key,
                job_id=str(job_id),
            )
            continue
        tally.orphans_deleted += 1
        log.warning(
            "Deleted orphaned staging object no ingest job row references",
            storage_key=physical_key,
            job_id=str(job_id),
            last_modified=entry.last_modified.isoformat(),
            age_seconds=int((now - entry.last_modified).total_seconds()),
        )
    return None
