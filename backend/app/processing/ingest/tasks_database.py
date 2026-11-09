"""Procrastinate tasks that import and refresh a table from a database connection."""

from __future__ import annotations

import asyncio
import uuid
from functools import partial

import structlog
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from app.core.db.tenant_session import tenant_task
from app.core.failure_reason import FixedReason
from app.platform.catalog_locks import CATALOG_LOCK_CONFLICT_CODE, CatalogLockConflict
from app.platform.database_sources import (
    DatabaseSourceError,
    TableGeometry,
    probe_table_geometry,
)
from app.platform.dataset_origin import (
    DatabaseSource,
    Unavailable,
    bound_pointer,
    classify_origin,
    read_source,
    still_bound,
)
from app.platform.jobs import ledger
from app.platform.jobs.heartbeat import (
    JOB_ERROR_WRITE_TIMEOUT_MS,
    attempt_scoped_staging_table,
    claim_job_attempt_and_start_heartbeat,
    log_job_error_write_failure,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
)
from app.platform.jobs.models import DATABASE_SOURCE_METADATA_KEY
from app.processing.ingest.database_import import (
    DatabaseImportError,
    copy_database_table,
    require_importable_table,
)
from app.platform.refresh import verification as refresh_policy
from app.platform.refresh.service import drift_status_from_diff, record_refresh_blocked
from app.platform.source_copies import refuse_second_copy
from app.processing.ingest import catalog_projection
from app.processing.ingest.publication import (
    PUBLISH,
    Failure,
    PublicationCommit,
    Published,
    Verdict,
    settle_replacement,
)
from app.processing.ingest.publish_followups import run_publish_followups
from app.processing.ingest.tasks_common import (
    IngestContext,
    _append_job_warning,
    _append_mercator_clip_warning,
    _bind_task_log_context,
    _current_tenant_schema,
    _finalize_ingest,
    _install_reupload_table,
    _job_phase_session,
    _write_reupload_catalog,
    cleanup_step,
    task_app,
)
from app.processing.ingest.tasks_reupload import (
    RefreshPublicationFenceError,
    _LiveComparison,
    _assert_geometry_survives,
    _data_revision_baseline,
    _enforce_refresh_publication_fence,
    _held_live_geometry_types,
    _hold_live_table,
    _live_content_digest,
    _live_geometry_types,
    _quicklook_table,
    _staged_geometry_contract,
    _table_row_count,
)
from app.processing.ingest.tasks_staging import (
    _cleanup_staging_on_failure,
    _run_staging_pipeline,
)
from app.processing.ingest.tasks_vector import (
    _drop_attempt_staging_table,
    _publish_attempt_staging_table,
)

MISSING_CRS_DATABASE = FixedReason(
    "Missing CRS: the table's geometries have no SRID (SRID 0), or it has no "
    "rows or only empty geometries. Import it again and choose its coordinate "
    "system.",
    code="missing_crs_database",
)

MIXED_SRID_DATABASE = FixedReason(
    "The table's geometries use more than one SRID, so no single coordinate "
    "system describes them. Give them one SRID in a view and import that.",
    code="mixed_srid_database",
)


class DatabaseRefusal(DatabaseImportError):
    """A table GeoLens won't copy as it stands; ``reason`` says why."""

    def __init__(self, reason: FixedReason) -> None:
        super().__init__(str(reason))
        self.reason = reason


def job_database_source(user_metadata: object) -> DatabaseSource | Unavailable:
    """The table a job's metadata names, or the key it lacks."""
    stored = (
        user_metadata.get(DATABASE_SOURCE_METADATA_KEY)
        if isinstance(user_metadata, dict)
        else None
    )
    source = read_source("database", stored)
    if isinstance(source, (DatabaseSource, Unavailable)):
        return source
    return Unavailable("database", "connection")


async def probe_import_geometry(
    connection: str, schema_name: str, table_name: str
) -> TableGeometry:
    """The column GDAL will read, its SRID, and whether it mixes SRIDs."""
    try:
        return await probe_table_geometry(connection, schema_name, table_name)
    except DatabaseSourceError as exc:
        raise DatabaseImportError(str(exc)) from None


async def _rename_reserved(session, job, table: str) -> None:
    from app.processing.ingest.metadata import rename_reserved_columns
    from app.processing.ingest.warnings import make_reserved_rename_warning

    renames = await rename_reserved_columns(
        session, table, schema=_current_tenant_schema()
    )
    if renames:
        _append_job_warning(job, make_reserved_rename_warning(renames))


