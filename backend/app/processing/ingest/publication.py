"""The settlement seam: one order for every replacement of a dataset's data.

``settle_replacement`` claims the job, has the strategy fetch and stage the
candidate, publishes it in one transaction and ends the job. A strategy
supplies only its own steps.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.orm import joinedload

from app.core.failure_reason import redact_failure_reason
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.catalog_locks import (
    CatalogLockConflict,
    bump_tile_cache_version_on,
    lock_catalog_rows,
    lock_conflict_report,
    worker_lock_budget,
)
from app.platform.jobs import heartbeat
from app.platform.jobs.heartbeat import (
    StaleIngestAttempt,
    arm_job_error_write_budget,
    attempt_scoped_staging_table,
    claim_job_attempt_and_start_heartbeat,
    log_job_error_write_failure,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
)
from app.platform.jobs.ledger import hold
from app.platform.jobs.models import IngestJob
from app.platform.refresh.service import (
    claim_run_for_job,
    record_refresh_failure,
    record_refresh_success,
)
from app.processing.ingest.tasks_common import (
    _current_tenant_schema,
    cleanup_step,
    invalidate_tile_cache_for_table,
)
from app.processing.ingest.tasks_raster_common import (
    PublishObservation,
    absorb_cancellation,
    observe_publish_commit,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# What settles the rows linked to a job when its end lands.
Linked = Callable[["AsyncSession"], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Verdict:
    """What staging decided about the candidate.

    A verdict that holds the candidate back ends the job ``failed`` with
    ``reason``. Its ``settle``, which it must have, writes what the hold-back
    records, under the catalog rows and only when the job's end lands, and
    ``notify`` sends ``ingest_failed``.
    """

    publish: bool = True
    reason: str = ""
    settle: Linked | None = None
    notify: bool = False

    def __post_init__(self) -> None:
        if not self.publish and self.settle is None:
            raise ValueError("A held-back verdict needs a settle step for its run")


PUBLISH = Verdict()


@dataclass(frozen=True, slots=True)
class Published:
    """What a strategy's catalog writes produced, for the run it completes."""

    dataset_version_id: uuid.UUID | None
    feature_count: int | None
    schema_diff: dict[str, Any] | None
    contacted_origin: bool
    verification: dict[str, Any] | None = None
    # Its cached tiles are purged after the commit.
    live_table: str | None = None
    # Whether the write changed tile content, which bumps the tile version.
    tiles_changed: bool = True
    # Whether it changed what the dataset's search embedding is built from.
    reembed: bool = True


@dataclass(frozen=True, slots=True)
class Failure:
    """How a failed attempt is recorded on its run."""

    error_code: str
    feature_count_after: int | None = None
    schema_diff: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    # The origin binding the attempt contacted, when it reached the origin.
    contacted: tuple[str | None, dict[str, Any] | None, str | None] | None = None
    # What the contact established about the origin: (health, detail).
    health: tuple[str, str | None] | None = None
    # A refused input is recorded like any failure, but the task returns.
    refused: bool = False


class ReplacementStrategy(Protocol):
    """One kind of replacement's own steps; the seam decides their order."""

    task: str
    # Stages into this attempt's own copy of the dataset's table.
    staging: bool
    # The catalog rows include the dataset's raster row.
    raster_row: bool
    # The prefix of the catalog wait's log events.
    catalog_event: str

    def prepare(self, job: IngestJob, dataset: Any, staging_table: str) -> None:
        """Read what the attempt needs from its job and dataset; writes nothing."""

    async def fetch(self) -> None:
        """Bring the candidate in, holding no session."""

    async def stage(
        self, session: AsyncSession, job: IngestJob, dataset: Any
    ) -> Verdict:
        """Prepare and measure the candidate, and decide whether it publishes."""

    async def install(self, session: AsyncSession, dataset: Any) -> None:
        """Put the candidate in place, before the catalog rows are taken."""

    async def write(self, session: AsyncSession, dataset: Any) -> Published:
        """Write the catalog rows the seam holds, starting with any fence."""

    def classify(self, exc: BaseException) -> Failure:
        """How ``exc`` is recorded; may scrub it first."""

    async def release(
        self, *, publication: PublicationCommit | None, failed: bool
    ) -> None:
        """Keep or remove the files the strategy owns; must not raise."""


