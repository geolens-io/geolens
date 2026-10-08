"""Accepting a blocked refresh run once, for the refresh endpoint.

A blocked service refresh or re-upload is accepted by fetching again under the
accepted fingerprint. A blocked file replacement is accepted by a new job over
the upload its blocked job kept.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import defer_async_with_tenant
from app.core.identity import Identity
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.schemas import DatasetRefreshResponse
from app.platform.extensions import get_catalog_port
from app.platform.jobs import ledger
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.verification import (
    REVIEW_SUPERSEDED,
    canonical_service_source_binding_fingerprint,
)
from app.platform.refresh.service import DatasetBusyError, create_pending_run

# What a manifest apply wrote on its job, so an accepted run publishes the
# manifest's record metadata as the blocked one would have.
_MANIFEST_RECORD_KEYS = ("title", "summary", "visibility", "record_status")


async def accepted_refresh_fingerprint(
    db: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    run_id: uuid.UUID | None,
) -> str | None:
    """Resolve the approval token from an actionable blocked run."""
    if run_id is None:
        return None
    accepted_run = await db.scalar(
        select(DatasetRefreshRun).where(
            DatasetRefreshRun.id == run_id,
            DatasetRefreshRun.dataset_id == dataset_id,
            DatasetRefreshRun.status == "blocked",
        )
    )
    verification = accepted_run.verification if accepted_run is not None else None
    fingerprint = (
        verification.get("review_fingerprint")
        if isinstance(verification, dict)
        else None
    )
    consumed_by = (
        verification.get("acceptance_consumed_by_run_id")
        if isinstance(verification, dict)
        else None
    )
    if not isinstance(fingerprint, str) or consumed_by is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The selected run is not an actionable blocked refresh.",
        )
    return fingerprint


async def consume_blocked_refresh_acceptance(
    db: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    blocked_run_id: uuid.UUID,
    new_run_id: uuid.UUID,
    fingerprint: str,
) -> None:
    """Atomically mark the matching blocked run as consumed by this dispatch."""
    consumed = await db.scalar(
        text(
            """
            UPDATE catalog.dataset_refresh_runs
            SET verification = verification || jsonb_build_object(
                'acceptance_consumed_by_run_id', CAST(:new_run_id AS text)
            )
            WHERE id = :blocked_run_id
              AND dataset_id = :dataset_id
              AND status = 'blocked'
              AND verification->>'review_fingerprint' = :fingerprint
              AND NOT (verification ? 'acceptance_consumed_by_run_id')
            RETURNING id
            """
        ),
        {
            "blocked_run_id": str(blocked_run_id),
            "dataset_id": str(dataset_id),
            "new_run_id": str(new_run_id),
            "fingerprint": fingerprint,
        },
    )
    if consumed is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The selected blocked refresh was already accepted or changed.",
        )


async def held_reupload_binding(
    db: AsyncSession, *, dataset_id: uuid.UUID, run_id: uuid.UUID | None
) -> dict | None:
    """The source a held service re-upload fetched, or None for any other run.

    A re-upload's fingerprint identifies the changes its preview showed, not
    the data it fetched, so it records no identity check. Its acceptance is
    fetched and judged as a re-upload, which compares the same changes.
    """
    if run_id is None:
        return None
    verification = await db.scalar(
        select(DatasetRefreshRun.verification).where(
            DatasetRefreshRun.id == run_id,
            DatasetRefreshRun.dataset_id == dataset_id,
            DatasetRefreshRun.origin_kind == "service",
        )
    )
    if (
        not isinstance(verification, dict)
        or verification.get("identity_check") != "unavailable"
    ):
        return None
    binding = verification.get("source_binding")
    return binding if isinstance(binding, dict) else {}


async def refuse_unless_reupload_source_current(
    db: AsyncSession, binding: dict | None, origin_ref: object
) -> None:
    """Refuse accepting a held re-upload whose source is no longer the dataset's.

    The acceptance fetches the dataset's source, and the changes a person
    accepted describe another one.
    """
    if binding is None:
        return
    current = origin_ref if isinstance(origin_ref, dict) else {}
    try:
        same = canonical_service_source_binding_fingerprint(
            current
        ) == canonical_service_source_binding_fingerprint(binding)
    except ValueError:
        same = False
    if not same:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_changed",
                "message": (
                    "This re-upload fetched a different source than the "
                    "dataset's current one. Re-upload it again to review it."
                ),
            },
        )


async def blocked_run_origin_kind(
    db: AsyncSession, *, dataset_id: uuid.UUID, run_id: uuid.UUID | None
) -> str | None:
    """The door the run to accept came through, or None when there is no such run."""
    if run_id is None:
        return None
    return await db.scalar(
        select(DatasetRefreshRun.origin_kind).where(
            DatasetRefreshRun.id == run_id,
            DatasetRefreshRun.dataset_id == dataset_id,
        )
    )


def _upload_unavailable(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "upload_unavailable", "message": message},
    )


def _accepted_upload_metadata(
    blocked_job: IngestJob,
    *,
    dataset_id: uuid.UUID,
    run_id: uuid.UUID,
    fingerprint: str,
    held_version: int | None,
) -> dict:
    blocked = blocked_job.user_metadata or {}
    carried = {
        key: value
        for key, value in blocked.items()
        if key == "srid_override"
        or key.startswith("manifest_")
        or ("manifest_key" in blocked and key in _MANIFEST_RECORD_KEYS)
    }
    return {
        **carried,
        "reupload": True,
        "dataset_id": str(dataset_id),
        "accepted_refresh_fingerprint": fingerprint,
        "accepted_refresh_run_id": str(run_id),
        "accepted_from_job_id": str(blocked_job.id),
        "accepted_dataset_version": held_version,
    }


async def dispatch_upload_acceptance(
    db: AsyncSession,
    *,
    dataset,
    dataset_id: uuid.UUID,
    user: Identity,
    run_id: uuid.UUID,
    token: str | None,
) -> DatasetRefreshResponse:
    """Queue a new replacement job over a blocked file run's kept upload.

    The run is accepted once: the acceptance is consumed in the transaction
    that admits the new run, and a failed or cancelled attempt gives it back.
    Refuses with 409 ``review_superseded`` when the dataset's data was
    replaced after the run was held.
    """
    if token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "credential_not_applicable",
                "message": (
                    "Accepting a file replacement contacts no service. Send "
                    "the request without a credential."
                ),
            },
        )
    fingerprint = await accepted_refresh_fingerprint(
        db, dataset_id=dataset_id, run_id=run_id
    )
    blocked_run = await db.get(DatasetRefreshRun, run_id)
    held_version = (blocked_run.verification or {}).get("live_version")
    # Held until commit, so the retention purge skips the job and keeps its
    # upload; a job the purge already took is gone by the time this returns.
    blocked_job = await db.scalar(
        select(IngestJob)
        .join(DatasetRefreshRun, DatasetRefreshRun.ingest_job_id == IngestJob.id)
        .where(DatasetRefreshRun.id == run_id, IngestJob.dataset_id == dataset_id)
        .with_for_update(read=True, key_share=True, of=IngestJob)
    )
    if blocked_job is None or not blocked_job.file_path:
        raise _upload_unavailable(
            "The upload this run staged is gone. Upload the file again."
        )
    from app.platform.jobs.router import staged_input_available

    available, reason = await staged_input_available(blocked_job)
    if not available:
        raise _upload_unavailable(
            reason or "The upload this run staged is gone. Upload the file again."
        )

    user_id = user.id
    job = ledger.create(
        db,
        created_by=user_id,
        dataset_id=dataset_id,
        source_filename=blocked_job.source_filename,
        file_path=blocked_job.file_path,
        source_layer=blocked_job.source_layer,
        user_metadata=_accepted_upload_metadata(
            blocked_job,
            dataset_id=dataset_id,
            run_id=run_id,
            fingerprint=fingerprint,
            held_version=held_version,
        ),
    )
    await db.flush()
    try:
        run = await create_pending_run(
            db,
            dataset_id=dataset_id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=user_id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
    except DatasetBusyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": (
                    "A refresh is already running for this dataset. "
                    "Wait for it to finish, then try again."
                ),
            },
        ) from exc
    # Read after the run is admitted: a replacement that published first is
    # visible here, and one that comes later waits behind this run.
    current_version = await db.scalar(
        select(Dataset.current_version).where(Dataset.id == dataset_id)
    )
    if held_version is None or current_version != held_version:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "review_superseded", "message": REVIEW_SUPERSEDED},
        )
    await consume_blocked_refresh_acceptance(
        db,
        dataset_id=dataset_id,
        blocked_run_id=run_id,
        new_run_id=run.id,
        fingerprint=fingerprint,
    )
    job_id, attempt_id, new_run_id, file_path = (
        job.id,
        job.attempt_id,
        run.id,
        job.file_path,
    )
    await db.commit()

    async def _defer() -> None:
        await defer_async_with_tenant(
            get_catalog_port().reupload_file_task(),
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            dataset_id=str(dataset_id),
            file_path=file_path,
            user_id=str(user_id),
        )

    # Failing the job and run gives the acceptance back.
    await defer_with_orphan_guard(
        _defer,
        rollback=make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue the accepted replacement"
        ),
        db=db,
        job=job,
    )
    return DatasetRefreshResponse(
        run_id=new_run_id,
        job_id=job_id,
        dataset_id=dataset_id,
        origin_kind="upload",
        trigger="manual",
        status="pending",
        message="Accepted replacement queued",
    )
