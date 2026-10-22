"""Restore or drop a dataset's kept previous versions."""

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
from app.modules.catalog.datasets.domain.service import (
    PreviousVersionRefused,
    admit_restore,
    drop_previous_version,
    get_dataset,
)
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.dataset_origin import classify_origin
from app.platform.extensions import get_catalog_port
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.request_credential import refuse_publish_key
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


async def _restore(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    user: Identity,
    version_number: int,
    *,
    newest: bool,
) -> RestorePreviousVersionResponse:
    dataset = await _writable_dataset(db, dataset_id, user)
    # A restore can reinstate only an upload's or a drawn layer's binding, so
    # restoring over a service, STAC or table binding would lose it for good.
    if classify_origin(dataset.source_format, dataset.record.record_type) not in (
        "upload",
        "created",
    ):
        refuse_publish_key(
            db, "A publish key can't restore over a dataset bound to a remote origin"
        )
    try:
        job, run = await admit_restore(
            db, dataset, user_id=user.id, expected=version_number, newest=newest
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


async def _drop(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    user: Identity,
    version_number: int,
    *,
    newest: bool,
) -> Response:
    dataset = await _writable_dataset(db, dataset_id, user)
    try:
        await drop_previous_version(
            db, dataset, user_id=user.id, expected=version_number, newest=newest
        )
    except PreviousVersionRefused as exc:
        await db.rollback()
        raise _refusal(exc) from exc
    await db.commit()
    await invalidate_catalog_cache()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{dataset_id}/previous-versions/{version_number}/restore",
    response_model=RestorePreviousVersionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def restore_kept_version(
    dataset_id: uuid.UUID,
    version_number: int,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> RestorePreviousVersionResponse:
    """Publish one of the dataset's kept previous versions as its live data again.

    The dataset detail lists the kept versions in ``previous_versions``. The
    restore runs as a job and a refresh run with origin kind ``restore``, and
    publishes a new version that names the restored one in
    ``restored_from_version``. The data it replaces, including any feature
    edits made since, becomes a kept version in turn. Scheduled refreshes of
    the dataset are held afterwards.

    Refuses with 422 ``restore_not_applicable`` for a dataset without a
    feature table, 404 ``no_previous_version`` when the dataset does not keep
    ``version_number``, and 409 ``dataset_busy`` while another refresh,
    replacement or restore is active.
    """
    return await _restore(db, dataset_id, user, version_number, newest=False)


@router.delete(
    "/{dataset_id}/previous-versions/{version_number}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_kept_version(
    dataset_id: uuid.UUID,
    version_number: int,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete one of the dataset's kept previous versions, so it can no longer be restored.

    Refuses with 404 ``no_previous_version`` when the dataset does not keep
    ``version_number``, 409 ``previous_version_in_use`` while a view or
    foreign key elsewhere reads its table, and 409 ``dataset_busy`` while a
    refresh, replacement or restore is active.
    """
    return await _drop(db, dataset_id, user, version_number, newest=False)


@router.post(
    "/{dataset_id}/previous-version/restore",
    response_model=RestorePreviousVersionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    deprecated=True,
)
async def restore_previous_version(
    dataset_id: uuid.UUID,
    body: RestorePreviousVersionRequest,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> RestorePreviousVersionResponse:
    """Publish the dataset's newest kept version as its live data again.

    Deprecated: use ``POST /previous-versions/{version_number}/restore``.
    Behaves like it, and also refuses with 409 ``previous_version_changed``
    when ``expected_version_number`` is not the newest kept version.
    """
    return await _restore(
        db, dataset_id, user, body.expected_version_number, newest=True
    )


@router.delete(
    "/{dataset_id}/previous-version",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    deprecated=True,
)
async def delete_previous_version(
    dataset_id: uuid.UUID,
    expected_version_number: int = Query(
        description="The newest kept version, which the caller confirmed deleting"
    ),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete the dataset's newest kept version, so it can no longer be restored.

    Deprecated: use ``DELETE /previous-versions/{version_number}``. Behaves
    like it, and also refuses with 409 ``previous_version_changed`` when
    ``expected_version_number`` is not the newest kept version.
    """
    return await _drop(db, dataset_id, user, expected_version_number, newest=True)
