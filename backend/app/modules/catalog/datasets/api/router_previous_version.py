"""Restore or drop a dataset's previous version."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import defer_async_with_tenant
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import check_dataset_write_access
from app.modules.catalog.datasets.domain.schemas import (
    RestorePreviousVersionRequest,
    RestorePreviousVersionResponse,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.catalog.datasets.domain.service_previous_version import (
    PreviousVersionRefused,
    admit_restore,
    drop_previous_version,
)
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.extensions import get_catalog_port
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets - Refresh"],
    responses=ERROR_RESPONSES_WRITE,
)


def _refusal(exc: PreviousVersionRefused) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


async def _writable_dataset(db: AsyncSession, dataset_id: uuid.UUID, user: Identity):
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)
    return dataset


@router.post(
    "/{dataset_id}/previous-version/restore",
    response_model=RestorePreviousVersionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def restore_previous_version(
    dataset_id: uuid.UUID,
    body: RestorePreviousVersionRequest,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> RestorePreviousVersionResponse:
    """Publish the dataset's previous version as its live data again.

    The previous version is the data the last replacement or restore
    replaced. The restore runs as a job and a refresh run with origin kind
    ``restore``, and publishes a new version that names the restored one in
    ``restored_from_version``. The data it replaces, including any feature
    edits made since, becomes the previous version in turn. Scheduled
    refreshes of the dataset are held afterwards.

    Refuses with 422 ``restore_not_applicable`` for a dataset without a
    feature table, 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while another refresh, replacement or restore is
    active.
    """
    dataset = await _writable_dataset(db, dataset_id, user)
    try:
        job, run = await admit_restore(
            db, dataset, user_id=user.id, expected=body.expected_version_number
        )
    except PreviousVersionRefused as exc:
        raise _refusal(exc) from exc
    job_id, attempt_id, run_id = job.id, job.attempt_id, run.id
    await db.commit()

    async def _defer_restore() -> None:
        await defer_async_with_tenant(
            get_catalog_port().restore_previous_version_task(),
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            dataset_id=str(dataset_id),
            user_id=str(user.id),
        )

    await defer_with_orphan_guard(
        _defer_restore,
        rollback=make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue restore task"
        ),
        db=db,
        job=job,
    )
    return RestorePreviousVersionResponse(job_id=job_id, run_id=run_id)


@router.delete(
    "/{dataset_id}/previous-version",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_previous_version(
    dataset_id: uuid.UUID,
    expected_version_number: int = Query(
        description="The previous version the caller confirmed deleting"
    ),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete the dataset's previous version, so it can no longer be restored.

    Refuses with 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while a refresh, replacement or restore is
    active.
    """
    dataset = await _writable_dataset(db, dataset_id, user)
    try:
        await drop_previous_version(
            db, dataset, user_id=user.id, expected=expected_version_number
        )
    except PreviousVersionRefused as exc:
        await db.rollback()
        raise _refusal(exc) from exc
    await db.commit()
    await invalidate_catalog_cache()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
