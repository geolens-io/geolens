"""Settle a prepared service publication, and commit any replacement's publication."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from app.core.failure_reason import redact_failure_reason
from app.core.url_redaction import scrub_secret_from_exception
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.catalog_locks import (
    CATALOG_LOCK_CONFLICT_CODE,
    WORKER_LOCK_TIMEOUT,
    CatalogLockConflict,
    lock_catalog_rows,
)
from app.platform.refresh import verification as refresh_policy
from app.platform.refresh.service import (
    drift_status_from_diff,
    record_refresh_blocked,
    record_refresh_failure,
    record_refresh_success,
)
from app.processing.ingest.tasks_common import (
    _apply_reupload_swap,
    cleanup_step,
    invalidate_tile_cache_for_table,
    load_job_for_error_write,
)
from app.processing.ingest.tasks_raster_common import (
    absorb_cancellation,
    publish_commit_landed,
)
from app.processing.ingest.tasks_staging import _cleanup_staging_on_failure

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PublicationOutcome(StrEnum):
    """The durable result of one publication settlement."""

    PUBLISHED = "published"
    BLOCKED = "blocked"
    REJECTED = "rejected"


class RefreshPublicationFenceError(RuntimeError):
    """A durable source or local-edit publication fence refused the swap."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class PublicationSettlementFailure(RuntimeError):
    """Settlement rolled back and recorded its durable failure outcome."""


@dataclass(frozen=True, slots=True)
class PublicationSettlementCommand:
    """Prepared candidate plus evidence; settlement owns ``session``'s finish."""

    session: AsyncSession
    dataset: Any
    dataset_id: uuid.UUID
    job_id: uuid.UUID
    attempt_id: uuid.UUID
    staging_table: str
    metadata: dict[str, Any]
    sample_values: dict[str, Any]
    three_d: dict[str, Any]
    user_id: str
    source_filename: str | None
    source_format: str
    original_srid: int | None
    source_url: str
    origin_ref: dict[str, Any]
    schema_diff: dict[str, Any]
    source_binding: dict[str, Any]
    is_refresh: bool
    expected_feature_count: int | None
    content_digest: str | None
    staged_geometry_type: str | None
    staged_srid: int | None
    staged_coordinate_dimension: int | None
    accepted_fingerprint: str | None
    accepted_run_id: str | None
    origin_binding: tuple[str | None, dict[str, Any] | None, str | None] | None
    failure_contacted_origin: bool
    credential_for_error_scrubbing: str | None = None


def _service_refresh_error_code(exc: BaseException) -> str:
    """Map a settlement failure onto the existing refresh-run vocabulary."""
    from app.platform.refresh.credentials import (
        CredentialExpiredError,
        CredentialStoreUnavailable,
    )

    if isinstance(exc, CatalogLockConflict):
        return CATALOG_LOCK_CONFLICT_CODE
    if isinstance(exc, CredentialExpiredError):
        return "credential_expired"
    if isinstance(exc, CredentialStoreUnavailable):
        return "credential_store_unavailable"
    if isinstance(exc, RefreshPublicationFenceError):
        return exc.code
    if getattr(exc, "code", None) in (498, 499):
        return "credential_expired"
    return "service_refresh_failed"


def _verification(command: PublicationSettlementCommand) -> dict[str, Any] | None:
    if not command.is_refresh:
        return None
    assert command.content_digest is not None
    return refresh_policy.verify_service_refresh(
        source_binding=command.source_binding,
        schema_diff=command.schema_diff,
        expected_feature_count=command.expected_feature_count,
        fetched_feature_count=command.metadata.get("feature_count"),
        content_digest=command.content_digest,
        staged_geometry_type=command.staged_geometry_type,
        staged_srid=command.staged_srid,
        staged_coordinate_dimension=command.staged_coordinate_dimension,
        accepted_fingerprint=command.accepted_fingerprint,
        accepted_run_id=command.accepted_run_id,
    )


