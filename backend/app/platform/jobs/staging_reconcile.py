"""Reconcile real staging objects against ingest-job rows (fix(#1249)).

Every other staging reaper starts from a ROW and asks what object it owns.
This one starts from the OBJECT and asks whether any row still owns it — the
only direction that can see an object no row references at all.

Reconciliation replaces margin-widening (#1235/#1236): S3 validates a
presigned signature when a request STARTS, not when it finishes, so an
accepted PUT can still be writing arbitrarily long after any deadline
derived from its URL. A HEAD-before-delete has the symmetric problem: it
proves absence when checked, not that it stays absent while the delete is
in flight. Reconciliation instead asks a question with a durable answer —
does any row still reference this key? — since a presigned URL is only ever
minted alongside the `ingest_jobs` row of that id, kept alive by the
retention purge past `MAX_PRESIGNED_URL_LIFETIME_SECONDS +
_RECHECK_TRANSFER_MARGIN_SECONDS`. It also catches orphans from other
causes: a failed best-effort delete, a row purged while its delete errored,
a worker killed between writing an object and committing its row.

"Still needs", not "still exists": a fan-out child's inherited `file_path`
(`_can_still_consume`) and the owning row's finished lifecycle
(`_owner_still_manages`) both need their own predicate, or an object
nothing will ever clean up survives, including the late-PUT leak this
module exists to close.

Two races, handled by construction:

1. An object uploaded after the listing snapshot: age is re-read from the
   provider immediately before delete, never trusted from the listing alone.
2. A row that lands after the batch row query: absence is re-checked per
   object, in its own statement, immediately before that object's delete.

Neither race can be closed by ordering alone — there is no atomic
"delete-if-still-unreferenced" across a database and an object store. Both
rechecks fail CLOSED (an ambiguous answer skips the object for the next
pass), so the only cost of a miss is a day of leaked bytes.
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

# The one prefix this sweep may delete under; everything below it in a BUCKET
# is namespaced by the job that wrote it (`staging/{job_id}/…`). "In a
# bucket" is load-bearing — the same prefix on LOCAL is not exclusively
# ours, so the pass runs on S3 storage only (see the gate in `_reconcile`).
STAGING_PREFIX = "staging/"

# fix(#1249): two budgets, checked between provider pages, because the
# pass holds its advisory-lock transaction open the whole time and a
# `staging/` prefix has no upper bound. Leftovers are not urgent — they are
# already-leaked bytes, and the sweep runs every few minutes.
# Deletes: each costs a row recheck plus an age re-read, bounding how long
# the lock is held once there IS work.
_MAX_DELETES_PER_PASS = 200
# Objects examined: bounds the walk when there is no work — without it a
# million tracked-and-old objects would be paged through every cycle for nothing.
_MAX_OBJECTS_SCANNED_PER_PASS = 20_000

# fix(#1249): where the next pass resumes, per physical prefix. Without
# it every pass re-walks the same lexicographically first window and an
# orphan sorting later would never be reached. Advanced to the last key
# examined on a budget stop, cleared when a pass completes the whole prefix.
# CIRCULAR scan (`_reconcile_locked`) makes this an OFFSET, not a window, so
# process-local state seeded at a random point is safe: the cursor only
# decides what is looked at first, never what may be deleted.
_scan_cursors: dict[str, str | None] = {}


def _resume_point(physical_prefix: str) -> str | None:
    """Where this pass starts, seeding a random point on first use."""
    if physical_prefix not in _scan_cursors:
        # Same alphabet as the job segment of every staging key, so the seed
        # lands uniformly inside the keyspace rather than before/after all of it.
        _scan_cursors[physical_prefix] = f"{physical_prefix}{uuid.uuid4()}"
    return _scan_cursors[physical_prefix]


@dataclass(frozen=True)
class StagingReconcileOutcome:
    """What one reconciliation pass saw and did."""

    # False when the pass declined entirely: another process holds the lock,
    # or multi-tenant mode gave no tenant context to scope the prefix.
    ran: bool = False
    objects_listed: int = 0
    orphans_deleted: int = 0
    delete_failures: int = 0
    # Skips, each meaning something different: recent (younger than the
    # threshold at listing), object_changed (race #1: gone/rewritten before
    # delete), row_appeared (race #2: a row appeared), unattributable
    # (owning job cannot be named).
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

    Provider keys are PHYSICAL (tenant-namespaced); ``ingest_jobs.file_path``
    persists the tenant-agnostic LOGICAL form. Carrying both avoids comparing
    one against the other. Ordered physical-key-first so ``sorted()`` matches
    provider order, which the resume cursor assumes.
    """

    physical_key: str
    logical_key: str
    job_id: uuid.UUID


