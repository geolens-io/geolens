"""The job ledger: the dispatch-side ends of an ``ingest_jobs`` row.

``hold`` locks a job in the state its caller expects, and ``abort`` fails a job
no worker holds. Both fence on the attempt the caller read and write nothing
on a miss.

Rows linked to a job stay with their owners. When an abort lands, each
``JobEndHook`` settles its owner's rows in the same transaction, after the job
row is locked, and a hook that raises takes the job write back with it.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect as sa_inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.failure_reason import redact_failure_reason
from app.platform.jobs.models import IngestJob

# The three VRT regeneration doors create their job under this filename, and
# nothing else does.
VRT_REGENERATE_JOB_FILENAME = "vrt_regenerate"

# The URL import commits its row ``running`` before it dispatches.
_ABORTABLE_STATUSES = ("pending", "running")


class Outcome(enum.Enum):
    """What a ledger write did. Every value except ``ENDED`` wrote nothing."""

    ENDED = "ended"
    MISSING = "missing"
    MOVED = "moved"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class JobEnd:
    """A job end that landed, as the rows linked to the job see it."""

    job_id: uuid.UUID
    dataset_id: uuid.UUID | None
    source_filename: str | None
    user_metadata: dict[str, Any] | None
    created_by: uuid.UUID | None
    code: str
    reason: str
    at: datetime
    ip_address: str | None


JobEndHook = Callable[[AsyncSession, JobEnd], Awaitable[None]]


def _attempt_is(attempt_id: uuid.UUID | None):
    return (
        IngestJob.attempt_id == attempt_id
        if attempt_id is not None
        else IngestJob.attempt_id.is_(None)
    )


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
    reason = redact_failure_reason(reason)
    job_id, attempt_id = job.id, job.attempt_id
    now = datetime.now(timezone.utc)
    async with session.begin_nested():
        ended = (
            await session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job_id,
                    IngestJob.status == expect,
                    _attempt_is(attempt_id),
                )
                .values(status="failed", error_message=reason, completed_at=now)
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
                code=code,
                reason=reason,
                at=now,
                ip_address=ip_address,
            )
            for hook in _END_HOOKS:
                await hook(session, end)
    if ended is None:
        return await _missed(session, job_id, attempt_id)
    if sa_inspect(job, raiseerr=False) is not None:
        set_committed_value(job, "status", "failed")
        set_committed_value(job, "error_message", reason)
        set_committed_value(job, "completed_at", now)
    return Outcome.ENDED


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
) -> None:
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
        return
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
        return
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


# Each hook imports its owner at call time: the run module imports this one.
async def _fail_refresh_run(session: AsyncSession, end: JobEnd) -> None:
    from app.platform.refresh.service import record_refresh_failure

    await record_refresh_failure(
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
        ip_address=end.ip_address,
    )


async def _release_vrt_generation(session: AsyncSession, end: JobEnd) -> None:
    if (
        end.source_filename == VRT_REGENERATE_JOB_FILENAME
        and end.dataset_id is not None
    ):
        await release_vrt_regeneration(
            session, end.dataset_id, end.at, message=end.reason
        )


# One hook per owner of rows an ended job would strand. Each is a no-op for a
# job its owner has no rows for.
_END_HOOKS: tuple[JobEndHook, ...] = (
    _fail_refresh_run,
    _close_backfill_trail,
    _release_vrt_generation,
)