async def _enforce_refresh_publication_fence(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    dataset: Any,
    verification: dict[str, Any] | None,
) -> None:
    """Refuse a late swap after a scheduled source rebind or local edit."""
    if verification is None:
        return

    from app.platform.extensions import get_processing_port
    from app.platform.refresh.models import DatasetRefreshRun

    run = await session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job_id)
    )
    if run is None or run.source_binding_fingerprint is None:
        return

    record_cls = get_processing_port().get_record_orm_class()
    current_origin, current_record_modified_at = (
        await session.execute(
            select(dataset.__class__.origin_ref, record_cls.updated_at)
            .join(record_cls, record_cls.id == dataset.record_id)
            .where(dataset.__class__.id == dataset.id)
        )
    ).one()
    if not isinstance(current_origin, dict):
        raise RefreshPublicationFenceError(
            "source_changed", "Refresh source changed before publication."
        )
    try:
        current_fingerprint = (
            refresh_policy.canonical_service_source_binding_fingerprint(current_origin)
        )
    except ValueError as exc:
        raise RefreshPublicationFenceError(
            "source_changed", "Refresh source changed before publication."
        ) from exc
    if current_fingerprint != run.source_binding_fingerprint:
        raise RefreshPublicationFenceError(
            "source_changed", "Refresh source changed before publication."
        )
    if (
        run.local_edit_baseline is not None
        and current_record_modified_at is not None
        and current_record_modified_at > run.local_edit_baseline
    ):
        raise RefreshPublicationFenceError(
            "local_edits_changed", "Dataset changed locally before refresh publication."
        )


async def _settle_nonpublication(
    command: PublicationSettlementCommand, verification: dict[str, Any]
) -> PublicationOutcome:
    """Commit a blocked or rejected verification without changing live data."""
    session = command.session
    rejected = verification["decision"] == "rejected"
    if rejected:
        error_code, message = refresh_policy.refresh_rejection_diagnostic(verification)
    else:
        error_code = "review_required"
        message = "Review the detected changes before publication."

    from app.platform.extensions import get_processing_port
    from app.platform.jobs.heartbeat import require_ingest_job_update

    await require_ingest_job_update(
        session,
        command.job_id,
        command.attempt_id,
        values={
            "status": "failed",
            "error_message": redact_failure_reason(message),
            "completed_at": datetime.now(timezone.utc),
        },
    )
    port = get_processing_port()
    await lock_catalog_rows(
        session,
        dataset_cls=port.get_dataset_orm_class(),
        record_cls=port.get_record_orm_class(),
        dataset_id=command.dataset.id,
        record_id=command.dataset.record_id,
        lock_timeout=WORKER_LOCK_TIMEOUT,
    )
    command.dataset.last_checked_at = datetime.now(timezone.utc)
    command.dataset.schema_drift_status = drift_status_from_diff(command.schema_diff)
    if rejected:
        await record_refresh_failure(
            session,
            ingest_job_id=command.job_id,
            error_code=error_code,
            error_message=message,
            contacted_origin=False,
            feature_count_after=command.metadata.get("feature_count"),
            schema_diff=command.schema_diff,
            verification=verification,
        )
        outcome = PublicationOutcome.REJECTED
    else:
        await record_refresh_blocked(
            session,
            ingest_job_id=command.job_id,
            feature_count_after=command.metadata.get("feature_count"),
            schema_diff=command.schema_diff,
            verification=verification,
        )
        outcome = PublicationOutcome.BLOCKED
    await session.commit()
    return outcome


async def _record_settlement_failure(
    command: PublicationSettlementCommand,
    exc: BaseException,
    verification: dict[str, Any] | None,
) -> None:
    """Roll back the candidate and terminalize its attempt in a fresh session."""
    await command.session.rollback()
    from app.core.db import async_session

    async with async_session() as session:
        job = await load_job_for_error_write(
            session,
            command.job_id,
            command.attempt_id,
            task_name="publication_settlement",
        )
        if job is not None:
            await _cleanup_staging_on_failure(
                session,
                staging_table=command.staging_table,
                job=job,
                exc=exc,
                task_name="publication_settlement",
                attempt_id=command.attempt_id,
            )
        await record_refresh_failure(
            session,
            ingest_job_id=command.job_id,
            error_code=_service_refresh_error_code(exc),
            error_message=exc,
            contacted_origin=False,
            feature_count_after=command.metadata.get("feature_count"),
            schema_diff=command.schema_diff,
            verification=verification,
        )
        contact_stamped = False
        if command.failure_contacted_origin and command.origin_binding is not None:
            bound_uri, bound_ref, bound_format = command.origin_binding
            outcome = await session.execute(
                update(type(command.dataset))
                .where(
                    type(command.dataset).id == command.dataset_id,
                    type(command.dataset).origin_uri.is_not_distinct_from(bound_uri),
                    type(command.dataset).origin_ref.is_not_distinct_from(bound_ref),
                    type(command.dataset).source_format.is_not_distinct_from(
                        bound_format
                    ),
                )
                .values(last_checked_at=datetime.now(timezone.utc))
            )
            contact_stamped = bool(outcome.rowcount)
        await session.commit()
    if contact_stamped:
        await invalidate_catalog_cache()