@dataclass
class _Tally:
    """Mutable accumulator for one pass; frozen into the outcome at the end.

    Counters are carried, not returned and re-summed, so a helper's
    contribution can't silently get dropped.
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

    None for anything not shaped like a job-owned staging key. An
    unparseable key is never deleted: this sweep only destroys objects it
    can positively attribute to an absent row.
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

    fix(#1249): the key's own job segment is NOT the whole
    ownership story — fan-out proves it. ``create_fan_out_jobs`` clones the
    parent's ``file_path`` onto every child, so a child's only input is the
    PARENT's frozen object; the purge's survivor query keeps that object
    alive for a still-pending/running/retryable child, not the parent's row.
    Reconciling on ``IngestJob.id`` alone would find the purged parent gone
    and delete the input the child is about to read.

    So "does any row still NEED this key" is two questions —
    ``_owner_still_manages`` for the row whose id the key names,
    ``_can_still_consume`` for every other row.

    ``user_metadata->>'s3_key'`` is deliberately NOT consulted: it is cloned
    onto fan-out children wholesale, and an inherited copy is not ownership.

    Comparisons are against the LOGICAL key, since the provider reports
    PHYSICAL (tenant-namespaced) keys while ``file_path`` stays tenant-agnostic.
    """
    clauses = [and_(IngestJob.file_path.in_(logical_keys), _can_still_consume())]
    if job_id is not None:
        clauses.insert(0, and_(IngestJob.id == job_id, _owner_still_manages()))
    return or_(*clauses)


def _can_still_consume():
    """Predicate: this row can still read the staged input it points at.

    fix(#1249): unconditional was wrong — a fan-out child stays
    ``complete`` forever, so its inherited ``file_path`` would answer "still
    referenced" forever and the leaked parent object could never be
    repaired. Same line the retention purge's survivor query draws.
    """
    return IngestJob.status.in_(STATUSES_NEEDING_STAGED_INPUT)


def _owner_still_manages():
    """Predicate: some mechanism OTHER than this sweep still owns the row's keys.

    The row whose id a staging key names is its lifecycle, not a reference —
    so the question is "is anything still going to act on this key". Exactly
    two things do:

    - The task tails and the retention purge, while the row can still consume
      the bytes (``_can_still_consume``).
    - ``_sweep_expired_presigned_staging``, while the row carries an ``s3_key``
      it has not yet finalized.

    fix(#1249): existence alone was a permanent shield, and it
    shielded the exact leak this change closes — a PUT landing after the
    post-expiry sweep's final delete recreates an object every row-driven
    reaper is finished with.

    The ``s3_key IS NOT NULL`` half matters as much as the marker half: a
    job that never presigned has no such key, so treating a missing marker
    as "not yet finalized" would shield those rows forever instead.
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

    A fresh statement, not a reuse of the batch query's result: READ
    COMMITTED gives it its own snapshot, catching rows committed since. Core
    select over the id, never an ORM load, so the identity map can't answer stale.
    """
    result = await db.execute(
        select(IngestJob.id).where(_reference_clause(job_id, {logical_key}))
    )
    return result.first() is not None


async def _current_entry(storage, physical_key: str) -> StoredObject | None:
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