class PublicationCommit(StrEnum):
    """How a publishing commit is known to have landed."""

    ACKNOWLEDGED = "acknowledged"
    # The acknowledgement was lost; a probe read this attempt's job complete.
    OBSERVED = "observed"
    # The acknowledgement was lost and the probe failed: the old data may
    # still be the live data.
    INDETERMINATE = "indeterminate"

    @property
    def confirmed(self) -> bool:
        """The commit certainly landed, so what it superseded is unreferenced."""
        return self is not PublicationCommit.INDETERMINATE


async def commit_publication(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    task: str,
    ended: str = "complete",
) -> PublicationCommit:
    """Commit the transaction that ends this attempt's job ``ended``.

    When the acknowledgement is lost, a probe of the job row decides: a commit
    it reads as landed, or cannot read at all, is returned rather than raised,
    and a cancellation that lost the acknowledgement is absorbed so the caller
    goes on to its post-commit steps. Re-raises when the probe reads that the
    commit did not land. Every replacement path ends its job in that
    transaction, which is what the probe reads. Callers delete superseded data
    only when the result is ``confirmed``.
    """
    try:
        await session.commit()
    except (
        Exception,
        asyncio.CancelledError,
    ) as exc:  # broad: a lost acknowledgement can surface as any error
        observation = await observe_publish_commit(
            job_id, attempt_id, job_id=str(job_id), task=task, ended=ended
        )
        if observation is PublishObservation.NOT_LANDED:
            raise
        absorb_cancellation(exc)
        if observation is PublishObservation.LANDED:
            return PublicationCommit.OBSERVED
        return PublicationCommit.INDETERMINATE
    return PublicationCommit.ACKNOWLEDGED


async def hold_publishing_job(
    session: AsyncSession, job_id: uuid.UUID, attempt_id: uuid.UUID
) -> IngestJob:
    """Lock this attempt's running job row, the first row a publication takes.

    Waits at most ``WORKER_LOCK_TIMEOUT``, and raises ``CatalogLockConflict``
    after a rollback when the wait fails. Raises ``StaleIngestAttempt``,
    having written nothing, when the attempt no longer owns a running job.
    """
    async with worker_lock_budget(session):
        job = await hold(session, job_id, expect="running", attempt_id=attempt_id)
    if job is None:
        raise StaleIngestAttempt(
            f"Ingest attempt {attempt_id} no longer owns job {job_id}"
        )
    return job


async def _complete(
    session: AsyncSession, job_id: uuid.UUID, attempt_id: uuid.UUID, *, linked: Linked
) -> None:
    """Move this attempt's job from running to complete, then settle ``linked``.

    A miss raises ``StaleIngestAttempt`` and writes nothing. Does not commit.
    """
    await require_ingest_job_update(
        session,
        job_id,
        attempt_id,
        values={"status": "complete", "completed_at": datetime.now(timezone.utc)},
    )
    await linked(session)


