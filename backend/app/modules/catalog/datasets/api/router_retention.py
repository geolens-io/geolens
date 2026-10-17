"""A feature dataset's retention setting: keep only its last N days of rows."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import (
    check_dataset_write_access,
    lock_dataset_rows_for_write,
)
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.schemas import (
    DatasetRetentionResponse,
    DatasetRetentionUpdate,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.catalog.features.retention import (
    RetentionRefused,
    check_retention,
    count_rows_past,
)
from app.platform.cache.tiles import invalidate_catalog_cache
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE
)


def _wire_cutoff(cutoff: datetime | date) -> datetime | date:
    """A date column's cutoff stays a bare date; a naive timestamp's is UTC."""
    if isinstance(cutoff, datetime) and cutoff.tzinfo is None:
        return cutoff.replace(tzinfo=timezone.utc)
    return cutoff


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

    The worker deletes rows whose retention column is older than the cutoff on
    its next hourly run; rows where it is null are kept. `rows_past_cutoff`
    counts what that run would delete as of now. The instance's dataset
    editing switch does not apply: this is the owner's setting, not an edit.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)

    retention = body.retention
    rows_past_cutoff = 0
    cutoff = None
    if retention is not None:
        try:
            cutoff = await check_retention(db, dataset, retention)
        except RetentionRefused as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            )
        rows_past_cutoff = await count_rows_past(
            db, dataset.table_name, retention.column, cutoff
        )

    if not dry_run:
        await lock_dataset_rows_for_write(db, dataset)
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
        cutoff=_wire_cutoff(cutoff) if cutoff is not None else None,
    )
