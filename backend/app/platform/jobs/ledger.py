"""The job ledger: the ``ingest_jobs`` transitions no worker makes.

``hold`` locks a job in the state its caller expects. ``abort`` fails a job no
worker holds, ``cancel`` ends a pending or running job at a user's request,
``end_stale`` ends a job the stale pass found, and ``retry`` returns a failed
job to pending under a new attempt. Each fences on the attempt its caller read
and writes nothing on a miss.

Rows linked to a job stay with their owners. When an end lands, each owner's
``job_ended`` hook settles its rows in the same transaction, after the job row
is locked, and a hook that raises takes the job write back with it. Once per
stale pass, each owner's ``stale_pass`` settles the rows it proves stale
itself.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, inspect as sa_inspect, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.failure_reason import FixedReason, redact_failure_reason
from app.platform.jobs.models import IngestJob

# The three VRT regeneration doors create their job under this filename, and
# nothing else does.
VRT_REGENERATE_JOB_FILENAME = "vrt_regenerate"

# The URL import commits its row ``running`` before it dispatches.
_ABORTABLE_STATUSES = ("pending", "running")

# What a user's cancel stores on the job, and on a VRT generation it releases.
_CANCEL_REASON = FixedReason("Cancelled by user")

# The job's columns an owner's hook reads when an end lands.
_END_COLUMNS = ("dataset_id", "source_filename", "user_metadata", "created_by")


class Outcome(enum.Enum):
    """What a ledger write did. Every value except ``LANDED`` wrote nothing."""

    LANDED = "landed"
    MISSING = "missing"
    MOVED = "moved"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class JobEnd:
    """A job end that landed, as the rows linked to the job see it.

    ``transition`` is the ledger call that ended the job: ``abort``,
    ``cancel`` or ``settle_stale``. ``actor`` is whoever ended it, or None
    for its creator.
    """

    job_id: uuid.UUID
    dataset_id: uuid.UUID | None
    source_filename: str | None
    user_metadata: dict[str, Any] | None
    created_by: uuid.UUID | None
    transition: str
    status: str
    code: str
    reason: str
    at: datetime
    actor: uuid.UUID | None
    ip_address: str | None


JobEndHook = Callable[[AsyncSession, JobEnd], Awaitable[uuid.UUID | None]]
"""Settles one owner's rows for a landed end; returns the row it ended, if any."""


@dataclass(frozen=True, slots=True)
class StalePassResult:
    """What owners' stale passes settled, for the pass's outcome and reaper."""

    vrt_assets_recovered: int = 0
    vrt_generations_failed: int = 0
    refresh_runs_cancelled: int = 0
    storage_keys: tuple[str, ...] = ()

    def __add__(self, other: StalePassResult) -> StalePassResult:
        return StalePassResult(
            self.vrt_assets_recovered + other.vrt_assets_recovered,
            self.vrt_generations_failed + other.vrt_generations_failed,
            self.refresh_runs_cancelled + other.refresh_runs_cancelled,
            self.storage_keys + other.storage_keys,
        )


StalePass = Callable[
    [AsyncSession, datetime, Sequence[uuid.UUID] | None], Awaitable[StalePassResult]
]


@dataclass(frozen=True, slots=True)
class LinkedOwner:
    """An owner of rows a job end would strand.

    ``job_ended`` runs for each end that lands. ``stale_pass``, when an owner
    has one, runs once per stale pass after its ends, for rows whose
    staleness the owner proves by its own rule.
    """

    job_ended: JobEndHook
    stale_pass: StalePass | None = None


@dataclass(frozen=True, slots=True)
class Ended:
    """A job end's outcome, and the linked rows its hooks ended, by owner."""

    outcome: Outcome
    linked: Mapping[str, uuid.UUID] = field(default_factory=dict)


def _attempt_is(attempt_id: uuid.UUID | None):
    return (
        IngestJob.attempt_id == attempt_id
        if attempt_id is not None
        else IngestJob.attempt_id.is_(None)
    )


def _mirror(job: IngestJob, values: Mapping[str, Any]) -> None:
    """Show the caller's instance what landed, without a reload or a flush."""
    if sa_inspect(job, raiseerr=False) is not None:
        for key, value in values.items():
            set_committed_value(job, key, value)