async def _fail(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    reason: str | BaseException,
    linked: Linked,
) -> bool:
    """Move this attempt's job from pending or running to failed, then settle ``linked``.

    ``reason`` is stored redacted. Returns whether the write landed; a miss
    writes nothing. Does not commit.
    """
    ended = await session.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job_id,
            IngestJob.attempt_id == attempt_id,
            IngestJob.status.in_(("pending", "running")),
        )
        .values(
            status="failed",
            error_message=redact_failure_reason(reason),
            completed_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    if not ended.rowcount:
        return False
    await linked(session)
    return True


@dataclass
class _Attempt:
    """One attempt's ids, and what the seam cleans up after it."""

    job_id: uuid.UUID
    attempt_id: uuid.UUID
    dataset_id: uuid.UUID
    heartbeat: asyncio.Task[None] | None = None
    staging_table: str = ""
    # Set as the publishing commit returns, before anything else can raise or
    # be cancelled, so cleanup never reaps what the commit published.
    publication: PublicationCommit | None = None
    reembed: bool = True


async def settle_replacement(
    strategy: ReplacementStrategy,
    *,
    job_id: str,
    dataset_id: str,
    attempt_id: str | None,
) -> None:
    """Run one replacement attempt through claim, fetch, publication and cleanup.

    The job row is held from after staging to the commit, and the catalog rows
    are taken after ``install``, job row first, then the raster row, datasets
    and records, under ``WORKER_LOCK_TIMEOUT``. Nothing is fetched or staged
    after that. The job and its run end in the catalog writes' transaction. A
    failure before the commit leaves live data as it was and is recorded once;
    a step after the commit only logs its failure.
    """
    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label=strategy.task
    )
    if resolved is None:
        return
    attempt = _Attempt(*resolved, dataset_id=uuid.UUID(dataset_id))
    failed = False
    try:
        if not await _claim(strategy, attempt):
            return
        await strategy.fetch()
        failed = await _publish(strategy, attempt)
    except Exception as exc:  # broad: every failure before the commit is recorded once
        failed = True
        failure = strategy.classify(exc)
        logger.exception("Ingest task failed", job_id=job_id, task=strategy.task)
        await _record_failure(strategy, attempt, exc, failure)
        if failure.refused:
            return
        raise
    finally:
        async with cleanup_step(f"{strategy.task} heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(attempt.heartbeat)
        async with cleanup_step(f"{strategy.task} staging table", job_id=job_id):
            await _drop_staging_table(attempt.staging_table)
        await strategy.release(publication=attempt.publication, failed=failed)

    if attempt.publication is not None and attempt.reembed:
        async with cleanup_step(f"{strategy.task} embedding", job_id=job_id):
            await _defer_embedding(attempt.dataset_id)


async def _claim(strategy: ReplacementStrategy, attempt: _Attempt) -> bool:
    """Claim the job and its run and commit, before anything is fetched.

    False when the job, the dataset or the claim is gone.
    """
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port

    Dataset = get_processing_port().get_dataset_orm_class()
    async with async_session() as session:
        job = await session.scalar(
            select(IngestJob).where(
                IngestJob.id == attempt.job_id,
                IngestJob.attempt_id == attempt.attempt_id,
            )
        )
        if job is None:
            logger.warning("Ingest job not found, skipping", job_id=str(attempt.job_id))
            return False
        dataset = await session.scalar(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == attempt.dataset_id)
        )
        if dataset is None:
            logger.warning(
                "Dataset not found, skipping", dataset_id=str(attempt.dataset_id)
            )
            return False
        # Named before the claim: a redelivery that loses it still drops the
        # table its dead worker left, and nothing else reaps attempt tables.
        attempt.staging_table = (
            attempt_scoped_staging_table(dataset.table_name, attempt.attempt_id)
            if strategy.staging
            else ""
        )
        strategy.prepare(job, dataset, attempt.staging_table)
        attempt.heartbeat = await claim_job_attempt_and_start_heartbeat(
            session, attempt.job_id, attempt.attempt_id
        )
        if attempt.heartbeat is None:
            return False
        # The run row stays locked until this commit, and a cancel transitions
        # it under a 2 s lock_timeout, so it commits before the fetch.
        await claim_run_for_job(session, attempt.job_id)
        await session.commit()
        if attempt.staging_table:
            # A redelivery of this attempt may have left its table behind.
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS {_qualified(attempt.staging_table)} CASCADE"
                )
            )
            await session.commit()
    return True


