"""A feature dataset's retention setting: keep only its last N days of rows."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, update
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.core.upload_errors import refusal_detail
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import (
    check_dataset_write_access,
    lock_dataset_rows_for_write,
)
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.domain.schemas import (
    DatasetRetention,
    DatasetRetentionResponse,
    DatasetRetentionUpdate,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.catalog.features.retention import (
    RetentionRefused,
    check_retention,
    count_rows_past,
    hold_table_for_setting,
    relation_kind_refusal,
)
from app.platform.cache.tiles import invalidate_catalog_cache
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE
)


def _as_instant(cutoff: datetime | date) -> datetime:
    """The cutoff as a UTC instant; a date column's is UTC midnight of its date."""
    if not isinstance(cutoff, datetime):
        return datetime.combine(cutoff, time.min, tzinfo=timezone.utc)
    return cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)


def _refused(exc: RetentionRefused) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=refusal_detail(exc)
    )


async def _hold_qualifying_table(db: AsyncSession, dataset: Dataset) -> None:
    """Refuse a relation that is no plain table, then hold the table to the end
    of the request, before any catalog row, the order feature writes use."""
    try:
        refusal = await relation_kind_refusal(db, dataset.table_name)
        if refusal is not None:
            raise refusal
        await hold_table_for_setting(db, dataset.table_name)
    except RetentionRefused as exc:
        raise _refused(exc)


async def _locked_cutoff(
    db: AsyncSession, dataset: Dataset, retention: DatasetRetention
) -> datetime | date:
    """Check the setting against the dataset as it stands under the locks.

    The dataset is reloaded first: a replacement may have changed it while
    this request waited for them.
    """
    try:
        await db.refresh(dataset)
        await db.refresh(dataset.record)
    except InvalidRequestError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    try:
        return await check_retention(db, dataset, retention)
    except RetentionRefused as exc:
        raise _refused(exc)


@router.put("/{dataset_id}/retention/", response_model=DatasetRetentionResponse)
async def set_dataset_retention(
    dataset_id: uuid.UUID,
    body: DatasetRetentionUpdate,
    request: Request,
    dry_run: bool = Query(
        False, description="Check the setting and count its rows without saving it."
    ),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DatasetRetentionResponse:
    """Set or clear how many days of rows a feature dataset keeps.

    Hourly worker runs delete rows whose retention column is older than the
    cutoff, in batches, so a large backlog can take several runs; rows where
    it is null are kept. A dry run counts the rows past the cutoff now in
    `rows_past_cutoff`; a save skips that scan and returns null. The
    instance's dataset editing switch does not apply: this is the owner's
    setting, not an edit.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)

    retention = body.retention
    rows_past_cutoff = 0 if dry_run else None
    cutoff = None
    if retention is not None:
        await _hold_qualifying_table(db, dataset)

    if dry_run:
        if retention is not None:
            cutoff = await _locked_cutoff(db, dataset, retention)
            rows_past_cutoff = await count_rows_past(
                db, dataset.table_name, retention.column, cutoff
            )
    else:
        await lock_dataset_rows_for_write(db, dataset)
        if retention is not None:
            cutoff = await _locked_cutoff(db, dataset, retention)
        # Both columns, from the request: the instance predates the lock, so
        # assigning to it would write only what differs from a stale value.
        stored = await db.execute(
            update(Dataset)
            .where(Dataset.id == dataset_id)
            .values(
                retention_column=retention.column if retention else None,
                retention_days=retention.days if retention else None,
            )
            .returning(Dataset.id)
            .execution_options(synchronize_session=False)
        )
        if stored.one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        # Written outright: the loaded record predates the lock, so assigning
        # an equal updated_by would write nothing. The trigger sets the time.
        await db.execute(
            update(Record)
            .where(Record.id == dataset.record_id)
            .values(updated_at=func.now(), updated_by=user.id)
            .execution_options(synchronize_session=False)
        )
        db.expire(dataset.record, ["updated_at", "updated_by"])
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="metadata.edit",
                resource_type="dataset",
                resource_id=dataset_id,
                details=body.model_dump(mode="json"),
                ip_address=request.client.host if request.client else None,
            ),
        )
        await db.commit()
        await invalidate_catalog_cache()

    return DatasetRetentionResponse(
        retention=retention,
        rows_past_cutoff=rows_past_cutoff,
        cutoff=_as_instant(cutoff) if cutoff is not None else None,
    )
