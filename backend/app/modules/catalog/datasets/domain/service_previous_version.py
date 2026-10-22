"""A dataset's kept previous versions: their summary, a restore's admission, and their drop.

A previous version is a table a replacement or restore replaced, kept under
the name ``dataset_versions.kept_table`` records. The worker publishes a
restore; this module admits it and drops the tables on request.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import EDIT_METADATA
from app.core.record_types import capabilities
from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref
from app.modules.catalog.datasets.domain.schemas import PreviousVersionResponse
from app.platform.jobs import ledger
from app.platform.relations import dependent_relations, relation_present
from app.platform.jobs.heartbeat import previous_version_name_claimed
from app.platform.jobs.models import (
    ADMITTED_CAPABILITY_METADATA_KEY,
    EXPECTED_PREVIOUS_VERSION_KEY,
    IngestJob,
)
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    ACTIVE_RUN_STATUSES,
    DatasetBusyError,
    create_pending_run,
)


logger = structlog.get_logger(__name__)


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
_NOT_KEPT = (
    404,
    "no_previous_version",
    "This dataset does not keep that version. Reload the dataset and try again.",
)
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


async def previous_version_summaries(
    db: AsyncSession, dataset: Any
) -> list[PreviousVersionResponse]:
    """The dataset's kept versions, newest first, with the feature count each version recorded."""
    from app.modules.catalog.collections.models import DatasetVersion

    rows = await db.execute(
        select(
            DatasetVersion.version_number,
            DatasetVersion.kept_at,
            DatasetVersion.kept_bytes,
            DatasetVersion.feature_count,
        )
        .where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.kept_table.is_not(None),
        )
        .order_by(DatasetVersion.version_number.desc())
    )
    return [
        PreviousVersionResponse(
            version_number=row.version_number,
            retained_at=row.kept_at,
            size_bytes=row.kept_bytes,
            feature_count=row.feature_count,
        )
        for row in rows
    ]


async def _kept_tables(db: AsyncSession, dataset_id: uuid.UUID) -> dict[int, str]:
    """The dataset's kept versions and their tables, newest first."""
    from app.modules.catalog.collections.models import DatasetVersion

    rows = await db.execute(
        select(DatasetVersion.version_number, DatasetVersion.kept_table)
        .where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.kept_table.is_not(None),
        )
        .order_by(DatasetVersion.version_number.desc())
    )
    return dict(rows.tuples().all())


async def _require_version(
    db: AsyncSession, dataset: Any, version: int, *, newest: bool
) -> str:
    """The table keeping ``version``; refuses unless it is kept, and with ``newest``, the newest kept one."""
    kept = await _kept_tables(db, dataset.id)
    if newest:
        if not kept:
            raise PreviousVersionRefused(*_NONE)
        if next(iter(kept)) != version:
            raise PreviousVersionRefused(*_CHANGED)
    elif version not in kept:
        raise PreviousVersionRefused(*_NOT_KEPT)
    return kept[version]


async def admit_restore(
    db: AsyncSession,
    dataset: Any,
    *,
    user_id: uuid.UUID,
    expected: int,
    newest: bool = False,
) -> tuple[IngestJob, DatasetRefreshRun]:
    """Create the restore of kept version ``expected`` in the caller's transaction; never commits.

    Raises ``PreviousVersionRefused`` before writing when the dataset has no
    feature table or does not keep ``expected`` (with ``newest``, as its
    newest kept version), and after a rollback when another run is active.
    """
    if not capabilities(dataset.record.record_type).feature_table:
        raise PreviousVersionRefused(*_NOT_APPLICABLE)
    await _require_version(db, dataset, expected, newest=newest)
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
            ADMITTED_CAPABILITY_METADATA_KEY: EDIT_METADATA,
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


async def _drop_kept_table(
    db: AsyncSession, dataset: Any, name: str, *, schema: str
) -> None:
    """Drop one kept table; never commits.

    A table under the name that another dataset uses as its own is left in
    place.
    """
    if await previous_version_name_claimed(db, name):
        logger.warning("previous_version_drop_skipped", dataset_id=str(dataset.id))
        return
    kept = _safe_table_ref(name, schema=schema)
    if await relation_present(db, schema, name):
        await db.execute(text(f"LOCK TABLE {kept} IN ACCESS EXCLUSIVE MODE"))
        if dependents := await dependent_relations(db, schema, name):
            raise PreviousVersionRefused(
                409,
                "previous_version_in_use",
                f"{', '.join(dependents)} "
                f"{'depends' if len(dependents) == 1 else 'depend'} on this "
                "dataset's previous version. Drop or redefine them, then "
                "try again.",
            )
    await db.execute(text(f"DROP TABLE IF EXISTS {kept}"))


async def drop_kept_versions(db: AsyncSession, dataset: Any, *, schema: str) -> None:
    """Drop every table this dataset keeps a previous version in; never commits.

    Call holding the dataset's job rows. Read under them: a replacement that
    committed while the caller waited for them kept a version the caller has
    not seen.
    """
    for name in (await _kept_tables(db, dataset.id)).values():
        await _drop_kept_table(db, dataset, name, schema=schema)


async def drop_previous_version(
    db: AsyncSession,
    dataset: Any,
    *,
    user_id: uuid.UUID,
    expected: int,
    newest: bool = False,
) -> None:
    """Drop kept version ``expected`` in the caller's transaction; never commits.

    With ``newest``, it must be the newest kept version. Takes the job rows,
    the table and then the catalog rows, the order a publishing worker and a
    dataset delete take them. Refuses while any run is active, since a
    restore reads the table before it holds its job row.
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.modules.audit.service import AuditEvent, audit_emit
    from app.modules.catalog.collections.models import DatasetVersion
    from app.modules.catalog.features.service import lock_catalog_rows_for_write
    from app.platform.catalog_locks import lock_ingest_jobs

    await lock_ingest_jobs(db, job_cls=IngestJob, dataset_id=dataset.id)
    await _refuse_while_running(db, dataset.id)
    name = await _require_version(db, dataset, expected, newest=newest)
    await _drop_kept_table(
        db, dataset, name, schema=tenant_data_schema(current_tenant_var.get())
    )
    await lock_catalog_rows_for_write(db, dataset)
    # A run admitted before the row lock committed is visible now.
    await _refuse_while_running(db, dataset.id)
    await _require_version(db, dataset, expected, newest=newest)
    await db.execute(
        update(DatasetVersion)
        .where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.version_number == expected,
        )
        .values(kept_table=None, kept_at=None, kept_bytes=None, kept_refreshed_at=None)
    )
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
