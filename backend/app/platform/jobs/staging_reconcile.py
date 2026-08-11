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

"Still needs", not "still exists", and the difference took two review rounds
to get right in both directions: a fan-out child's inherited `file_path`
(`_can_still_consume`) and the owning row's own finished lifecycle
(`_owner_still_manages`). Either read as an unconditional shield leaves an
object nothing will ever clean up, including — in the second case — the very
late-PUT leak this module exists to close.

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
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.observability.metrics.jobs import staging_orphans_deleted_total
from app.platform.jobs.models import (
    STAGING_REAPED_FINAL_MARKER,
    STATUSES_NEEDING_STAGED_INPUT,
    IngestJob,
)
from app.platform.storage.provider import StoredObject
from app.platform.storage.titiler_url import resolve_current_storage_key

log = structlog.get_logger()

# The one prefix this sweep may delete under. Everything below it in a BUCKET
# is written by the upload system and namespaced by the job that wrote it
# (`staging/{job_id}/…`, plus the `frozen/` snapshot under the same job
# segment); `manifest_sources.py` refuses operator-declared s3:// keys here for
# exactly that reason. Nothing outside this prefix is ever listed, so no object
# the upload system does not own can reach the delete path.
#
# "In a bucket" is load-bearing — the same prefix on the LOCAL backend is not
# exclusively ours, which is why the pass runs on S3 storage only. See the
# provider gate in `_reconcile`.
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
# when a pass gets all the way round — it has seen the whole prefix, so the
# next one may as well start at the front.
#
# The scan is CIRCULAR (see `_reconcile_locked`), which is what makes this
# cursor a starting OFFSET rather than a window: an unbudgeted pass covers the
# whole prefix from wherever it begins. That is why process-local state is
# enough here, and why it is seeded at a random point rather than at the front
# (fix(#1249) review r2/r7). Every pass is independently correct — the cursor
# never decides what may be deleted, only what is looked at first — so the
# worst a lost cursor costs is re-examining keys that were already cheap to
# skip, and a worker recycled under `UVICORN_MAX_REQUESTS` before its next pass
# does not keep restarting its coverage from the same place.
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

    So the question is "does any row still NEED this key", which is two
    different questions with two different answers — ``_owner_still_manages``
    for the row whose id the key names, ``_can_still_consume`` for every other
    row. Neither is "a row exists", and both took a review round to learn.

    ``user_metadata->>'s3_key'`` is deliberately NOT consulted as a reference.
    It is cloned onto fan-out children wholesale, and
    ``owned_presigned_staging_key`` already settles that an inherited copy is
    not ownership; the only row for which it IS ownership is the one whose id
    the key names, which the first branch covers.

    Comparisons are against the LOGICAL key. The provider reports physical
    keys, which carry the ``tenants/{id}/`` namespace in multi-tenant mode,
    while ``file_path`` deliberately persists the tenant-agnostic form.
    """
    clauses = [and_(IngestJob.file_path.in_(logical_keys), _can_still_consume())]
    if job_id is not None:
        clauses.insert(0, and_(IngestJob.id == job_id, _owner_still_manages()))
    return or_(*clauses)


def _can_still_consume():
    """Predicate: this row can still read the staged input it points at.

    fix(#1249 review r4, codex P2): a reference is only a reference while the
    row can act on it. Unconditional was wrong in the direction that never
    self-corrects — a fan-out child stays ``complete`` forever and is exempt
    from retention indefinitely as a dataset's latest complete job, so its
    inherited ``file_path`` would answer "still referenced" on every future
    pass and the leaked parent object could never be repaired. Same line the
    retention purge's own survivor query draws, read from one place so the two
    cannot drift.
    """
    return IngestJob.status.in_(STATUSES_NEEDING_STAGED_INPUT)


def _owner_still_manages():
    """Predicate: some mechanism OTHER than this sweep still owns the row's keys.

    The row whose id a staging key names is not a reference to it, it is its
    lifecycle — so the question for that row is not "does it exist" but "is
    anything still going to act on this key". Exactly two things do:

    - The task tails and the retention purge, while the row can still consume
      the bytes (``_can_still_consume``).
    - ``_sweep_expired_presigned_staging``, while the row carries an ``s3_key``
      it has not yet finalized.

    fix(#1249 review r6, codex P2): existence alone was a permanent shield, and
    it shielded the exact leak this whole change exists to close. Once the
    post-expiry sweep sets ``STAGING_REAPED_FINAL_MARKER`` it never looks at
    that key again; if the row is also its dataset's latest complete job, the
    retention purge exempts it indefinitely. A PUT that lands after that final
    delete recreates an object that every row-driven reaper is now finished
    with — and, before this predicate, one this reconciler declined forever
    because the row was still there.

    The ``s3_key IS NOT NULL`` half matters as much as the marker half: a
    direct upload (or any job that never presigned) has no such key, so the
    presigned sweep will never set a marker on it, and treating a missing
    marker as "not yet finalized" would shield those rows forever instead.
    """
    return or_(
        _can_still_consume(),
        and_(
            IngestJob.user_metadata["s3_key"].astext.is_not(None),
            IngestJob.user_metadata[STAGING_REAPED_FINAL_MARKER].astext.is_(None),
        ),
    )


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

    if settings.storage_provider != "s3":
        # fix(#1249 review r8, codex P1): `staging/` is the upload system's
        # exclusive namespace in a BUCKET, and only in a bucket. On the local
        # backend the same prefix sits inside `upload_staging_dir`, which is
        # also where an operator stages manifest seed files — a local manifest
        # source spelled `staging/{anything}/seed.geojson` resolves to an
        # absolute path under that directory whenever the directory's basename
        # is not itself `staging` (see `classify_manifest_source`). Those files
        # are operator-owned, are legitimately staged BEFORE the manifest that
        # names them is applied, and are stored as absolute paths that no
        # logical-key comparison here would ever match. Deleting one is not a
        # leaked byte, it is someone's input.
        #
        # Nothing is lost by declining: presigned uploads refuse anything but
        # the S3 backend at request time, so the late-PUT orphan this module
        # exists for cannot occur on local or Azure storage at all. The s3://
        # manifest branch closes the mirror-image hole by refusing `staging/`
        # keys outright (`_storage_uri_to_key`), which is what makes the bucket
        # prefix exclusively ours in the first place.
        return StagingReconcileOutcome(ran=False)

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

    The scan is CIRCULAR (review r7, codex P2): it walks from the cursor to the
    end of the prefix and then, with whatever budget is left, from the front of
    the prefix back up to the cursor. A one-directional scan from a random
    start is not a rotation, it is a sample — a worker recycled before its next
    pass would only ever see suffixes, and an orphan sorting near the front of
    a large prefix would be reached with probability ~1/(objects+1) per
    restart. With the wrap, one unbudgeted pass covers the whole prefix and the
    cursor only decides where it starts.
    """
    # Clock skew between this process and the object store is immaterial at a
    # threshold measured in hours, which is one more reason the threshold is
    # not a tuned estimate of transfer duration.
    cutoff = now - timedelta(seconds=settings.staging_orphan_min_age_seconds)
    tally = _Tally()
    last_examined: str | None = None
    stopped_early = False

    resume_point = _resume_point(physical_prefix)
    # (start_after, stop_at). The second leg is the wrap and is skipped when
    # the pass already begins at the front, where there is nothing to wrap to.
    legs: list[tuple[str | None, str | None]] = [(resume_point, None)]
    if resume_point is not None:
        legs.append((None, resume_point))

    for start_after, stop_at in legs:
        async for page in _iter_leg(
            storage, physical_prefix, start_after=start_after, stop_at=stop_at
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
                    # The delete budget ran out partway through this page.
                    # Resume from the last candidate actually PROCESSED, not
                    # from the end of the page, so the ones it never reached
                    # are not skipped until the next lap.
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
        if stopped_early:
            break

    # A pass that got all the way round has seen the whole prefix, so the next
    # one may as well start at the front. Only a budget stop carries a resume
    # point, and only when the walk actually got somewhere — a budget stop with
    # no page yielded would otherwise clear the cursor and undo the progress.
    if stopped_early and last_examined is not None:
        _scan_cursors[physical_prefix] = last_examined
    else:
        _scan_cursors[physical_prefix] = None

    return tally.freeze()


async def _iter_leg(storage, physical_prefix: str, *, start_after, stop_at):
    """Pages of one leg of the circular scan, bounded above by ``stop_at``.

    The wrap leg must not run past the point the pass started from, or it would
    re-examine the keys the first leg already covered instead of ending.
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
    # Two halves of `_reference_clause`, asked in bulk with the SAME two
    # predicates rather than a Python re-derivation of them — a pre-filter that
    # shields more than the recheck would silently skip candidates the recheck
    # never gets to see, which is how r4 and r6 each hid a permanent leak.
    logical_keys = {candidate.logical_key for candidate in candidates}
    shielding_ids = set(
        (
            await db.execute(
                select(IngestJob.id).where(
                    IngestJob.id.in_({c.job_id for c in candidates}),
                    _owner_still_manages(),
                )
            )
        ).scalars()
    )
    referenced_keys = set(
        (
            await db.execute(
                select(IngestJob.file_path).where(
                    IngestJob.file_path.in_(logical_keys), _can_still_consume()
                )
            )
        ).scalars()
    )

    processed: str | None = None
    for candidate in sorted(candidates):
        physical_key, logical_key, job_id = candidate
        if job_id in shielding_ids or logical_key in referenced_keys:
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
        # Published here rather than once at the end of the pass (fix(#1249)
        # review r5, codex P2). The object is already gone, so a later page
        # listing or database error that ends the pass must not take this
        # number with it — nothing can recover the count afterwards, and a
        # counter that silently under-reports completed cleanup is worse than
        # one incremented a few statements earlier. The durability rule is
        # unchanged: this runs strictly after the provider's delete returned,
        # so it still counts completions rather than intentions.
        staging_orphans_deleted_total.inc()
        log.warning(
            "Deleted orphaned staging object no ingest job row references",
            storage_key=physical_key,
            job_id=str(job_id),
            last_modified=entry.last_modified.isoformat(),
            age_seconds=int((now - entry.last_modified).total_seconds()),
        )
    return None