async def hold(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    expect: str,
    attempt_id: uuid.UUID | None = None,
) -> IngestJob | None:
    """Lock the job row and return it while it is in ``expect``.

    ``attempt_id``, when given, must still own the row. A miss returns None
    and writes nothing. The lock lasts until the caller's transaction ends
    either way, so a caller can check linked rows under it. The row is read
    from the database, never from the session's identity map.
    """
    job = await session.scalar(
        select(IngestJob)
        .where(IngestJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None or job.status != expect:
        return None
    if attempt_id is not None and job.attempt_id != attempt_id:
        return None
    return job


async def abort(
    session: AsyncSession,
    job: IngestJob,
    *,
    code: str,
    reason: str | BaseException,
    expect: str = "pending",
    ip_address: str | None = None,
) -> Outcome:
    """Fail a job no worker holds, fenced on ``expect`` and ``job``'s attempt.

    ``code`` names the cause for linked rows, such as a run's ``error_code``.
    ``reason`` is stored redacted. ``ip_address`` is the request behind the
    end, when there is one.

    Only ``job.id`` and ``job.attempt_id`` are read off the instance, so a
    session reset that expired the rest does not stop it. When the write
    lands, the new state is mirrored onto the instance. The write and the
    hooks share a SAVEPOINT, so a hook that raises rolls back the job row and
    every earlier hook's rows before the error propagates. Does not commit.
    """
    if expect not in _ABORTABLE_STATUSES:
        raise ValueError(f"abort cannot end a job from {expect!r}")
    ended = await _end(
        session,
        job.id,
        job.attempt_id,
        expect=(expect,),
        transition="abort",
        status="failed",
        code=code,
        reason=reason,
        actor=None,
        ip_address=ip_address,
        mirror=job,
    )
    return ended.outcome


async def cancel(session: AsyncSession, job: IngestJob, *, actor: uuid.UUID) -> Ended:
    """End a pending or running job at ``actor``'s request, fenced on its attempt.

    Needs no proof that the work stopped. A worker's finalize fences on the
    same row, so once the cancel commits, a late swap matches nothing and
    rolls back. ``Ended.linked["run"]`` is the refresh run the cancel ended.

    Sets a 2 s ``lock_timeout`` for the rest of the caller's transaction, so
    when a finalize holds the row this raises the lock-timeout error, having
    written nothing, instead of waiting out the swap. Reads the instance and
    shares a SAVEPOINT with its hooks as ``abort`` does. Does not commit.
    """
    from app.platform.refresh.service import USER_CANCELLED_ERROR_CODE

    await session.execute(text("SET LOCAL lock_timeout = '2s'"))
    return await _end(
        session,
        job.id,
        job.attempt_id,
        expect=("pending", "running"),
        transition="cancel",
        status="cancelled",
        code=USER_CANCELLED_ERROR_CODE,
        reason=_CANCEL_REASON,
        actor=actor,
        ip_address=None,
        mirror=job,
    )


async def end_stale(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID | None,
    *,
    expect: str,
    still_stale: Sequence[Any],
    status: str,
    code: str,
    reason: str,
    values: Mapping[str, Any] | None = None,
) -> Ended:
    """End one job the stale pass found, fenced on the status and attempt it read.

    ``still_stale`` is the pass's predicate for the job's class, checked again
    under the row lock, so a job that was claimed, restaged or retried since
    the pass read it is left alone. ``values`` are further columns the end
    writes. The owners whose rows have their own staleness rule leave them to
    their stale pass. Does not commit.
    """
    return await _end(
        session,
        job_id,
        attempt_id,
        expect=(expect,),
        transition="settle_stale",
        status=status,
        code=code,
        reason=reason,
        actor=None,
        ip_address=None,
        recheck=still_stale,
        values=values,
    )


async def run_stale_passes(
    session: AsyncSession,
    now: datetime,
    *,
    job_ids: Sequence[uuid.UUID] | None = None,
) -> StalePassResult:
    """Run each owner's stale pass once, after the stale pass's job ends.

    ``job_ids`` limits every owner to the rows linked to those jobs. Does not
    commit.
    """
    settled = StalePassResult()
    for owner in _OWNERS.values():
        if owner.stale_pass is not None:
            settled += await owner.stale_pass(session, now, job_ids)
    return settled


async def _end(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID | None,
    *,
    expect: tuple[str, ...],
    transition: str,
    status: str,
    code: str,
    reason: str | BaseException,
    actor: uuid.UUID | None,
    ip_address: str | None,
    recheck: Sequence[Any] = (),
    values: Mapping[str, Any] | None = None,
    mirror: IngestJob | None = None,
) -> Ended:
    """Write one fenced end and, when it lands, run every owner's hook on it.

    What landed is mirrored onto ``mirror``, or else onto the session's own
    instance of the row, if it holds one.
    """
    reason = redact_failure_reason(reason)
    now = datetime.now(timezone.utc)
    written = {"status": status, "error_message": reason, "completed_at": now}
    written.update(values or {})
    linked: dict[str, uuid.UUID] = {}
    async with session.begin_nested():
        ended = (
            await session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job_id,
                    IngestJob.status.in_(expect),
                    _attempt_is(attempt_id),
                    *recheck,
                )
                .values(**written)
                .returning(
                    *(
                        getattr(IngestJob, column)
                        for column in dict.fromkeys((*_END_COLUMNS, *written))
                    )
                )
                .execution_options(synchronize_session=False)
            )
        ).one_or_none()
        if ended is not None:
            end = JobEnd(
                job_id=job_id,
                dataset_id=ended.dataset_id,
                source_filename=ended.source_filename,
                user_metadata=ended.user_metadata,
                created_by=ended.created_by,
                transition=transition,
                status=status,
                code=code,
                reason=reason,
                at=now,
                actor=actor,
                ip_address=ip_address,
            )
            for name, owner in _OWNERS.items():
                row_id = await owner.job_ended(session, end)
                if row_id is not None:
                    linked[name] = row_id
    if ended is None:
        return Ended(await _missed(session, job_id, attempt_id))
    if mirror is None:
        mirror = session.identity_map.get(session.identity_key(IngestJob, job_id))
    if mirror is not None:
        _mirror(mirror, {column: ended._mapping[column] for column in written})
    return Ended(Outcome.LANDED, linked)