async def _publish(strategy: ReplacementStrategy, attempt: _Attempt) -> bool:
    """Stage and verify the candidate, then publish it or hold it back.

    Records a publication's commit on ``attempt``. Returns whether a verdict
    held the candidate back.
    """
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port

    Dataset = get_processing_port().get_dataset_orm_class()
    job_id, attempt_id = attempt.job_id, attempt.attempt_id
    async with async_session() as session:
        job = (
            await session.execute(
                select(IngestJob).where(
                    IngestJob.id == job_id, IngestJob.attempt_id == attempt_id
                )
            )
        ).scalar_one()
        dataset = (
            await session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == attempt.dataset_id)
            )
        ).scalar_one()
        verdict = await strategy.stage(session, job, dataset)
        await hold_publishing_job(session, job_id, attempt_id)

        if not verdict.publish:
            await _take_catalog_rows(session, strategy, dataset)
            landed = await _fail(
                session,
                job_id,
                attempt_id,
                reason=verdict.reason,
                linked=verdict.settle,
            )
            ended = await commit_publication(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                task=strategy.task,
                ended="failed",
            )
            async with cleanup_step(
                f"{strategy.task} catalog cache", job_id=str(job_id)
            ):
                await invalidate_catalog_cache()
            if landed and ended.confirmed and verdict.notify:
                await _notify_failed(job_id, task=strategy.task, reason=verdict.reason)
            return True

        await strategy.install(session, dataset)
        await _take_catalog_rows(session, strategy, dataset)
        published = await strategy.write(session, dataset)
        attempt.reembed = published.reembed
        if published.tiles_changed:
            await bump_tile_cache_version_on(session, dataset)
        await _complete(
            session,
            job_id,
            attempt_id,
            linked=partial(
                record_refresh_success,
                ingest_job_id=job_id,
                dataset=dataset,
                dataset_version_id=published.dataset_version_id,
                feature_count_after=published.feature_count,
                schema_diff=published.schema_diff,
                verification=published.verification,
                contacted_origin=published.contacted_origin,
            ),
        )
        attempt.publication = await commit_publication(
            session, job_id=job_id, attempt_id=attempt_id, task=strategy.task
        )

        # Published, so each step below logs its own failure instead of
        # failing the replacement.
        async with cleanup_step(f"{strategy.task} catalog cache", job_id=str(job_id)):
            await invalidate_catalog_cache()
        if published.live_table is not None:
            async with cleanup_step(f"{strategy.task} tile cache", job_id=str(job_id)):
                await invalidate_tile_cache_for_table(published.live_table)
    return False


async def _take_catalog_rows(
    session: AsyncSession, strategy: ReplacementStrategy, dataset: Any
) -> None:
    """Lock the raster row when the strategy has one, then datasets and records."""
    from app.platform.catalog_locks import WORKER_LOCK_TIMEOUT
    from app.platform.extensions import get_processing_port

    raster_asset_cls = None
    if strategy.raster_row:
        from app.processing.raster.models import RasterAsset as raster_asset_cls

    port = get_processing_port()
    # Read before the wait: a failed acquisition rolls back and expires the row.
    dataset_id, table_name = str(dataset.id), dataset.table_name
    started = time.perf_counter()
    try:
        async with worker_lock_budget(session):
            await lock_catalog_rows(
                session,
                dataset_cls=port.get_dataset_orm_class(),
                record_cls=port.get_record_orm_class(),
                dataset_id=dataset.id,
                record_id=dataset.record_id,
                lock_timeout=None,
                raster_asset_cls=raster_asset_cls,
            )
    except CatalogLockConflict as conflict:
        event, hint, code = lock_conflict_report(
            conflict, event_prefix=strategy.catalog_event
        )
        logger.warning(
            event,
            dataset_id=dataset_id,
            table_name=table_name,
            waited_ms=round((time.perf_counter() - started) * 1000),
            budget=WORKER_LOCK_TIMEOUT,
            sqlstate=code,
            hint=hint,
        )
        raise
    logger.info(
        f"{strategy.catalog_event}_lock_acquired",
        dataset_id=dataset_id,
        table_name=table_name,
        waited_ms=round((time.perf_counter() - started) * 1000),
        budget=WORKER_LOCK_TIMEOUT,
    )


