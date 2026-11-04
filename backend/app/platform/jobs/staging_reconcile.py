"""Reconcile real staging objects against ingest-job rows.

Every other staging reaper starts from a ROW and asks what object it owns.
This one starts from the OBJECT and asks whether any row still owns it — the
only direction that can see an object no row references at all.

Reconciliation rather than a wider deadline margin: S3 validates a
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
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.observability.metrics.jobs import staging_orphans_deleted_total
from app.platform.jobs.local_staging_reconcile import reconcile_orphaned_local_uploads
from app.platform.jobs.models import (
    STAGING_REAPED_FINAL_MARKER,
    STATUSES_NEEDING_STAGED_INPUT,
    IngestJob,
    needs_staged_input,
)
from app.platform.jobs.orphan_scan import current_entry, reconcile_orphan_objects
from app.platform.storage.provider import StoredObject

log = structlog.get_logger()

# The one prefix this sweep may delete under; everything below it in a BUCKET
# is namespaced by the job that wrote it (`staging/{job_id}/…`). "In a
# bucket" is load-bearing — the same prefix on LOCAL is not exclusively
# ours, so the pass runs on S3 storage only (see the gate in `_reconcile`).
STAGING_PREFIX = "staging/"

# Two budgets, checked between provider pages, because the
# pass holds its advisory-lock transaction open the whole time and a
# `staging/` prefix has no upper bound. Leftovers are not urgent — they are
# already-leaked bytes, and the sweep runs every few minutes.
# Deletes: each costs a row recheck plus an age re-read, bounding how long
# the lock is held once there IS work.
_MAX_DELETES_PER_PASS = 200
# Objects examined: bounds the walk when there is no work — without it a
# million tracked-and-old objects would be paged through every cycle for nothing.
_MAX_OBJECTS_SCANNED_PER_PASS = 20_000


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

    The key's own job segment is NOT the whole
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
    """Predicate: this row still needs the staged input it points at.

    A complete fan-out child names its parent's upload forever, so naming a key
    is not enough. Same line the retention purge's survivor query draws.
    """
    return needs_staged_input()


def _owner_still_manages():
    """Predicate: some mechanism OTHER than this sweep still owns the row's keys.

    The row whose id a staging key names is its lifecycle, not a reference —
    so the question is "is anything still going to act on this key". Exactly
    two things do:

    - The task tails and the retention purge, while the row is pending, running
      or failed.
    - ``_sweep_expired_presigned_staging``, while the row carries an ``s3_key``
      it has not yet finalized.

    Existence alone is no shield: a PUT that lands after the post-expiry
    sweep's final delete recreates an object every row-driven reaper is done
    with. A row holding an unarchived original keeps the key its
    ``file_path`` names through ``_can_still_consume``. With no ``file_path``
    the post-expiry sweep never finalizes it, so this keeps its ``s3_key``.

    The ``s3_key IS NOT NULL`` half matters as much as the marker half: a
    job that never presigned has no such key, so treating a missing marker
    as "not yet finalized" would shield those rows forever instead.
    """
    return or_(
        IngestJob.status.in_(STATUSES_NEEDING_STAGED_INPUT),
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


async def reconcile_orphaned_staging_objects(
    db: AsyncSession, *, now: datetime | None = None
) -> StagingReconcileOutcome:
    """Delete staging objects that no ``ingest_jobs`` row tracks.

    Read-only against ``db`` and never commits/rolls it back: a rollback
    would expire every ORM instance in the caller's identity map, leaving
    them unloadable. The advisory lock lives on its own session instead.

    The lock makes the counter honest: every API worker runs its own
    sweeper loop, and without it each would count the same delete N times
    under ``UVICORN_WORKERS>1``. Transaction-scoped, so a dying process
    releases it with its connection.

    Never raises: a mid-pass failure leaves the rest for the next cycle.

    Runs ``reconcile_orphaned_local_uploads`` first, since an upload staged on
    local disk is in no storage listing.
    """
    now = now or datetime.now(timezone.utc)
    await reconcile_orphaned_local_uploads(db, now=now)
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
    """The pass itself. See the wrapper above for the error and lock contract.

    Page at a time; both budgets are checked between pages, and a budget stop
    leaves a cursor so the next pass resumes (see ``orphan_scan``).
    """
    if settings.storage_provider != "s3":
        # `staging/` is exclusively the upload system's namespace only in a
        # BUCKET. On the local backend the same prefix also holds
        # operator-staged manifest seed files (`classify_manifest_source`), and
        # deleting one would destroy someone's input. Nothing is lost by
        # declining: presigned uploads refuse non-S3
        # backends, so this orphan class cannot occur on local or Azure.
        return StagingReconcileOutcome(ran=False)

    # Clock skew is immaterial at a threshold measured in hours.
    cutoff = now - timedelta(seconds=settings.staging_orphan_min_age_seconds)
    tally = _Tally()

    async def handle_page(storage, physical_prefix, page, previous_end):
        candidates = _page_candidates(
            page, physical_prefix=physical_prefix, cutoff=cutoff, tally=tally
        )
        # Pages arrive in ascending key order, so the last entry is the
        # high-water mark whether or not this page produced any deletes.
        resume_after = page[-1].key
        if candidates:
            unfinished_at = await _delete_page_orphans(
                db, candidates, now=now, cutoff=cutoff, storage=storage, tally=tally
            )
            if unfinished_at is not None:
                # Delete budget ran out partway through this page. Resume
                # from the last PROCESSED candidate, not the page's end.
                resume_after = unfinished_at
        return tally.orphans_deleted + tally.delete_failures < _MAX_DELETES_PER_PASS, (
            resume_after
        )

    progress = await reconcile_orphan_objects(
        prefix=STAGING_PREFIX,
        lock_name="staging-orphan-reconcile",
        handle_page=handle_page,
        max_objects=_MAX_OBJECTS_SCANNED_PER_PASS,
    )
    if progress is None:
        return StagingReconcileOutcome(ran=False)
    tally.objects_listed = progress.objects_listed
    if progress.stopped_early:
        log.info(
            "Staging orphan reconciliation stopped at its per-pass budget",
            resume_after=progress.resume_after,
            **tally.as_log_fields(),
        )
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
    # One query per page, not per pass — page size (1000 on
    # S3/Azure) keeps these INs under the bind-parameter ceiling. Same two
    # predicates as `_reference_clause`, not a Python re-derivation, so a
    # broader pre-filter can't hide candidates the recheck never sees.
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
            entry = await current_entry(storage, physical_key)
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
        # Published per delete, after it returned, so a later error can't
        # take this count with it.
        staging_orphans_deleted_total.inc()
        log.warning(
            "Deleted orphaned staging object no ingest job row references",
            storage_key=physical_key,
            job_id=str(job_id),
            last_modified=entry.last_modified.isoformat(),
            age_seconds=int((now - entry.last_modified).total_seconds()),
        )
    return None
