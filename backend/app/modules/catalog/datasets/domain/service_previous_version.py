"""A dataset's previous version: its summary, a restore's admission, and its drop.

The previous version is the table the last replacement or restore replaced,
kept under ``previous_version_table``. The worker publishes a restore; this
module admits it and drops the table on request.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.record_types import capabilities
from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref
from app.modules.catalog.datasets.domain.schemas import PreviousVersionResponse
from app.platform.jobs import ledger
from app.platform.jobs.heartbeat import previous_version_table
from app.platform.jobs.models import EXPECTED_PREVIOUS_VERSION_KEY, IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    ACTIVE_RUN_STATUSES,
    DatasetBusyError,
    create_pending_run,
)


class PreviousVersionRefused(Exception):
    """A previous-version request the dataset's state refuses, with its HTTP answer."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


_NOT_APPLICABLE = (
    422,
    "restore_not_applicable",
    "Only datasets with a feature table keep a previous version.",
)
_NONE = (404, "no_previous_version", "This dataset has no previous version.")
_CHANGED = (
    409,
    "previous_version_changed",
    "The dataset's previous version is no longer the one you confirmed. "
    "Reload the dataset and try again.",
)
_BUSY = (
    409,
    "dataset_busy",
    "A refresh, replacement or restore is running for this dataset. Wait for "
    "it to finish, then try again.",
)


async def previous_version_summary(
    db: AsyncSession, dataset: Any
) -> PreviousVersionResponse | None:
    """The dataset's previous version, with the feature count its version recorded."""
    from app.modules.catalog.collections.models import DatasetVersion

    number = dataset.previous_version_number
    if number is None:
        return None
    feature_count = await db.scalar(
        select(DatasetVersion.feature_count).where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.version_number == number,
        )
    )
    return PreviousVersionResponse(
        version_number=number,
        retained_at=dataset.previous_version_retained_at,
        size_bytes=dataset.previous_version_bytes,
        feature_count=feature_count,
    )


def _require_version(dataset: Any, expected: int) -> None:
    if dataset.previous_version_number is None:
        raise PreviousVersionRefused(*_NONE)
    if dataset.previous_version_number != expected:
        raise PreviousVersionRefused(*_CHANGED)


async def admit_restore(
    db: AsyncSession, dataset: Any, *, user_id: uuid.UUID, expected: int
) -> tuple[IngestJob, DatasetRefreshRun]:
    """Create the restore's job and run in the caller's transaction; never commits.

    Raises ``PreviousVersionRefused`` before writing when the dataset has no
    feature table or no previous version, or it is not ``expected``, and after
    a rollback when another run is active.
    """
    if not capabilities(dataset.record.record_type).feature_table:
        raise PreviousVersionRefused(*_NOT_APPLICABLE)
    _require_version(dataset, expected)
    job = ledger.create(
        db,
        created_by=user_id,
        dataset_id=dataset.id,
        source_filename=dataset.source_filename,
        user_metadata={
            "refresh": True,
            "dataset_id": str(dataset.id),
            "origin_kind": "restore",
            EXPECTED_PREVIOUS_VERSION_KEY: expected,
        },
    )
    await db.flush()
    try:
        run = await create_pending_run(
            db,
            dataset_id=dataset.id,
            origin_kind="restore",
            trigger="manual",
            triggered_by=user_id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
    except DatasetBusyError as exc:
        await db.rollback()
        raise PreviousVersionRefused(*_BUSY) from exc
    return job, run


async def _refuse_while_running(db: AsyncSession, dataset_id: uuid.UUID) -> None:
    active = await db.scalar(
        select(DatasetRefreshRun.id)
        .where(
            DatasetRefreshRun.dataset_id == dataset_id,
            DatasetRefreshRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .limit(1)
    )
    if active is not None:
        raise PreviousVersionRefused(*_BUSY)


async def drop_previous_version(
    db: AsyncSession, dataset: Any, *, user_id: uuid.UUID, expected: int
) -> None:
    """Drop the dataset's previous version in the caller's transaction; never commits.

    Takes the job rows, the table and then the catalog rows, the order a
    publishing worker and a dataset delete take them. Refuses while any run
    is active, since a restore reads the table before it holds its job row.
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.modules.audit.service import AuditEvent, audit_emit
    from app.modules.catalog.features.service import lock_catalog_rows_for_write
    from app.platform.catalog_locks import lock_ingest_jobs

    await lock_ingest_jobs(db, job_cls=IngestJob, dataset_id=dataset.id)
    await _refuse_while_running(db, dataset.id)
    await db.refresh(dataset, ["previous_version_number"])
    _require_version(dataset, expected)
    previous = _safe_table_ref(
        previous_version_table(dataset.table_name, dataset.id),
        schema=tenant_data_schema(current_tenant_var.get()),
    )
    await db.execute(text(f"DROP TABLE IF EXISTS {previous}"))
    await lock_catalog_rows_for_write(db, dataset)
    # A run admitted before the row lock committed is visible now.
    await _refuse_while_running(db, dataset.id)
    await db.refresh(dataset, ["previous_version_number"])
    _require_version(dataset, expected)
    dataset.previous_version_number = None
    dataset.previous_version_retained_at = None
    dataset.previous_version_bytes = None
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="dataset.previous_version_dropped",
            resource_type="dataset",
            resource_id=dataset.id,
            details={"version_number": expected},
        ),
    )
