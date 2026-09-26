"""The job ledger: every write of ``ingest_jobs.status``.

``create`` adds a job. The job's owner moves it with ``claim``, ``stage``,
``fan_out``, ``restore``, ``complete`` and ``fail``. ``hold`` locks a job in
the state its caller expects. ``abort`` fails a job no worker holds, ``cancel``
ends a pending or running job at a user's request, ``end_stale`` ends a job the
stale pass found, and ``retry`` returns a failed job to pending under a new
attempt. Each fences on the attempt its caller read and writes nothing on a
miss.

Rows linked to a job stay with their owners. When an abort, cancel or stale
end lands, each owner's ``job_ended`` hook settles its rows in the same
transaction, after the job row is locked, and a hook that raises takes the job
write back with it. Once per stale pass, each owner's ``stale_pass`` settles
the rows it proves stale itself. A job's owner ending its own job passes its
linked write as ``linked`` instead.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import String, func, inspect as sa_inspect, literal, or_, select, text
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.failure_reason import FixedReason, failure_code, redact_failure_reason
from app.platform.jobs.models import (
    ACTIVE_STATUSES,
    FAN_OUT_INTERRUPTED_METADATA_KEY,
    IngestJob,
)

# The three VRT regeneration doors create their job under this filename, and
# nothing else does.
VRT_REGENERATE_JOB_FILENAME = "vrt_regenerate"

# What a user's cancel stores on the job, and on a VRT generation it releases.
_CANCEL_REASON = FixedReason("Cancelled by user", code="user_cancelled")

# The job's columns an owner's hook reads when an end lands.
_END_COLUMNS = ("dataset_id", "source_filename", "user_metadata", "created_by")

# The columns a transition writes itself or fences on. Neither a transition's
# ``values`` nor heartbeat's fenced update may name them.
OWNED_COLUMNS = frozenset(
    {"status", "error_message", "error_code", "completed_at", "attempt_id", "id"}
)


class Outcome(enum.Enum):
    """What a ledger write did. Every value except ``LANDED`` wrote nothing."""

    LANDED = "landed"
    MISSING = "missing"
    MOVED = "moved"
    SUPERSEDED = "superseded"


class StaleIngestAttempt(RuntimeError):
    """Raised when a worker no longer owns the job attempt it received."""


Linked = Callable[[AsyncSession], Awaitable[None]]
"""An owner's write to its job's linked rows, run when the owner's end lands."""


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