async def reconcile_orphaned_staging_objects(
    db: AsyncSession, *, now: datetime | None = None
) -> StagingReconcileOutcome:
    """Delete staging objects that no ``ingest_jobs`` row tracks.

    Read-only against ``db`` and never commits/rolls it back: a rollback
    would expire every ORM instance in the caller's identity map, leaving
    them unloadable. The advisory lock lives on its own session instead.

    The lock makes the counter honest — every API worker runs its own
    sweeper loop, and without it each would count the same delete N times
    under ``UVICORN_WORKERS>1`` (#1240's fabricated-number class).
    Transaction-scoped, so a dying process releases it with its connection.

    Never raises: a mid-pass failure leaves the rest for the next cycle.
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
        # fix(#1249): `staging/` is exclusively the upload
        # system's namespace only in a BUCKET. On the local backend the same
        # prefix also holds operator-staged manifest seed files
        # (`classify_manifest_source`) — deleting one there is not a leaked
        # byte, it is someone's input. Nothing is lost by declining: presigned
        # uploads refuse non-S3 backends, so this module's orphan class
        # cannot occur on local or Azure.
        return StagingReconcileOutcome(ran=False)

    if is_multi_tenant() and current_tenant_var.get() is None:
        # No tenant context to scope the listing. Declining is the only safe
        # answer — sweeping the whole bucket while RLS shows no rows would
        # read every tenant's objects as untracked (same posture as
        # `_stale_generation_storage_keys` in sweep.py).
        return StagingReconcileOutcome(ran=False)

    # Resolves the ACTIVE tenant's namespace in multi-tenant mode, so the
    # listing can never cross a tenant boundary.
    physical_prefix = resolve_current_storage_key(STAGING_PREFIX)

    # A session that exists only to hold the lock; touches no table, so RLS
    # is irrelevant. Leaving the context ends its transaction and releases
    # the lock without touching anything the caller's ``db`` owns.
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

    Page at a time; both budgets are checked between pages (fix(#1249) r1). A
    budget stop leaves a cursor so the next pass resumes rather than
    re-walking the same window (r2 — see ``_scan_cursors``).

    The scan is CIRCULAR (r7, codex P2): cursor to end, then front to cursor
    with whatever budget is left. A one-directional scan from a random start
    is a sample, not a rotation — a recycled worker would only ever see
    suffixes. With the wrap, one unbudgeted pass covers the whole prefix.
    """
    # Clock skew is immaterial at a threshold measured in hours — one more
    # reason the threshold isn't a tuned estimate of transfer duration.
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
                    # Delete budget ran out partway through this page. Resume
                    # from the last PROCESSED candidate, not the page's end.
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

    # A full pass has seen the whole prefix, so the next starts at the front.
    # Only a budget stop with actual progress carries a resume point — one
    # with no page yielded would otherwise clear the cursor and undo progress.
    if stopped_early and last_examined is not None:
        _scan_cursors[physical_prefix] = last_examined
    else:
        _scan_cursors[physical_prefix] = None

    return tally.freeze()


async def _iter_leg(storage, physical_prefix: str, *, start_after, stop_at):
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
    # fix(#1249): one query per page, not per pass — page size (1000 on
    # S3/Azure) keeps these INs under the bind-parameter ceiling. Same two
    # predicates as `_reference_clause`, not a Python re-derivation, so a
    # broader pre-filter can't hide candidates the recheck never sees (r4/r6).
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
        # Deliberately OUTSIDE the try below — a DB error here leaves the
        # transaction unusable, so let it reach the wrapper and end the pass.
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
        # fix(#1249): published here, not batched to the pass
        # end — the object is already gone, so a later error must not take
        # this count with it. Runs strictly after the delete returned, so it
        # counts completions, not intentions.
        staging_orphans_deleted_total.inc()
        log.warning(
            "Deleted orphaned staging object no ingest job row references",
            storage_key=physical_key,
            job_id=str(job_id),
            last_modified=entry.last_modified.isoformat(),
            age_seconds=int((now - entry.last_modified).total_seconds()),
        )
    return None