async def commit_publication(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    task: str,
) -> bool:
    """Commit the transaction that publishes this attempt.

    Returns True when the commit is acknowledged. Returns False when the
    acknowledgement was lost but a probe of the job row shows the commit
    landed; a cancellation that lost it is absorbed, so the caller goes on to
    its post-commit steps. Re-raises when the commit did not land. Every
    replacement path turns its job row ``complete`` in the publishing
    transaction, which is what the probe reads.
    """
    try:
        await session.commit()
    except (
        Exception,
        asyncio.CancelledError,
    ) as exc:  # broad: a lost acknowledgement can surface as any error
        if not await publish_commit_landed(
            job_id, attempt_id, job_id=str(job_id), task=task
        ):
            raise
        absorb_cancellation(exc)
        return False
    return True


async def _invalidate_after_commit(
    job_id: uuid.UUID, live_table_name: str | None = None
) -> None:
    """Purge the caches a committed settlement changed; a failure is only logged."""
    async with cleanup_step("publication catalog cache", job_id=str(job_id)):
        await invalidate_catalog_cache()
    if live_table_name is not None:
        async with cleanup_step("publication tile cache", job_id=str(job_id)):
            await invalidate_tile_cache_for_table(live_table_name)


async def settle_publication(
    command: PublicationSettlementCommand,
) -> PublicationOutcome:
    """Settle a prepared candidate and own its session's commit or rollback."""
    verification: dict[str, Any] | None = None
    try:
        from app.platform.jobs.heartbeat import require_ingest_job_update

        await require_ingest_job_update(
            command.session,
            command.job_id,
            command.attempt_id,
            values={"heartbeat_at": datetime.now(timezone.utc)},
        )
        verification = _verification(command)
        if verification is not None and verification["decision"] != "allowed":
            outcome = await _settle_nonpublication(command, verification)
            await _invalidate_after_commit(command.job_id)
            return outcome

        version = await _apply_reupload_swap(
            command.session,
            dataset=command.dataset,
            staging_table=command.staging_table,
            metadata=command.metadata,
            sample_values=command.sample_values,
            three_d=command.three_d,
            user_id=command.user_id,
            source_filename=command.source_filename,
            source_format=command.source_format,
            original_srid=command.original_srid,
            source_url=command.source_url,
            origin_ref=command.origin_ref,
            pre_catalog_write=partial(
                _enforce_refresh_publication_fence,
                command.session,
                job_id=command.job_id,
                dataset=command.dataset,
                verification=verification,
            ),
        )
        live_table_name = command.dataset.table_name
        await require_ingest_job_update(
            command.session,
            command.job_id,
            command.attempt_id,
            values={
                "status": "complete",
                "completed_at": datetime.now(timezone.utc),
            },
        )
        await record_refresh_success(
            command.session,
            ingest_job_id=command.job_id,
            dataset=command.dataset,
            dataset_version_id=version.id,
            feature_count_after=command.metadata.get("feature_count"),
            schema_diff=command.schema_diff,
            verification=verification,
            contacted_origin=True,
        )
        await commit_publication(
            command.session,
            job_id=command.job_id,
            attempt_id=command.attempt_id,
            task="publication_settlement",
        )
    except (
        Exception
    ) as exc:  # broad: settlement preserves last-known-good on every pre-commit failure
        scrub_secret_from_exception(exc, command.credential_for_error_scrubbing)
        await _record_settlement_failure(command, exc, verification)
        raise PublicationSettlementFailure("Publication settlement failed.") from exc

    await _invalidate_after_commit(command.job_id, live_table_name)
    return PublicationOutcome.PUBLISHED