def _extra(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """A transition's further columns, refused if they name one it writes itself."""
    extra = dict(values or {})
    if owned := OWNED_COLUMNS & extra.keys():
        raise ValueError(f"the ledger writes {sorted(owned)} itself")
    return extra


async def _move(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID | None,
    *,
    expect: tuple[str, ...],
    written: Mapping[str, Any],
    require: Sequence[Any] = (),
    linked: Linked | None = None,
    mirror: IngestJob | None = None,
) -> bool:
    """Write one fenced transition, run ``linked`` when it lands, and mirror it.

    ``linked`` shares a SAVEPOINT with the write, so when it raises, the write
    rolls back with it. What landed is mirrored onto ``mirror``, or else onto
    the session's own instance of the row. Does not commit.
    """
    statement = (
        update(IngestJob)
        .where(
            IngestJob.id == job_id,
            IngestJob.status.in_(expect),
            _attempt_is(attempt_id),
            *require,
        )
        .values(**written)
        .returning(*(getattr(IngestJob, column) for column in written))
        .execution_options(synchronize_session=False)
    )
    if linked is None:
        landed = (await session.execute(statement)).one_or_none()
    else:
        async with session.begin_nested():
            landed = (await session.execute(statement)).one_or_none()
            if landed is not None:
                await linked(session)
    if landed is None:
        return False
    if mirror is None:
        mirror = session.identity_map.get(session.identity_key(IngestJob, job_id))
    if mirror is not None:
        _mirror(mirror, landed._mapping)
    return True


def create(
    session: AsyncSession,
    *,
    created_by: uuid.UUID | None,
    status: str = "pending",
    dataset_id: uuid.UUID | None = None,
    source_filename: str | None = None,
    file_path: str | None = None,
    source_url: str | None = None,
    source_layer: str | None = None,
    user_metadata: dict[str, Any] | None = None,
    current_step: str | None = None,
    progress: float | None = None,
) -> IngestJob:
    """Add a job, pending or running, to the session. Does not flush or commit.

    A job created ``running`` starts now: the URL import and the manifest
    reservation begin their work in the request that creates them.
    """
    if status not in ACTIVE_STATUSES:
        raise ValueError(f"a job cannot be created {status!r}")
    job = IngestJob(
        status=status,
        created_by=created_by,
        dataset_id=dataset_id,
        source_filename=source_filename,
        file_path=file_path,
        source_url=source_url,
        source_layer=source_layer,
        user_metadata=user_metadata,
        current_step=current_step,
        progress=progress,
        started_at=datetime.now(timezone.utc) if status == "running" else None,
    )
    session.add(job)
    return job


async def claim(
    session: AsyncSession, job_id: uuid.UUID, attempt_id: uuid.UUID
) -> bool:
    """Move this attempt's pending job to running and start its lease.

    Returns whether it landed. Does not commit.
    """
    now = datetime.now(timezone.utc)
    return await _move(
        session,
        job_id,
        attempt_id,
        expect=("pending",),
        written={"status": "running", "started_at": now, "heartbeat_at": now},
    )


async def stage(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID | None,
    *,
    values: Mapping[str, Any],
    require: Sequence[Any] = (),
    mirror: IngestJob | None = None,
) -> bool:
    """Return this attempt's running job to pending, writing ``values`` with it.

    ``require`` adds predicates the row must still meet. Returns whether it
    landed. Does not commit.
    """
    return await _move(
        session,
        job_id,
        attempt_id,
        expect=("running",),
        written={"status": "pending", **_extra(values)},
        require=require,
        mirror=mirror,
    )


async def fan_out(
    session: AsyncSession, job_id: uuid.UUID, attempt_id: uuid.UUID | None
) -> bool:
    """Move this attempt's pending parent to ``fanned_out``, before any child exists.

    Returns whether it landed. Does not commit.
    """
    return await _move(
        session,
        job_id,
        attempt_id,
        expect=("pending",),
        written={"status": "fanned_out", "completed_at": datetime.now(timezone.utc)},
    )


async def restore(
    session: AsyncSession, job_id: uuid.UUID, attempt_id: uuid.UUID | None
) -> bool:
    """Return this attempt's parent to pending when none of its children queued.

    Takes the parent from ``fanned_out``, or from ``failed`` with the
    interrupted marker the childless fan-out sweep stamps, and drops that
    marker. Returns whether it landed. Does not commit.
    """
    return await _move(
        session,
        job_id,
        attempt_id,
        expect=("fanned_out", "failed"),
        require=(
            or_(
                IngestJob.status == "fanned_out",
                IngestJob.user_metadata[FAN_OUT_INTERRUPTED_METADATA_KEY].astext
                == "true",
            ),
        ),
        written={
            "status": "pending",
            "completed_at": None,
            "error_message": None,
            "error_code": None,
            "user_metadata": IngestJob.user_metadata.op("-")(
                literal(FAN_OUT_INTERRUPTED_METADATA_KEY, String)
            ),
        },
    )


async def complete(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    values: Mapping[str, Any] | None = None,
    linked: Linked | None = None,
    expect: str = "running",
    mirror: IngestJob | None = None,
) -> None:
    """Move this attempt's job to ``complete``, then run ``linked``.

    ``values`` are further columns the end writes. A miss raises
    ``StaleIngestAttempt`` and writes nothing. Does not commit.
    """
    written = {
        "status": "complete",
        "completed_at": datetime.now(timezone.utc),
        **_extra(values),
    }
    if not await _move(
        session,
        job_id,
        attempt_id,
        expect=(expect,),
        written=written,
        linked=linked,
        mirror=mirror,
    ):
        raise StaleIngestAttempt(
            f"Ingest attempt {attempt_id} no longer owns job {job_id}"
        )


async def fail(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID | None,
    *,
    reason: str | BaseException | None,
    values: Mapping[str, Any] | None = None,
    linked: Linked | None = None,
    expect: str | tuple[str, ...] = "running",
    require: Sequence[Any] = (),
    mirror: IngestJob | None = None,
) -> bool:
    """Move this attempt's job to ``failed``, then run ``linked``.

    ``reason`` is stored redacted, and None stores none. A ``FixedReason``
    also stores its code in ``error_code``. ``values`` are further
    columns the end writes, and ``require`` further predicates the row must
    still meet. A miss returns False and writes nothing. Does not commit.
    """
    stored = None if reason is None else redact_failure_reason(reason)
    written = {
        "status": "failed",
        "error_message": stored,
        "error_code": failure_code(stored),
        "completed_at": datetime.now(timezone.utc),
        **_extra(values),
    }
    return await _move(
        session,
        job_id,
        attempt_id,
        expect=(expect,) if isinstance(expect, str) else expect,
        written=written,
        require=require,
        linked=linked,
        mirror=mirror,
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
    # A URL import commits its row running before it dispatches.
    if expect not in ACTIVE_STATUSES:
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
        expect=ACTIVE_STATUSES,
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
    written = {
        "status": status,
        "error_message": reason,
        "error_code": failure_code(reason),
        "completed_at": now,
        **_extra(values),
    }
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
                error_code=None,
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
                IngestJob.error_code,
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