async def retry(session: AsyncSession, job: IngestJob) -> Outcome:
    """Return a failed job to pending under a new attempt, fenced on ``job``'s.

    Clears what the failed attempt left: its reason, its clocks and its
    dataset binding. ``staged_at`` is stamped now, because the stale-pending
    sweep ages a pending row from it and an hour-old failure would otherwise
    be stale the moment the retry commits. A late worker on the old attempt
    then matches no row. When the write lands, the new state, new attempt
    included, is mirrored onto the instance. Ends no linked rows, and does
    not commit.
    """
    job_id, attempt_id = job.id, job.attempt_id
    retried_at = datetime.now(timezone.utc)
    retried = (
        await session.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job_id,
                IngestJob.status == "failed",
                _attempt_is(attempt_id),
            )
            .values(
                status="pending",
                attempt_id=uuid.uuid4(),
                error_message=None,
                started_at=None,
                heartbeat_at=None,
                completed_at=None,
                dataset_id=None,
                user_metadata=func.coalesce(
                    IngestJob.user_metadata, text("'{}'::jsonb")
                ).op("||", return_type=JSONB)(
                    func.jsonb_build_object("staged_at", retried_at.isoformat())
                ),
            )
            .returning(
                IngestJob.status,
                IngestJob.attempt_id,
                IngestJob.error_message,
                IngestJob.started_at,
                IngestJob.heartbeat_at,
                IngestJob.completed_at,
                IngestJob.dataset_id,
                IngestJob.user_metadata,
            )
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    if retried is None:
        return await _missed(session, job_id, attempt_id)
    _mirror(job, retried._mapping)
    return Outcome.LANDED


async def _missed(
    session: AsyncSession, job_id: uuid.UUID, attempt_id: uuid.UUID | None
) -> Outcome:
    """Why a fenced write matched no row, as the row reads now."""
    row = (
        await session.execute(
            select(IngestJob.status, IngestJob.attempt_id).where(IngestJob.id == job_id)
        )
    ).one_or_none()
    if row is None:
        return Outcome.MISSING
    if row.attempt_id != attempt_id:
        return Outcome.SUPERSEDED
    return Outcome.MOVED