def chosen_srid(probed: int | None, fallback: int | None) -> int | None:
    """The table's own SRID; ``fallback`` only when its geometries carry none.

    Import and refresh choose alike, so a refresh of an unchanged table never
    reports a changed SRID.
    """
    return probed if probed is not None else fallback


@task_app.task(queue="ingest", retry=0)
@tenant_task
async def ingest_database(
    job_id: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: copy one table from a database connection into PostGIS.

    The connection, schema and table come from the job row, never from task
    arguments, and the connection's address and login from settings. No
    session is held across the SQL Server reads or ogr2ogr.
    """
    _bind_task_log_context(task_name="ingest_database", job_id=job_id)
    from app.processing.ingest.service import generate_table_name

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="ingest"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    staging_table_name = ""
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        async with _job_phase_session(
            job_uuid, phase="phase1", attempt_id=attempt_uuid
        ) as (session, job):
            if job is None:
                return
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid, job=job, current_step="validating"
            )
            if heartbeat_task is None:
                return
            um = job.user_metadata or {}
            source = job_database_source(um)
            if not isinstance(source, DatabaseSource):
                raise DatabaseImportError("This job names no database table.")
            require_importable_table(source.connection, source.schema, source.table)
            srid_override = um.get("srid_override")
            source_filename = job.source_filename
            table_name, collision_warning = await generate_table_name(
                um.get("title") or source.table, session
            )
            staging_table_name = attempt_scoped_staging_table(table_name, attempt_uuid)
            if collision_warning:
                job.user_metadata = {**um, "collision_warning": collision_warning}
                um = job.user_metadata
            await session.commit()

        probed = await probe_import_geometry(
            source.connection, source.schema, source.table
        )
        srid = probed.srid
        effective_srid = chosen_srid(srid, srid_override)
        if probed.mixed or effective_srid is None:
            async with _job_phase_session(
                job_uuid, phase="refused", attempt_id=attempt_uuid
            ) as (session, job):
                if job is not None:
                    await ledger.fail(
                        session,
                        job_uuid,
                        attempt_uuid,
                        reason=MIXED_SRID_DATABASE
                        if probed.mixed
                        else MISSING_CRS_DATABASE,
                    )
                    await session.commit()
            return

        async with _job_phase_session(
            job_uuid, phase="progress_write_ogr2ogr", attempt_id=attempt_uuid
        ) as (progress_session, progress_job):
            if progress_job is not None:
                progress_job.current_step = "ogr2ogr"
                progress_job.progress = 0.1
                await progress_session.commit()

        await copy_database_table(
            source.connection,
            schema_name=source.schema,
            table_name=source.table,
            target_schema=_current_tenant_schema(),
            target_table=staging_table_name,
            srid=effective_srid,
        )

        async with _job_phase_session(
            job_uuid,
            phase="phase2",
            attempt_id=attempt_uuid,
            require_status="running",
        ) as (session, job):
            if job is None or await refuse_second_copy(session, job, attempt_uuid):
                return
            job.current_step = "finalize"
            job.progress = 0.7
            await _rename_reserved(session, job, staging_table_name)
            await _publish_attempt_staging_table(
                session,
                job_id=job_uuid,
                attempt_id=attempt_uuid,
                staging_table=staging_table_name,
                live_table=table_name,
            )
            await _finalize_ingest(
                IngestContext(
                    session=session,
                    job=job,
                    table_name=table_name,
                    user_id=user_id,
                    has_geometry=None,
                    effective_srid=effective_srid,
                    source_format="database",
                    source_filename=source_filename,
                    original_srid=srid,
                    user_metadata=um,
                    attempt_id=attempt_uuid,
                    origin_ref=source.ref(),
                    origin_uri=source.uri,
                )
            )

    except Exception as exc:  # broad: SQL Server, GDAL and PostGIS can each fail; mark the job failed and re-raise
        try:
            async with _job_phase_session(
                job_uuid,
                phase="error_write",
                attempt_id=attempt_uuid,
                lock_and_statement_timeout_ms=JOB_ERROR_WRITE_TIMEOUT_MS,
            ) as (err_session, err_job):
                if err_job is not None:
                    await _cleanup_staging_on_failure(
                        err_session,
                        staging_table=staging_table_name,
                        job=err_job,
                        exc=exc,
                        task_name="ingest_database",
                        attempt_id=attempt_uuid,
                    )
                else:
                    structlog.get_logger().exception(
                        "Ingest task failed", job_id=job_id, task="ingest_database"
                    )
        except DBAPIError as write_failure:
            log_job_error_write_failure(
                write_failure, job_id=job_id, task="ingest_database"
            )
        raise
    finally:
        async with cleanup_step("ingest_database heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("ingest_database staging table", job_id=job_id):
            await _drop_attempt_staging_table(staging_table_name)
    async with cleanup_step("ingest_database follow-ups", job_id=job_id):
        await run_publish_followups(job_uuid, attempt_id=attempt_uuid)


class _DatabaseRefresh(_LiveComparison):
    """A database table read again into this attempt's table, then verified.

    The binding is the dataset's own, read while this run holds the dataset's
    one active refresh, and the connection is looked up by name again.
    """

    task = "refresh_database"
    staging = True
    raster_row = False
    catalog_event = "reupload_swap_catalog"

    def __init__(self, *, job_id: str, user_id: str):
        self.job_uuid = uuid.UUID(job_id)
        self.user_id = user_id
        self.measured_feature_count: int | None = None
        self.measured_schema_diff: dict | None = None
        self.verification: dict | None = None

    def prepare(self, job, dataset, staging_table: str) -> None:
        self.staging_table = staging_table
        self.live_table = dataset.table_name
        self.dataset_id = dataset.id
        self.live_feature_count = dataset.feature_count
        self.live_has_geometry = dataset.geometry_type is not None
        self.source = (
            read_source("database", dataset.origin_ref)
            if classify_origin(dataset.source_format) == "database"
            else None
        )
        self.bound = bound_pointer(dataset)
        self.stored_srid = dataset.srid
        self.source_filename = job.source_filename
        um = job.user_metadata or {}
        self.accepted_fingerprint = um.get("accepted_refresh_fingerprint")
        self.accepted_run_id = um.get("accepted_refresh_run_id")

    async def fetch(self) -> None:
        source = self.source
        if not isinstance(source, DatabaseSource):
            raise DatabaseImportError(
                "This dataset is no longer bound to a database table."
            )
        self.table = source
        require_importable_table(source.connection, source.schema, source.table)
        probed = await probe_import_geometry(
            source.connection, source.schema, source.table
        )
        if probed.mixed:
            raise DatabaseRefusal(MIXED_SRID_DATABASE)
        # SRID 0 or an empty table: the SRID the copy was imported under.
        self.srid = chosen_srid(probed.srid, self.stored_srid)
        if self.srid is None:
            raise DatabaseRefusal(MISSING_CRS_DATABASE)
        schema = _current_tenant_schema()
        await copy_database_table(
            source.connection,
            schema_name=source.schema,
            table_name=source.table,
            target_schema=schema,
            target_table=self.staging_table,
            srid=self.srid,
        )
        self.live_scan = await _live_geometry_types(
            self.live_table, schema=schema, dataset_id=self.dataset_id
        )
        if (
            await _table_row_count(self.staging_table, schema=schema)
            == self.live_feature_count
        ):
            self.live_content = await _live_content_digest(
                self.live_table,
                schema=schema,
                dataset_id=self.dataset_id,
                has_geometry=self.live_has_geometry,
            )

    async def stage(self, session, job, dataset) -> Verdict:
        from app.processing.ingest.metadata import (
            compute_table_content_digest,
            get_geometry_types,
        )

        schema = _current_tenant_schema()
        await _rename_reserved(session, job, self.staging_table)
        staged = await _run_staging_pipeline(
            session,
            table_name=self.staging_table,
            has_geometry=None,
            effective_srid=self.srid,
        )
        _assert_geometry_survives(
            record_type=dataset.record.record_type,
            geometry_type=dataset.geometry_type,
            has_geometry=staged.has_geometry,
        )
        _append_mercator_clip_warning(job, staged.mercator_clip)
        self.metadata = staged.metadata
        self.measurement = await catalog_projection.measure(
            session, dataset, table=self.staging_table, schema=schema, staged=staged
        )
        self.measured_feature_count = staged.metadata.get("feature_count")
        self.staged_contract = refresh_policy.geometry_contract(
            geometry_types=await get_geometry_types(
                session, self.staging_table, schema=schema
            ),
            srid=self.measurement.metadata.get("srid"),
            is_3d=self.measurement.three_d.get("is_3d"),
            n_dims=self.measurement.three_d.get("n_dims"),
        )
        self.staged_geometry = await _staged_geometry_contract(
            session, schema=schema, table=self.staging_table
        )
        self.content_digest = await compute_table_content_digest(
            session, self.staging_table, schema=schema, has_geometry=staged.has_geometry
        )
        return Verdict(verify=self._verify)

    async def _verify(self, session, dataset) -> Verdict:
        schema = _current_tenant_schema()
        await _hold_live_table(session, dataset, schema=schema)
        live_geometry_types = await _held_live_geometry_types(
            session, dataset, self.live_scan, schema=schema
        )
        self.measured_schema_diff = catalog_projection.schema_diff(
            dataset, self.measurement
        )
        geometry_type, srid, coordinate_dimension = self.staged_geometry
        source = self.table
        self.verification = refresh_policy.verify_database_refresh(
            source_binding={
                **source.ref(),
                "verification_policy": refresh_policy.DATABASE_SINGLE_READ_POLICY,
            },
            schema_diff=self.measured_schema_diff,
            fetched_feature_count=self.measured_feature_count,
            content_digest=self.content_digest,
            staged_geometry_type=geometry_type,
            staged_srid=srid,
            staged_coordinate_dimension=coordinate_dimension,
            live=refresh_policy.geometry_contract(
                geometry_types=live_geometry_types,
                srid=dataset.srid,
                is_3d=dataset.is_3d,
                n_dims=dataset.n_dims,
            ),
            staged=self.staged_contract,
            accepted_fingerprint=self.accepted_fingerprint,
            accepted_run_id=self.accepted_run_id,
            data_revision_baseline=await _data_revision_baseline(
                session,
                job_id=self.job_uuid,
                dataset_id=dataset.id,
                accepted_run_id=self.accepted_run_id,
            ),
            data_revision=dataset.data_revision,
        )
        if self.verification["decision"] == "allowed":
            await self._compare_live(session, dataset)
            return PUBLISH
        # The policy has no rejection, so a held-back run waits for review.
        return Verdict(
            publish=False,
            reason="Review the detected changes before publication.",
            settle=partial(self._hold_back, dataset=dataset),
        )

    async def _hold_back(self, session, *, dataset) -> None:
        # Lands only while the dataset still holds the binding this run read.
        await session.execute(
            update(type(dataset))
            .where(still_bound(type(dataset), dataset.id, self.bound))
            .values(
                schema_drift_status=drift_status_from_diff(self.measured_schema_diff)
            )
        )
        await record_refresh_blocked(
            session,
            ingest_job_id=self.job_uuid,
            feature_count_after=self.measured_feature_count,
            schema_diff=self.measured_schema_diff,
            verification=self.verification,
        )

    async def install(self, session, dataset) -> None:
        if self.unchanged:
            return
        await _install_reupload_table(
            session,
            dataset=dataset,
            staging_table=self.staging_table,
            measurement=self.measurement,
        )

    async def write(self, session, dataset) -> Published:
        await _enforce_refresh_publication_fence(
            session,
            job_id=self.job_uuid,
            dataset=dataset,
            verification=self.verification,
        )
        if self.unchanged:
            published = await self._publish_unchanged(
                session,
                dataset,
                field_labels=None,
                feature_count=self.measured_feature_count,
                contacted_origin=True,
                reembed=False,
            )
            # The table was just read, as in a changed swap.
            dataset.source_health = "healthy"
            return published
        source = self.table
        version, schema_diff = await _write_reupload_catalog(
            session,
            dataset=dataset,
            measurement=self.measurement,
            user_id=self.user_id,
            source_filename=self.source_filename,
            source_format="database",
            original_srid=self.srid,
            origin_ref=source.ref(),
            origin_uri=source.uri,
            field_labels=None,
            job_id=self.job_uuid,
        )
        return Published(
            dataset_version_id=version.id,
            feature_count=self.measured_feature_count,
            schema_diff=schema_diff,
            contacted_origin=True,
            verification=self.verification,
            live_table=dataset.table_name,
            quicklook_table=_quicklook_table(dataset, self.measurement),
        )

    def classify(self, exc: BaseException) -> Failure:
        if isinstance(exc, DatabaseRefusal):
            # The table as it stands, not a failed read: recorded, not raised.
            return Failure(exc.reason.code, reason=exc.reason, refused=True)
        if isinstance(exc, CatalogLockConflict):
            code = CATALOG_LOCK_CONFLICT_CODE
        elif isinstance(exc, RefreshPublicationFenceError):
            code = exc.code
        else:
            code = "database_refresh_failed"
        return Failure(
            code,
            feature_count_after=self.measured_feature_count,
            schema_diff=self.measured_schema_diff,
            verification=self.verification,
        )

    async def release(
        self, *, publication: PublicationCommit | None, failed: bool
    ) -> None:
        return None


@task_app.task(queue="ingest", retry=0)
@tenant_task
async def refresh_database(
    job_id: str,
    dataset_id: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: replace a database dataset's data with a fresh read.

    Verified under ``database_single_read_v1`` before it publishes.
    """
    _bind_task_log_context(
        task_name="refresh_database", job_id=job_id, dataset_id=dataset_id
    )
    await settle_replacement(
        _DatabaseRefresh(job_id=job_id, user_id=user_id),
        job_id=job_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
    )
