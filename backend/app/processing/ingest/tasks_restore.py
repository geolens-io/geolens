"""Procrastinate task: publish a dataset's previous version again.

The previous version is the table a replacement kept. Restoring it is a
replacement whose candidate is that table, so it runs through the settlement
seam like any other: the job row, the catalog rows, the run, the follow-ups
and the tile version are the publish path's own. The data it replaces becomes
the previous version in turn.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.db.tenant_session import tenant_task
from app.core.failure_reason import FixedReason
from app.core.record_types import capabilities
from app.platform.catalog_locks import CATALOG_LOCK_CONFLICT_CODE, CatalogLockConflict
from app.platform.jobs.models import EXPECTED_PREVIOUS_VERSION_KEY
from app.platform.jobs.heartbeat import (
    attempt_scoped_staging_table,
    previous_version_table,
)
from app.processing.ingest import catalog_projection
from app.processing.ingest.publication import (
    PUBLISH,
    Failure,
    PublicationCommit,
    Published,
    Verdict,
    settle_replacement,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _current_tenant_schema,
    install_candidate_table,
    stamp_previous_version,
    task_app,
)

# Why a restored dataset refuses scheduled refreshes until the hold is released.
RESTORED_HOLD = "restored"

_CHANGED = "previous_version_changed"
_NOT_APPLICABLE = "restore_not_applicable"


class RestoreRefused(Exception):
    """The previous version the restore was admitted for is not there to publish."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _RestorePreviousVersion:
    """The dataset's previous-version table, renamed over its live table."""

    task = "restore_previous_version"
    staging = False
    raster_row = False
    catalog_event = "restore_catalog"

    def __init__(self, *, user_id: str):
        self.user_id = user_id

    def prepare(self, job, dataset, staging_table: str) -> None:
        self.expected = (job.user_metadata or {}).get(EXPECTED_PREVIOUS_VERSION_KEY)
        self.previous = previous_version_table(dataset.table_name, dataset.id)
        # The live table waits under this name inside the publishing
        # transaction only, so a crash leaves nothing behind.
        self.holding = attempt_scoped_staging_table(dataset.table_name, job.attempt_id)

    async def fetch(self) -> None:
        return None

    async def stage(self, session, job, dataset) -> Verdict:
        if not capabilities(dataset.record.record_type).feature_table:
            raise RestoreRefused(
                _NOT_APPLICABLE,
                "This dataset has no feature table, so it has no previous "
                "version to restore.",
            )
        await self._require_previous(session, dataset)
        return PUBLISH

    async def install(self, session, dataset) -> None:
        # Measured here, under the job row, so a delete that takes the job
        # rows before dropping the table never waits on this read.
        await self._require_previous(session, dataset)
        schema = _current_tenant_schema()
        self.measurement = await catalog_projection.measure(
            session, dataset, table=self.previous, schema=schema
        )
        await install_candidate_table(
            session,
            dataset=dataset,
            candidate=self.previous,
            measurement=self.measurement,
            holding=self.holding,
        )

    async def write(self, session, dataset) -> Published:
        from app.platform.audit import AuditEvent, audit_emit
        from app.platform.extensions import get_processing_port

        DatasetVersion = get_processing_port().get_dataset_version_orm_class()
        actor_id = uuid.UUID(self.user_id)
        await session.refresh(dataset, ["current_version", "previous_version_number"])
        replaced = dataset.current_version
        restored = dataset.previous_version_number
        source = await session.scalar(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset.id,
                DatasetVersion.version_number == restored,
            )
        )

        schema_diff = await catalog_projection.project(
            session, dataset, self.measurement
        )
        await stamp_previous_version(session, dataset, replaced)
        dataset.current_version = replaced + 1
        dataset.scheduled_refresh_hold = RESTORED_HOLD
        dataset.record.updated_by = actor_id
        # Freshness describes the data that is live again. A first ingest
        # writes no version row, so its data dates from the dataset's creation.
        dataset.last_refreshed_at = (
            dataset.record.created_at if source is None else source.uploaded_at
        )

        version = DatasetVersion(
            dataset_id=dataset.id,
            version_number=replaced + 1,
            source_filename=None if source is None else source.source_filename,
            source_format=None if source is None else source.source_format,
            file_hash=None if source is None else source.file_hash,
            feature_count=self.measurement.metadata.get("feature_count"),
            srid=self.measurement.metadata.get("srid"),
            geometry_type=self.measurement.geometry_type,
            restored_from_version=restored,
            uploaded_by=actor_id,
        )
        session.add(version)
        await session.flush()
        await audit_emit(
            session,
            AuditEvent(
                user_id=actor_id,
                action="dataset.restore",
                resource_type="dataset",
                resource_id=dataset.id,
                details={
                    "version_number": replaced + 1,
                    "restored_from_version": restored,
                    "replaced_version": replaced,
                },
            ),
        )
        quicklook = (
            None if self.measurement.geometry_type is None else dataset.table_name
        )
        return Published(
            dataset_version_id=version.id,
            feature_count=self.measurement.metadata.get("feature_count"),
            schema_diff=schema_diff,
            contacted_origin=False,
            live_table=dataset.table_name,
            quicklook_table=quicklook,
        )

    def classify(self, exc: BaseException) -> Failure:
        if isinstance(exc, RestoreRefused):
            return Failure(exc.code, reason=FixedReason(str(exc), code=exc.code))
        if isinstance(exc, CatalogLockConflict):
            return Failure(CATALOG_LOCK_CONFLICT_CODE)
        return Failure("restore_failed")

    async def release(
        self, *, publication: PublicationCommit | None, failed: bool
    ) -> None:
        return None

    async def _require_previous(self, session, dataset) -> None:
        """Refuse unless the previous version is still the one admitted."""
        from sqlalchemy import text

        from app.platform.extensions import get_processing_port
        from app.processing.ingest.metadata import _qtable

        Dataset = get_processing_port().get_dataset_orm_class()
        number = await session.scalar(
            select(Dataset.previous_version_number).where(Dataset.id == dataset.id)
        )
        present = await session.scalar(
            text("SELECT to_regclass(:previous) IS NOT NULL"),
            {"previous": _qtable(self.previous, schema=_current_tenant_schema())},
        )
        if number is None or number != self.expected or not present:
            raise RestoreRefused(
                _CHANGED,
                "The dataset's previous version changed or was deleted before "
                "it could be restored. Check its version history and try again.",
            )


@task_app.task(queue="ingest", retry=0)
@tenant_task
async def restore_previous_version(
    job_id: str,
    dataset_id: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Background task: publish the dataset's previous version as its live data."""
    _bind_task_log_context(
        task_name="restore_previous_version", job_id=job_id, dataset_id=dataset_id
    )
    await settle_replacement(
        _RestorePreviousVersion(user_id=user_id),
        job_id=job_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
    )
