"""The refresh strategy for a dataset imported from a database connection.

Admission, the run row and the dispatch follow the registered-table strategy
in ``router_refresh.py``; the worker reads the table again by connection name
and verifies the copy under ``database_single_read_v1`` before it publishes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db.tenant_session import defer_async_with_tenant
from app.core.identity import Identity
from app.core.permissions import EDIT_METADATA
from app.modules.catalog.datasets.api.refresh_acceptance import (
    consume_blocked_refresh_acceptance,
)
from app.modules.catalog.datasets.domain.schemas import DatasetRefreshResponse
from app.platform.dataset_origin import DatabaseSource, classify_origin, read_source
from app.platform.extensions import get_catalog_port
from app.platform.jobs import ledger
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import ADMITTED_CAPABILITY_METADATA_KEY
from app.platform.refresh.service import DatasetBusyError, create_pending_run
from app.platform.refresh.verification import DATABASE_SINGLE_READ_POLICY


def _conflict(code: str, message: str, **extra: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, "origin_kind": "database", **extra},
    )


def _resolve_database_origin(dataset) -> DatabaseSource:
    """The table a database dataset is bound to, or the 409 that says why not."""
    if classify_origin(dataset.source_format, dataset.record.record_type) != "database":
        raise _conflict(
            "refresh_not_applicable",
            "This dataset is not imported from a database connection.",
        )
    source = read_source("database", dataset.origin_ref)
    if not isinstance(source, DatabaseSource):
        raise _conflict(
            "origin_unavailable",
            "This dataset's source binding does not record which table it "
            "was imported from. Import the table again.",
        )
    if source.connection not in settings.database_sources:
        raise _conflict(
            "database_connection_missing",
            f"The database connection {source.connection!r} is no longer "
            "configured. Ask an administrator to restore it.",
            connection=source.connection,
        )
    return source


@dataclass(frozen=True)
class AcceptedRun:
    """A blocked run this refresh publishes over, and its review fingerprint."""

    run_id: uuid.UUID
    fingerprint: str


async def dispatch_database_refresh(
    db: AsyncSession,
    *,
    dataset,
    dataset_id: uuid.UUID,
    user: Identity,
    token: str | None,
    accepted: AcceptedRun | None = None,
) -> DatasetRefreshResponse:
    """Admit and dispatch a fresh read of a database dataset's table.

    The binding is read again once the run is reserved, as on the other
    strategies, so a re-upload that lands meanwhile can't be undone by a
    refresh of the table it replaced.
    """
    candidate = _resolve_database_origin(dataset)
    if token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "credential_not_applicable",
                "message": (
                    "This dataset is read through a database connection the "
                    "deployment configures, which needs no credential. Send "
                    "the request without one."
                ),
            },
        )

    user_id = user.id
    job = ledger.create(
        db,
        created_by=user_id,
        dataset_id=dataset_id,
        user_metadata={
            "reupload": True,
            "refresh": True,
            "dataset_id": str(dataset_id),
            "origin_kind": "database",
            "verification_policy": DATABASE_SINGLE_READ_POLICY,
            ADMITTED_CAPABILITY_METADATA_KEY: EDIT_METADATA,
            **(
                {
                    "accepted_refresh_run_id": str(accepted.run_id),
                    "accepted_refresh_fingerprint": accepted.fingerprint,
                }
                if accepted is not None
                else {}
            ),
        },
    )
    await db.flush()
    try:
        run = await create_pending_run(
            db,
            dataset_id=dataset_id,
            origin_kind="database",
            trigger="api",
            triggered_by=user_id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
            verification_policy=DATABASE_SINGLE_READ_POLICY,
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

    await db.refresh(
        dataset, ["origin_uri", "origin_ref", "source_format", "feature_count"]
    )
    try:
        origin = _resolve_database_origin(dataset)
    except HTTPException:
        await db.rollback()
        raise
    if origin != candidate:
        await db.rollback()
        raise _conflict(
            "origin_changed",
            "This dataset's source changed while the refresh was being "
            "queued, so it was not started. Check the new source and try again.",
        )
    if accepted is not None:
        await consume_blocked_refresh_acceptance(
            db,
            dataset_id=dataset_id,
            blocked_run_id=accepted.run_id,
            new_run_id=run.id,
            fingerprint=accepted.fingerprint,
        )

    job.source_filename = f"{origin.schema}.{origin.table}"
    run.feature_count_before = dataset.feature_count
    job_id = job.id
    attempt_id = job.attempt_id
    run_id = run.id
    await db.commit()

    async def _defer_refresh() -> None:
        await defer_async_with_tenant(
            get_catalog_port().refresh_database_task(),
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            dataset_id=str(dataset_id),
            user_id=str(user_id),
        )

    await defer_with_orphan_guard(
        _defer_refresh,
        rollback=make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue refresh task"
        ),
        db=db,
        job=job,
    )
    return DatasetRefreshResponse(
        run_id=run_id,
        job_id=job_id,
        dataset_id=dataset_id,
        origin_kind="database",
        trigger="api",
        status="pending",
        message="Refresh queued from the database table",
    )
