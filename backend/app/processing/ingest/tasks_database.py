"""Procrastinate tasks that import a table from a database connection."""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.exc import DBAPIError

from app.core.db.tenant_session import tenant_task
from app.core.failure_reason import FixedReason
from app.platform.database_sources import DatabaseSourceError, probe_table_geometry
from app.platform.dataset_origin import (
    DatabaseSource,
    Unavailable,
    database_origin_uri,
    read_source,
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
from app.processing.ingest.publish_followups import run_publish_followups
from app.processing.ingest.tasks_common import (
    IngestContext,
    _append_job_warning,
    _bind_task_log_context,
    _current_tenant_schema,
    _finalize_ingest,
    _job_phase_session,
    cleanup_step,
    task_app,
)
from app.processing.ingest.tasks_staging import (
    _cleanup_staging_on_failure,
)
from app.processing.ingest.tasks_vector import (
    _drop_attempt_staging_table,
    _publish_attempt_staging_table,
)

MISSING_CRS_DATABASE = FixedReason(
    "Missing CRS: the table's geometries have SRID 0 or the table has no "
    "rows. Import it again and choose its coordinate system.",
    code="missing_crs_database",
)


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


async def probe_import_srid(
    connection: str, schema_name: str, table_name: str
) -> int | None:
    """The SRID of the column GDAL will read, or ``None`` for 0 or no rows."""
    try:
        probed = await probe_table_geometry(connection, schema_name, table_name)
    except DatabaseSourceError as exc:
        raise DatabaseImportError(str(exc)) from None
    return probed.srid


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

        srid = await probe_import_srid(source.connection, source.schema, source.table)
        effective_srid = srid_override if srid_override is not None else srid
        if effective_srid is None:
            async with _job_phase_session(
                job_uuid, phase="missing_crs", attempt_id=attempt_uuid
            ) as (session, job):
                if job is not None:
                    await ledger.fail(
                        session, job_uuid, attempt_uuid, reason=MISSING_CRS_DATABASE
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
            if job is None:
                return
            job.current_step = "finalize"
            job.progress = 0.7
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(
                session, staging_table_name, schema=_current_tenant_schema()
            )
            if reserved_renames:
                from app.processing.ingest.warnings import (
                    make_reserved_rename_warning,
                )

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))
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
                    origin_ref={
                        "connection": source.connection,
                        "schema": source.schema,
                        "table": source.table,
                    },
                    origin_uri=database_origin_uri(
                        source.connection, source.schema, source.table
                    ),
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