async def release_vrt_regeneration(
    session: AsyncSession, dataset_id: uuid.UUID, now: datetime, *, message: str
) -> uuid.UUID | None:
    """Release the VRT state an ended ``vrt_regenerate`` job would strand.

    VRT dispatch commits a ``pending`` VrtGeneration and flips the RasterAsset
    to ``regenerating`` before it defers the job, and that status 409-blocks
    every later regenerate, add-source and remove-source call. A job that ends
    before a worker publishes would leave it blocked until
    ``sweep_stale_vrt_assets``' cutoff.

    Runs in the transaction that ended the job, after the job write landed, as
    guarded conditional updates:

    - The generation flips to ``failed`` (its CHECK has no ``cancelled``)
      only from ``pending`` or ``running``. A terminal generation means
      another actor finished first, and nothing here is touched.
    - The asset restore uses the sweep's ``_READY_WORTHY_SQL`` branches:
      ``ready`` only when the published member set still matches the catalog
      and the prior attempt didn't fail, else ``failed``. Either branch clears
      ``current_generation_id``, so the 409 block lifts at once.
    - A worker's publish carries its fenced job-complete update, so it either
      committed before the job ended or rolls back at the fence. A late
      arrival on either side matches no row.

    The caller holds the job row, locked first as every worker phase does.
    Returns the generation it failed, if any.
    """
    # platform reaches processing only at call time; the sweep imports the
    # run module, which imports this one.
    from app.platform.jobs.sweep import _READY_WORTHY_SQL
    from app.processing.raster.models import RasterAsset, VrtGeneration

    pointer = await session.scalar(
        select(RasterAsset.current_generation_id).where(
            RasterAsset.dataset_id == dataset_id,
            RasterAsset.status == "regenerating",
        )
    )
    if pointer is None:
        # Nothing in flight: already published or already reconciled.
        return None
    generation_cas = await session.execute(
        update(VrtGeneration)
        .where(
            VrtGeneration.id == pointer,
            VrtGeneration.status.in_(("pending", "running")),
        )
        .values(
            status="failed",
            completed_at=now,
            error_message=redact_failure_reason(message),
        )
        .returning(VrtGeneration.id)
    )
    if generation_cas.scalar_one_or_none() is None:
        # The pointed-at generation is already terminal: another actor's
        # record stands, and the asset is that actor's to reconcile.
        return None
    asset_predicate = (
        RasterAsset.dataset_id == dataset_id,
        RasterAsset.status == "regenerating",
        RasterAsset.current_generation_id == pointer,
    )
    restored = await session.execute(
        update(RasterAsset)
        .where(*asset_predicate, text(_READY_WORTHY_SQL))
        .values(status="ready", current_generation_id=None)
        .returning(RasterAsset.dataset_id)
    )
    if restored.scalar_one_or_none() is None:
        await session.execute(
            update(RasterAsset)
            .where(*asset_predicate, text(f"NOT ({_READY_WORTHY_SQL})"))
            .values(status="failed", current_generation_id=None)
        )
    return pointer


# Each hook imports its owner at call time: the run module imports this one.
async def _end_refresh_run(session: AsyncSession, end: JobEnd) -> uuid.UUID | None:
    from app.platform.refresh.service import (
        cancel_active_run_for_job,
        record_refresh_failure,
    )

    if end.transition == "settle_stale":
        # A stale job's run keeps its own proof: its stale pass cancels it
        # only when no task can still finish it.
        return None
    if end.transition == "cancel":
        return await cancel_active_run_for_job(
            session, end.job_id, cancelled_by=end.actor
        )
    return await record_refresh_failure(
        session,
        ingest_job_id=end.job_id,
        error_code=end.code,
        error_message=end.reason,
        contacted_origin=False,
    )


async def _close_backfill_trail(session: AsyncSession, end: JobEnd) -> None:
    from app.platform.jobs.sweep import audit_settled_embedding_backfill

    await audit_settled_embedding_backfill(
        session,
        job_id=end.job_id,
        user_metadata=end.user_metadata,
        created_by=end.created_by,
        error_code=end.code,
        settled_by=end.actor,
        ip_address=end.ip_address,
    )


async def _release_vrt_generation(
    session: AsyncSession, end: JobEnd
) -> uuid.UUID | None:
    if (
        end.transition == "settle_stale"
        or end.source_filename != VRT_REGENERATE_JOB_FILENAME
        or end.dataset_id is None
    ):
        # A stale regeneration is failed by its own heartbeat, in the VRT
        # stale pass.
        return None
    return await release_vrt_regeneration(
        session, end.dataset_id, end.at, message=end.reason
    )


async def _cancel_abandoned_runs(
    session: AsyncSession, now: datetime, job_ids: Sequence[uuid.UUID] | None
) -> StalePassResult:
    from app.platform.refresh.service import sweep_abandoned_refresh_runs

    cancelled = await sweep_abandoned_refresh_runs(session, now, job_ids=job_ids)
    return StalePassResult(refresh_runs_cancelled=cancelled)


async def _reconcile_stale_regenerations(
    session: AsyncSession, now: datetime, job_ids: Sequence[uuid.UUID] | None
) -> StalePassResult:
    from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS, sweep_stale_vrt_assets

    recovered, failed, storage_keys = await sweep_stale_vrt_assets(
        session,
        now - timedelta(seconds=JOB_TIMEOUT_SECONDS),
        dataset_ids=None
        if job_ids is None
        else select(IngestJob.dataset_id).where(IngestJob.id.in_(job_ids)),
    )
    return StalePassResult(
        vrt_assets_recovered=recovered,
        vrt_generations_failed=failed,
        storage_keys=storage_keys,
    )


# One entry per owner of rows an ended job would strand. Each hook is a no-op
# for a job its owner has no rows for.
_OWNERS: dict[str, LinkedOwner] = {
    "run": LinkedOwner(_end_refresh_run, _cancel_abandoned_runs),
    "backfill_trail": LinkedOwner(_close_backfill_trail),
    "vrt": LinkedOwner(_release_vrt_generation, _reconcile_stale_regenerations),
}
