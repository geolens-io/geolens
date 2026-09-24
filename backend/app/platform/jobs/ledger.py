"""The job ledger: the ``ingest_jobs`` transitions no worker makes.

``hold`` locks a job in the state its caller expects. ``abort`` fails a job no
worker holds, ``cancel`` ends a pending or running job at a user's request,
and ``retry`` returns a failed job to pending under a new attempt. Each fences
on the attempt its caller read and writes nothing on a miss.

Rows linked to a job stay with their owners. When an abort or a cancel lands,
each ``JobEndHook`` settles its owner's rows in the same transaction, after the
job row is locked, and a hook that raises takes the job write back with it.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


class Outcome(enum.Enum):
    """What a ledger write did. Every value except ``LANDED`` wrote nothing."""

    LANDED = "landed"
    MISSING = "missing"
    MOVED = "moved"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class JobEnd:
    """A job end that landed, as the rows linked to the job see it.

    ``actor`` is whoever ended the job, or None for its creator.
    """

    job_id: uuid.UUID
    dataset_id: uuid.UUID | None
    source_filename: str | None
    user_metadata: dict[str, Any] | None
    created_by: uuid.UUID | None
    status: str
    code: str
    reason: str
    at: datetime
    actor: uuid.UUID | None
    ip_address: str | None


JobEndHook = Callable[[AsyncSession, JobEnd], Awaitable[uuid.UUID | None]]
"""Settles one owner's rows for a landed end; returns the row it ended, if any."""


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
        job,
        expect=(expect,),
        status="failed",
        code=code,
        reason=reason,
        actor=None,
        ip_address=ip_address,
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
        job,
        expect=("pending", "running"),
        status="cancelled",
        code=USER_CANCELLED_ERROR_CODE,
        reason=_CANCEL_REASON,
        actor=actor,
        ip_address=None,
    )


async def _end(
    session: AsyncSession,
    job: IngestJob,
    *,
    expect: tuple[str, ...],
    status: str,
    code: str,
    reason: str | BaseException,
    actor: uuid.UUID | None,
    ip_address: str | None,
) -> Ended:
    """Write one fenced end and, when it lands, run every hook on it."""
    reason = redact_failure_reason(reason)
    job_id, attempt_id = job.id, job.attempt_id
    now = datetime.now(timezone.utc)
    linked: dict[str, uuid.UUID] = {}
    async with session.begin_nested():
        ended = (
            await session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job_id,
                    IngestJob.status.in_(expect),
                    _attempt_is(attempt_id),
                )
                .values(status=status, error_message=reason, completed_at=now)
                .returning(
                    IngestJob.dataset_id,
                    IngestJob.source_filename,
                    IngestJob.user_metadata,
                    IngestJob.created_by,
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
                status=status,
                code=code,
                reason=reason,
                at=now,
                actor=actor,
                ip_address=ip_address,
            )
            for owner, hook in _END_HOOKS.items():
                row_id = await hook(session, end)
                if row_id is not None:
                    linked[owner] = row_id
    if ended is None:
        return Ended(await _missed(session, job_id, attempt_id))
    _mirror(job, {"status": status, "error_message": reason, "completed_at": now})
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

    if end.status == "cancelled":
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
    if end.source_filename != VRT_REGENERATE_JOB_FILENAME or end.dataset_id is None:
        return None
    return await release_vrt_regeneration(
        session, end.dataset_id, end.at, message=end.reason
    )


# One hook per owner of rows an ended job would strand, keyed by owner. Each is
# a no-op for a job its owner has no rows for.
_END_HOOKS: dict[str, JobEndHook] = {
    "run": _end_refresh_run,
    "backfill_trail": _close_backfill_trail,
    "vrt": _release_vrt_generation,
}