async def _record_failure(
    strategy: ReplacementStrategy,
    attempt: _Attempt,
    exc: BaseException,
    failure: Failure,
) -> None:
    """End the attempt's job and run as failed in one bounded transaction.

    Never raises: the task's own failure is what the caller re-raises. Sends
    ``ingest_failed`` when the job's end landed.
    """
    from app.core.db import async_session

    stamped = False

    async def _settle(session: AsyncSession) -> None:
        nonlocal stamped
        await record_refresh_failure(
            session,
            ingest_job_id=attempt.job_id,
            error_code=failure.error_code,
            error_message=exc,
            feature_count_after=failure.feature_count_after,
            schema_diff=failure.schema_diff,
            verification=failure.verification,
        )
        if failure.contacted is not None:
            stamped = await _stamp_contact(
                session, attempt.dataset_id, failure.contacted, failure.health
            )

    try:
        async with async_session() as session:
            # The pool checkout first, on its own deadline: `SET LOCAL` cannot
            # bound a wait for a connection.
            await asyncio.wait_for(
                session.connection(),
                timeout=heartbeat.JOB_ERROR_WRITE_TIMEOUT_MS / 1000,
            )
            await arm_job_error_write_budget(session)
            landed = await _fail(
                session,
                attempt.job_id,
                attempt.attempt_id,
                reason=exc,
                linked=_settle,
            )
            await session.commit()
    except Exception as write_failure:  # broad: must not replace the task's failure
        log_job_error_write_failure(
            write_failure, job_id=str(attempt.job_id), task=strategy.task
        )
        return
    if stamped:
        async with cleanup_step(
            f"{strategy.task} catalog cache", job_id=str(attempt.job_id)
        ):
            await invalidate_catalog_cache()
    if landed:
        await _notify_failed(attempt.job_id, task=strategy.task, reason=exc)


async def _stamp_contact(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    binding: tuple[str | None, dict[str, Any] | None, str | None],
    health: tuple[str, str | None] | None = None,
) -> bool:
    """Date a failed attempt's origin contact, only while the dataset is still bound as it read.

    ``health`` is written with it when the contact established one. A rebind
    that finished first stamped what is true now, so losing the race writes
    nothing. A row another transaction holds is skipped the same way: the
    failure is often the wait on that row, and its write must not wait again.
    """
    from app.platform.extensions import get_processing_port

    Dataset = get_processing_port().get_dataset_orm_class()
    origin_uri, origin_ref, source_format = binding
    free = (
        select(Dataset.id)
        .where(Dataset.id == dataset_id)
        .with_for_update(key_share=True, skip_locked=True)
    )
    stamped = await session.execute(
        update(Dataset)
        .where(
            Dataset.id == dataset_id,
            Dataset.id.in_(free),
            Dataset.origin_uri.is_not_distinct_from(origin_uri),
            Dataset.origin_ref.is_not_distinct_from(origin_ref),
            Dataset.source_format.is_not_distinct_from(source_format),
        )
        .values(
            last_checked_at=datetime.now(timezone.utc),
            **(
                {"source_health": health[0], "source_health_detail": health[1]}
                if health is not None
                else {}
            ),
        )
        .execution_options(synchronize_session=False)
    )
    return bool(stamped.rowcount)


async def _notify_failed(
    job_id: uuid.UUID, *, task: str, reason: str | BaseException
) -> None:
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    message = redact_failure_reason(reason)
    await emit_event_safe(
        event_key="ingest_failed",
        build=lambda: build_event_notification(
            "ingest_failed",
            subject=f"Ingest failed: {task}",
            body=f"Ingest job (task={task}) failed.",
            reason=message,
            extra={"job_id": str(job_id), "task": task},
        ),
    )


def _qualified(staging_table: str) -> str:
    from app.processing.ingest.metadata import _qtable

    return _qtable(staging_table, schema=_current_tenant_schema())


async def _drop_staging_table(staging_table: str) -> None:
    """Drop this attempt's staging table; a failure is only logged."""
    if not staging_table:
        return
    from app.core.db import async_session

    try:
        async with async_session() as session:
            await session.execute(
                text(f"DROP TABLE IF EXISTS {_qualified(staging_table)} CASCADE")
            )
            await session.commit()
    except Exception:  # broad: cleanup must not mask the ingest result
        logger.warning(
            "attempt_staging_cleanup_failed", staging_table=staging_table, exc_info=True
        )


async def _defer_embedding(dataset_id: uuid.UUID) -> None:
    """Queue the published dataset's embedding, built from what it now holds."""
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.processing.embeddings.helpers import defer_embedding

    Dataset = get_processing_port().get_dataset_orm_class()
    async with async_session() as session:
        dataset = await session.scalar(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
        if dataset is not None:
            await defer_embedding(dataset)
