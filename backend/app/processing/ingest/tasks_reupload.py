"""Procrastinate task definitions for file and service re-upload workflows."""

import asyncio
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import structlog
from sqlalchemy import select, text, update

from app.core.db.tenant_session import tenant_task
from app.core.failure_reason import redact_failure_reason
from app.core.upload_errors import geometry_loss_refusal
from app.core.url_redaction import scrub_secret_from_exception
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.catalog_locks import (
    CATALOG_LOCK_CONFLICT_CODE,
    CatalogLockConflict,
)
from app.platform.dataset_origin import classify_origin, service_layer_identity
from app.platform.jobs.heartbeat import (
    attempt_scoped_staging_table,
    claim_job_attempt_and_start_heartbeat,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.processing.raster.cog import sha256_file

from app.platform.jobs.models import owned_presigned_staging_key
from app.platform.refresh.credentials import resolve_worker_credential
from app.platform.refresh.service import (
    claim_run_for_job,
    record_refresh_failure,
    record_refresh_success,
)
from app.processing.ingest import catalog_projection
from app.processing.ingest.publication import (
    PublicationCommit,
    PublicationOutcome,
    PublicationSettlementCommand,
    PublicationSettlementFailure,
    _service_refresh_error_code,
    commit_publication,
    settle_publication,
)
from app.processing.ingest.source_format import derive_source_format
from app.processing.ingest.tasks_common import (
    _append_job_warning,
    cleanup_step,
    _append_mercator_clip_warning,
    _apply_reupload_swap,
    _bind_task_log_context,
    _detect_3d_and_promote_elev,
    load_job_for_error_write,
    _current_tenant_role,
    _current_tenant_schema,
    _run_service_import_with_wfs_fallback,
    apply_manifest_record_metadata,
    invalidate_tile_cache_for_table,
    purge_token_on_failure,
    resolve_service_type,
    task_app,
)
from app.processing.ingest.tasks_staging import (
    StagingResult,
    _archive_original_file,
    _cleanup_staging_on_failure,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
    _run_staging_pipeline,
    _validate_upload_file_safety,
)


# A keyed admitted occurrence has its own wall-clock budget.  The queue claim
# deadline ends at the pending -> running CAS; it must not terminate a
# legitimate fetch that started before that deadline.
_KEYED_REFRESH_EXECUTION_TIMEOUT_SECONDS = 1_800.0


def require_scheduled_execution_claim(fn):
    """Fence direct/late scheduled invocations before they contact a source."""

    @wraps(fn)
    async def _wrapped(*args, **kwargs):
        scheduled_execution_key = kwargs.get("scheduled_execution_key")
        if scheduled_execution_key is not None:
            try:
                execution_key = uuid.UUID(str(scheduled_execution_key))
                job_id = uuid.UUID(str(kwargs["job_id"]))
                attempt_id = uuid.UUID(str(kwargs["attempt_id"]))
            except (KeyError, TypeError, ValueError):
                structlog.get_logger().warning(
                    "scheduled_refresh_execution_claim_invalid"
                )
                return None

            from app.core.db import async_session
            from app.platform.refresh.models import DatasetRefreshRun

            async with async_session() as session:
                matching_run = await session.scalar(
                    select(DatasetRefreshRun).where(
                        DatasetRefreshRun.ingest_job_id == job_id,
                        DatasetRefreshRun.status == "running",
                        DatasetRefreshRun.execution_key == execution_key,
                    )
                )
            if matching_run is None:
                structlog.get_logger().warning(
                    "scheduled_refresh_execution_not_claimed", job_id=str(job_id)
                )
                return None
            try:
                async with asyncio.timeout(_KEYED_REFRESH_EXECUTION_TIMEOUT_SECONDS):
                    return await fn(*args, **kwargs)
            except TimeoutError:
                # ``asyncio.timeout`` injects cancellation, so the service
                # task's ordinary Exception handler does not get a chance to
                # settle the admitted run. Terminalize it here before the
                # queue sees the timeout; a late worker cannot publish after
                # this transition.
                await _settle_keyed_execution_timeout(job_id, attempt_id)
                raise
        return await fn(*args, **kwargs)

    return _wrapped


async def _settle_keyed_execution_timeout(
    job_id: uuid.UUID, attempt_id: uuid.UUID
) -> bool:
    """Atomically settle a timed-out keyed run within the error-write budget."""
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.db import async_session
    from app.platform.jobs.heartbeat import (
        JOB_ERROR_WRITE_TIMEOUT_MS,
        arm_job_error_write_budget,
        log_job_error_write_failure,
    )
    from app.platform.refresh.service import record_refresh_failure

    TIMEOUT_ERROR_MESSAGE = "The admitted refresh exceeded its execution time limit."
    try:
        async with async_session() as session:
            # The session's pool checkout needs its own deadline; SET LOCAL
            # only protects statements after the connection is acquired.
            await asyncio.wait_for(
                session.connection(), timeout=JOB_ERROR_WRITE_TIMEOUT_MS / 1000
            )
            await arm_job_error_write_budget(session)
            settled_job = await update_ingest_job_for_attempt(
                session,
                job_id,
                attempt_id,
                values={
                    "status": "failed",
                    "error_message": TIMEOUT_ERROR_MESSAGE,
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            if settled_job:
                await record_refresh_failure(
                    session,
                    ingest_job_id=job_id,
                    error_code="scheduled_execution_timeout",
                    error_message=TIMEOUT_ERROR_MESSAGE,
                    contacted_origin=False,
                )
            await session.commit()
            return settled_job
    except (SQLAlchemyError, TimeoutError) as write_failure:
        log_job_error_write_failure(
            write_failure,
            job_id=str(job_id),
            task="scheduled_refresh_execution_timeout",
        )
        return False


async def _drop_attempt_staging_table(staging_table: str) -> None:
    """Best-effort cleanup limited to one attempt-owned staging table."""
    if not staging_table:
        return

    from app.core.db import async_session
    from app.processing.ingest.metadata import _qtable
    from sqlalchemy import text

    try:
        async with async_session() as session:
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS "
                    f"{_qtable(staging_table, schema=_current_tenant_schema())} CASCADE"
                )
            )
            await session.commit()
    except Exception:  # broad: cleanup must not mask the ingest result
        structlog.get_logger().warning(
            "attempt_staging_cleanup_failed",
            staging_table=staging_table,
            exc_info=True,
        )


def _assert_geometry_survives(
    *, record_type: str | None, geometry_type: str | None, has_geometry: bool
) -> None:
    """Raise the preview door's refusal when a replacement would strip geometry.

    fix(#2031): both worker paths reach the same ``record_type`` re-derivation —
    the file path knows from ogrinfo, the service path from the staging table.
    """
    geometry_loss = geometry_loss_refusal(
        record_type=record_type,
        dataset_geometry_type=geometry_type,
        source_has_geometry=has_geometry,
    )
    if geometry_loss:
        from app.processing.ingest.ogr import IngestionError

        raise IngestionError(geometry_loss)


async def _detect_reupload_crs(
    file_path: str,
    layer_name: str | None,
    user_metadata: dict,
    *,
    original_filename: str | None = None,
    record_type: str | None,
    dataset_geometry_type: str | None,
) -> tuple[dict, int]:
    """Detect CRS/geometry for a reupload file and resolve the effective SRID.

    GPKG-01 Phase 1058: ``layer_name`` targets the user-chosen layer in a
    multi-layer GPKG rather than defaulting to ``layers[0]``.

    fix(#541): applies the same missing-CRS gate as ``ingest_file``,
    raising ``IngestionError`` rather than silently falling through to the
    4326 default and corrupting the replacement dataset.

    fix(#2031): and the preview door's geometry-loss refusal, for the client
    that skipped the preview. ``record_type`` is the dataset's CURRENT one.

    Returns (ogrinfo result dict, effective_srid).
    """
    from app.processing.ingest.ogr import IngestionError, run_ogrinfo
    from app.processing.ingest.tasks_common import check_missing_crs

    info = await run_ogrinfo(
        file_path, layer_name=layer_name, original_filename=original_filename
    )
    srid = info.get("srid")
    geometry_type = info.get("geometry_type")
    srid_override = user_metadata.get("srid_override")

    missing_crs = check_missing_crs(
        file_path=file_path,
        has_geometry=geometry_type is not None,
        detected_srid=srid,
        srid_override=srid_override,
    )
    if missing_crs:
        raise IngestionError(missing_crs)

    _assert_geometry_survives(
        record_type=record_type,
        geometry_type=dataset_geometry_type,
        has_geometry=geometry_type is not None,
    )

    effective_srid = (
        srid_override
        if srid_override is not None
        else (srid if srid is not None else 4326)
    )
    return info, effective_srid


async def _archive_after_publication(
    session,
    publication: PublicationCommit,
    *,
    job,
    dataset_id: uuid.UUID,
    file_path: str,
    job_id: str,
) -> None:
    """Archive the original file once the publish is confirmed; log a failure.

    The archive key is named after the file, so after an indeterminate publish
    it could overwrite the original of the version that is still live.
    """
    if not publication.confirmed:
        return
    async with cleanup_step("reupload_file archive", job_id=job_id):
        await session.refresh(job)
        await _archive_original_file(
            session,
            job=job,
            dataset_id=dataset_id,
            file_path=file_path,
            log_message="Failed to archive re-uploaded file to storage",
        )


@task_app.task(queue="ingest", retry=0, aliases=["app.ingest.tasks.reupload_file"])
@tenant_task
async def reupload_file(
    job_id: str,
    dataset_id: str,
    file_path: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: replace dataset data via staging table swap.

    Session lifecycle (gh #100 followup): the AsyncSession is split into two
    short-lived blocks so it is NOT held open across ``run_ogrinfo``,
    ``run_ogr2ogr``, or the ``asyncio.to_thread(sha256_file, ...)`` call.
    Holding a session across those long async boundaries in
    Python 3.14 + SQLAlchemy 2.0 + greenlet 3.3 corrupts the greenlet bridge
    state and the next ``session.execute()`` raises ``MissingGreenlet``
    (same root cause as gh #100 in ``ingest_file`` / ``ingest_raster``).
    """
    _bind_task_log_context(
        task_name="reupload_file", job_id=job_id, dataset_id=dataset_id
    )
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.metadata import _qtable
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr
    from app.platform.jobs.models import IngestJob
    from sqlalchemy import text
    from sqlalchemy.orm import joinedload

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="reupload"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    dataset_uuid = uuid.UUID(dataset_id)
    original_file_path = file_path
    final_status: str = "pending"
    # fix(#1207): captured in phase 1, swept in the finally.
    owned_staging_key: str | None = None
    staging_tn: str = ""
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        # Phase 1 (short-lived session): load job + dataset, mark running,
        # resolve, validate, drop stale staging table. Snapshot the values
        # needed for the long async work into local variables.
        async with async_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                )
            )
            job = job_result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job not found, skipping", job_id=job_id
                )
                return

            # fix(#1207): captured HERE, first thing after the row is in
            # hand, so every early exit below (dataset-missing, heartbeat
            # bail, download/validation failure) still reaches the
            # terminal `finally` with it set. Reads the DB column, not the
            # local `file_path` that resolve_file_path rebinds.
            owned_staging_key = owned_presigned_staging_key(
                job.id, job.user_metadata, job.file_path
            )

            dataset_result = await session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset_uuid)
            )
            dataset = dataset_result.scalar_one_or_none()
            if dataset is None:
                structlog.get_logger().warning(
                    "Dataset not found, skipping", dataset_id=dataset_id
                )
                return

            # 1. Update job to running
            staging_tn = attempt_scoped_staging_table(dataset.table_name, attempt_uuid)
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid
            )
            if heartbeat_task is None:
                return

            # feat(#1219): pending -> running, keyed on the job rather than a
            # run id threaded through task arguments (those are durable rows;
            # a new argument would break every in-flight job on deploy).
            # `started_at` stays at dispatch time, so the gap to this write
            # IS the queue wait.
            await claim_run_for_job(session, job_uuid)
            # fix(#1778): committed before the download, not after — this
            # holds a row lock on `dataset_refresh_runs` until commit, and
            # `cancel_job` transitions that row under a 2s lock_timeout, so
            # holding it across `resolve_file_path` made a cancel during
            # download 409 and roll back its own already-committed cancel.
            await session.commit()

            # Resolve S3 key to local file for ogr2ogr
            from app.processing.ingest.service import resolve_file_path

            file_path = await resolve_file_path(file_path, job_id)

            # Validate file content and safety before ogr2ogr (KISS-5).
            try:
                await _validate_upload_file_safety(
                    session,
                    file_path=file_path,
                    source_filename=job.source_filename,
                )
            except ValueError as exc:
                await update_ingest_job_for_attempt(
                    session,
                    job_uuid,
                    attempt_uuid,
                    values={
                        "status": "failed",
                        "error_message": redact_failure_reason(exc),
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
                # feat(#1219): RETURNS rather than raising, so the broad
                # handler below never sees it — without a terminal write
                # here the run would sit `running` until the sweep, instead
                # of the plain content rejection the user should read.
                await record_refresh_failure(
                    session,
                    ingest_job_id=job_uuid,
                    error_code="validation_failed",
                    error_message=exc,
                    contacted_origin=False,
                )
                await session.commit()
                Path(file_path).unlink(missing_ok=True)
                final_status = "failed"
                return

            # Snapshot values for phase 2 (job + dataset will be re-loaded;
            # these values are immutable for the duration of the task).
            source_filename = job.source_filename
            user_metadata = job.user_metadata or {}
            prior_record_type = dataset.record.record_type
            prior_geometry_type = dataset.geometry_type
            # GPKG-01 Phase 1058: snapshot the user-chosen layer so ogr2ogr
            # ingests the correct layer from multi-layer GPKG files.
            layer_name = job.source_layer  # None for single-layer files

            # Drop stale staging table from any prior failed attempt before
            # closing the session — ogr2ogr needs a clean target.
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS "
                    f"{_qtable(staging_tn, schema=_current_tenant_schema())} CASCADE"
                )
            )
            await session.commit()

        # Phase 1.5 (no session): ogrinfo, ogr2ogr subprocess, sha256.
        # Holding an AsyncSession across these would corrupt the greenlet
        # bridge state — same root cause as gh #100.

        # 2-3. Detect CRS from the new file, enforce the missing-CRS gate,
        # and resolve the effective SRID (override > detected > 4326).
        info, effective_srid = await _detect_reupload_crs(
            file_path,
            layer_name,
            user_metadata,
            original_filename=source_filename,
            record_type=prior_record_type,
            dataset_geometry_type=prior_geometry_type,
        )
        srid = info.get("srid")
        geometry_type = info.get("geometry_type")
        has_geometry = geometry_type is not None

        # 4. Load into staging table
        # GPKG-01 Phase 1058: pass layer_name to ogr2ogr to ingest the correct
        # layer from multi-layer GPKG files.
        db_conn_str = build_pg_conn_str()
        await run_ogr2ogr(
            file_path,
            staging_tn,
            db_conn_str,
            source_srid=srid,
            geometry_type=geometry_type,
            layer_name=layer_name,
            schema=_current_tenant_schema(),
            effective_srid=effective_srid,
            original_filename=source_filename,
        )

        # 7. Compute file hash (moved up — must be outside any session)
        file_hash = await asyncio.to_thread(sha256_file, file_path)
        source_format = await asyncio.to_thread(derive_source_format, file_path)

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): re-load job + dataset, run staging
        # pipeline, apply swap, archive, mark complete.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                )
            )
            job = job_result.scalar_one()

            dataset_result = await session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset_uuid)
            )
            dataset = dataset_result.scalar_one()

            # 4a. Rename source columns that collide with GeoLens-internal
            #     names. Runs BEFORE post-process steps so they cannot clash
            #     with source attributes.
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(
                session, staging_tn, schema=_current_tenant_schema()
            )
            if reserved_renames:
                from app.processing.ingest.warnings import make_reserved_rename_warning

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            # 4b. Shapefile-only: detect DBF 10-char truncation collisions.
            #     Keyed on the derived format, not the .zip suffix — a File
            #     Geodatabase arrives in a .zip too and has no DBF to truncate.
            if source_format == "shapefile":
                from app.processing.ingest.metadata import (
                    detect_dbf_truncation_collisions,
                )
                from app.processing.ingest.ogr import run_ogrinfo_preview
                from app.processing.ingest.warnings import make_dbf_truncation_warning

                preview_cols = info.get("columns") or []
                if not preview_cols:
                    # GPKG-01 Phase 1058: pass layer_name for multi-layer shapefiles (rare)
                    preview_info = await run_ogrinfo_preview(
                        file_path, sample_limit=0, layer_name=layer_name
                    )
                    preview_cols = preview_info.get("columns") or []
                dbf_collisions = detect_dbf_truncation_collisions(preview_cols)
                if dbf_collisions:
                    _append_job_warning(
                        job, make_dbf_truncation_warning(dbf_collisions)
                    )
                    structlog.get_logger().warning(
                        "Shapefile DBF 10-char truncation collision detected",
                        table=staging_tn,
                        collisions=dbf_collisions,
                    )

            # 5-6. Post-process staging table (shared pipeline)
            staging_result = await _run_staging_pipeline(
                session,
                table_name=staging_tn,
                has_geometry=has_geometry,
                effective_srid=effective_srid,
            )
            # The staging table, measured in the swap's transaction and never
            # carried forward from the preview, which can be minutes old.
            measurement = await catalog_projection.measure(
                session,
                dataset,
                table=staging_tn,
                schema=_current_tenant_schema(),
                staged=staging_result,
            )

            # fix(#888): tell the user when the Web Mercator clamp destroyed
            # geometry instead of leaving them to discover it downstream.
            _append_mercator_clip_warning(job, staging_result.mercator_clip)

            # 8. Apply shared reupload swap/version invariants
            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={"heartbeat_at": datetime.now(timezone.utc)},
            )
            version, schema_diff = await _apply_reupload_swap(
                session,
                dataset=dataset,
                staging_table=staging_tn,
                measurement=measurement,
                user_id=user_id,
                source_filename=source_filename,
                source_format=source_format,
                original_srid=srid,
                file_hash=file_hash,
                # fix(#1218): the new bytes came from a file, so the
                # binding says upload — even when the dataset was originally
                # a registered table or a service import.
                origin_ref={"filename": source_filename, "file_hash": file_hash},
            )
            # fix(#1472): a manifest re-apply whose fingerprint
            # changed lands on THIS path carrying the manifest's current
            # metadata.attribution — without this the swap installs new
            # data but leaves the old (now wrong) credit on it.
            # `dataset.record` is joinedloaded here, so no lazy load runs.
            await apply_manifest_record_metadata(session, dataset.record, user_metadata)

            # Captured pre-commit: the ORM attribute may be expired after commit.
            live_table_name = dataset.table_name

            # 9. Update job status to complete
            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={
                    "status": "complete",
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            # feat(#1219, #1223): the run's terminal status commits WITH the
            # job's, which is what makes "job complete, run still running"
            # unreachable — the stale-run sweep leans on that rather than
            # having to guess whether such a row was abandoned.
            # contacted_origin=False: these bytes came from the browser, so
            # nothing remote was reached and last_checked_at must not claim a
            # probe that never happened.
            await record_refresh_success(
                session,
                ingest_job_id=job_uuid,
                dataset=dataset,
                dataset_version_id=version.id,
                feature_count_after=measurement.metadata.get("feature_count"),
                schema_diff=schema_diff,
                contacted_origin=False,
            )
            publication = await commit_publication(
                session,
                job_id=job_uuid,
                attempt_id=attempt_uuid,
                task="reupload_file",
            )
            # A publish seen only through the probe keeps the upload, which
            # `final_status` licenses deleting.
            if publication is PublicationCommit.ACKNOWLEDGED:
                final_status = "complete"

            # Past the commit, each step below logs its own failure instead
            # of failing the reupload.
            async with cleanup_step("reupload_file catalog cache", job_id=job_id):
                await invalidate_catalog_cache()
            # fix(#394) B-019/VT-01: the swap replaced the table's contents under the
            # same name — purge cached MVT tiles or they 304-serve stale data for up
            # to tile_cache_ttl. Post-commit, mirroring the feature-edit path.
            async with cleanup_step("reupload_file tile cache", job_id=job_id):
                await invalidate_tile_cache_for_table(live_table_name)

            # 10. Archive the original after the commit, so the upload never
            # runs under the rename's exclusive lock.
            await _archive_after_publication(
                session,
                publication,
                job=job,
                dataset_id=dataset.id,
                file_path=file_path,
                job_id=job_id,
            )

        await _defer_embedding_after_publication(
            PublicationOutcome.PUBLISHED, Dataset, dataset_uuid
        )

    except (
        Exception
    ) as exc:  # broad: reupload pipeline spans GDAL/PostGIS/S3/FS — any step can fail
        # Phase 1/2 sessions are already closed (or rolled back) by the time
        # we get here. Open a fresh session, re-load the job, and run the
        # shared cleanup helper.
        try:
            async with async_session() as err_session:
                # fix(#1950): arms the budget, loads the row, and
                # swallows an expiry — the failure below is the task's outcome.
                err_job = await load_job_for_error_write(
                    err_session, job_uuid, attempt_uuid, task_name="reupload_file"
                )
                if err_job is not None:
                    await _cleanup_staging_on_failure(
                        err_session,
                        staging_table=staging_tn,
                        job=err_job,
                        exc=exc,
                        task_name="reupload_file",
                        attempt_id=attempt_uuid,
                    )
                # feat(#1219): outside the err_job guard on purpose — the run
                # is keyed on the job id, which is known even when the job row
                # itself has gone, and a failure is history too.
                await record_refresh_failure(
                    err_session,
                    ingest_job_id=job_uuid,
                    error_code=_file_refresh_error_code(exc),
                    error_message=exc,
                    contacted_origin=False,
                )
                await err_session.commit()
        finally:
            # fix(#1213): the `finally` reapers gate on THIS
            # variable, so every exit from this handler sets it — the bounded
            # error write above can raise past a positional assignment.
            final_status = "failed"
        raise
    finally:
        async with cleanup_step("reupload_file heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("reupload_file staging table", job_id=job_id):
            await _drop_attempt_staging_table(staging_tn)
        # Clean up local file on success always; on failure only if it was
        # a resolve_file_path download (source of truth is S3).
        async with cleanup_step("reupload_file local file", job_id=job_id):
            if final_status == "complete":
                Path(file_path).unlink(missing_ok=True)
            elif file_path != original_file_path:
                Path(file_path).unlink(missing_ok=True)
        # fix(#1213): reap the object the task downloaded FROM, which
        # after a presigned completion is the frozen copy the job is bound to —
        # the unlinks above are local files only, so it was never deleted and a
        # successful reupload job is its dataset's latest-complete row, exempt
        # from the stale purge forever. No fan-out on this surface, so the
        # sibling-sharing guard is left at its default.
        async with cleanup_step("reupload_file downloaded source", job_id=job_id):
            await reap_downloaded_staging_source(
                job_id,
                original_file_path=original_file_path,
                final_status=final_status,
                # _retry_capability refuses reupload jobs outright, so nothing
                # else will ever reap this; reap on failure too.
                failed_source_replayable=False,
            )
        # fix(#1207): sweep the presigned staging key — this surface had NO
        # storage reaper (the unlinks above are local files only), and the
        # stale purge isn't a backstop since a successful reupload job is
        # the per-dataset latest-complete row it exempts forever.
        async with cleanup_step(
            "reupload_file presigned staging object", job_id=job_id
        ):
            await reap_presigned_staging_object(
                job_id, owned_staging_key, final_status=final_status
            )


async def _record_failed_origin_contact(
    err_session,
    dataset_cls,
    dataset_uuid,
    *,
    contacted: bool,
    bound: tuple | None,
) -> None:
    """Date the contact a failed service reupload made before it died.

    fix(#1271): a failed attempt that reached the outbound fetch
    still CONTACTED the origin (the column's contract is "last time
    GeoLens contacted the origin at all"), so only the timestamp moves —
    the dataset keeps its old data and the health verdict stays with the
    probe's classifier. ``contacted`` is False for failures before the
    fetch began.

    ``bound`` is the (origin_uri, origin_ref, source_format) snapshot taken
    at load time: guards against a concurrent reupload rebinding the origin
    mid-fetch, which would otherwise stamp the OLD origin's contact onto
    the NEW binding. Losing that race is a silent skip — same discipline
    as the source-health probe.
    """
    if not contacted or bound is None:
        return
    bound_uri, bound_ref, bound_format = bound
    outcome = await err_session.execute(
        update(dataset_cls)
        .where(
            dataset_cls.id == dataset_uuid,
            dataset_cls.origin_uri.is_not_distinct_from(bound_uri),
            dataset_cls.origin_ref.is_not_distinct_from(bound_ref),
            dataset_cls.source_format.is_not_distinct_from(bound_format),
        )
        .values(last_checked_at=datetime.now(timezone.utc))
    )
    await err_session.commit()
    # fix(#1271): GET /datasets/ caches last_checked_at for 60s;
    # invalidate only when the guarded write actually landed.
    if outcome.rowcount:
        await invalidate_catalog_cache()


def _file_refresh_error_code(exc: BaseException) -> str:
    """Map a file-reupload failure onto its run ``error_code``.

    A contended catalog row reports as contention: nothing was written, and
    the reader's next step is to find the holder, not to inspect the file.
    """
    if isinstance(exc, CatalogLockConflict):
        return CATALOG_LOCK_CONFLICT_CODE
    return "file_refresh_failed"


async def _resolve_service_token(
    token: str | None, credential_ref: str | None
) -> str | None:
    """The credential this attempt will fetch with, redeeming a ref if given.

    feat(#1220); fix(#1676) moved the body to
    ``platform.refresh.credentials.resolve_worker_credential`` so
    ``ingest_service`` redeems the same way without either task module
    importing the other. Kept as the name this task and its tests reach for.
    """
    return await resolve_worker_credential(token, credential_ref)


async def _fetch_service_layer_with_paging_guard(
    *,
    service_type_raw: str,
    service_type: str,
    source_url: str,
    layer_name: str,
    layer_id,
    token: str | None,
    staging_table: str,
    db_conn_str: str,
    schema: str,
    fallback_order_field: str | None,
    on_spawn,
    verification_policy: str | None = None,
) -> tuple[int | None, object | None]:
    """Fetch a service layer into staging, paging large ArcGIS layers.

    fix(#1675): parity with the initial-import path. A refresh of a large
    ArcGIS layer used to do ONE unpaged fetch and trust GDAL driver paging —
    the exact behavior the import path's guarded loop exists to distrust.
    Same criteria, same shared loop (tasks_common); the page-info fetch
    resolves through tasks_vector's module attribute so test monkeypatches
    cover both doors.
    """
    from app.platform.extensions import get_processing_port
    from app.platform.security import make_safe_client
    from app.processing.ingest import tasks_vector as _tv
    from app.processing.ingest.ogr import run_ogr2ogr_service
    from app.processing.ingest.tasks_common import run_paged_arcgis_service_fetch

    port = get_processing_port()
    page_size = _tv._ARCGIS_SERVICE_IMPORT_CHUNK_SIZE
    feature_count = None
    supports_pagination = False
    pagination_order_field = None
    id_plan = None
    if service_type == "arcgis_featureserver":
        # fix(#1675): the page-info probe is the FIRST outbound
        # contact of a refresh and can fail before any subprocess exists to
        # fire on_spawn, so arm the contact stamp here too (monotonic OR —
        # later per-page spawns re-arming is harmless).
        if on_spawn is not None:
            on_spawn()
        (
            feature_count,
            max_record_count,
            supports_pagination,
            pagination_order_field,
        ) = await _tv._fetch_arcgis_import_page_info(source_url, layer_id, token)
        if max_record_count is not None:
            page_size = max(1, min(page_size, max_record_count))
        if verification_policy == "arcgis_id_set_v1":
            try:
                async with make_safe_client(timeout=30.0) as client:
                    id_plan = await port.fetch_arcgis_id_plan(
                        source_url,
                        layer_id,
                        client,
                        token=token,
                        expected_oid_field=(
                            pagination_order_field or fallback_order_field
                        ),
                    )
            except ValueError as exc:
                from app.processing.ingest.ogr import IngestionError

                raise IngestionError(f"ArcGIS ID plan unavailable: {exc}") from exc
            if id_plan.count:
                await run_paged_arcgis_service_fetch(
                    service_type_raw=service_type_raw,
                    service_type=service_type,
                    source_url=source_url,
                    layer_name=layer_name,
                    layer_id=layer_id,
                    token=token,
                    staging_table=staging_table,
                    db_conn_str=db_conn_str,
                    schema=schema,
                    feature_count=id_plan.count,
                    page_size=page_size,
                    order_field=id_plan.oid_field,
                    on_spawn=on_spawn,
                    planned_ids=id_plan.ids,
                )
                return feature_count, id_plan
    if (
        service_type == "arcgis_featureserver"
        and supports_pagination
        and pagination_order_field is not None
        and feature_count is not None
        and feature_count > page_size
    ):
        await run_paged_arcgis_service_fetch(
            service_type_raw=service_type_raw,
            service_type=service_type,
            source_url=source_url,
            layer_name=layer_name,
            layer_id=layer_id,
            token=token,
            staging_table=staging_table,
            db_conn_str=db_conn_str,
            schema=schema,
            feature_count=feature_count,
            page_size=page_size,
            order_field=pagination_order_field,
            on_spawn=on_spawn,
        )
        return feature_count, id_plan

    gdal_source, layer_arg = port.build_gdal_source(
        service_type_raw,
        source_url,
        layer_name,
        layer_id,
        token=token,
        order_field=fallback_order_field,
    )
    await run_ogr2ogr_service(
        gdal_source,
        layer_arg,
        staging_table,
        db_conn_str,
        service_type,
        token=token,
        schema=schema,
        on_spawn=on_spawn,
    )
    return feature_count, id_plan


async def _arcgis_id_coverage_evidence(
    session,
    *,
    initial_id_plan,
    schema: str,
    table_name: str,
    source_url: str,
    layer_id,
    token: str | None,
) -> dict | None:
    """Return compact pre/post ArcGIS membership evidence for a staged fetch."""
    if initial_id_plan is None:
        return None

    from app.platform.extensions import get_processing_port
    from app.platform.security import make_safe_client
    from app.processing.ingest.tasks_common import verify_arcgis_staged_oid_coverage

    coverage = await verify_arcgis_staged_oid_coverage(
        session,
        schema=schema,
        table_name=table_name,
        oid_field=initial_id_plan.oid_field,
        planned_ids=initial_id_plan.ids,
    )
    try:
        async with make_safe_client(timeout=30.0) as client:
            final_id_plan = await get_processing_port().fetch_arcgis_id_plan(
                source_url,
                layer_id,
                client,
                token=token,
                expected_oid_field=initial_id_plan.oid_field,
            )
    except ValueError:
        coverage["source_membership_status"] = "unavailable"
    else:
        coverage["source_membership_status"] = (
            "matched" if final_id_plan.digest == initial_id_plan.digest else "changed"
        )
        coverage["source_marker_before"] = initial_id_plan.source_marker
        coverage["source_marker_after"] = final_id_plan.source_marker
    return coverage


async def _staged_geometry_contract(
    session, *, schema: str, table: str
) -> tuple[str | None, int | None, int | None]:
    row = (
        await session.execute(
            text(
                "SELECT type, srid, coord_dimension FROM geometry_columns "
                "WHERE f_table_schema = :schema AND f_table_name = :table "
                "AND f_geometry_column = 'geom'"
            ),
            {"schema": schema, "table": table},
        )
    ).one_or_none()
    if row is None:
        return None, None, None
    return row.type, int(row.srid), int(row.coord_dimension)


async def _defer_embedding_after_publication(
    outcome: PublicationOutcome, Dataset, dataset_uuid: uuid.UUID
) -> None:
    """Keep enrichment outside settlement and skip candidates left unpublished."""
    if outcome is not PublicationOutcome.PUBLISHED:
        return

    from app.core.db import async_session
    from sqlalchemy.orm import joinedload

    try:
        async with async_session() as embed_session:
            dataset_result = await embed_session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset_uuid)
            )
            embed_dataset = dataset_result.scalar_one_or_none()
            if embed_dataset is not None:
                from app.processing.embeddings.helpers import defer_embedding

                await defer_embedding(embed_dataset)
    except Exception:  # broad: post-commit enrichment cannot rewrite publication
        structlog.get_logger().warning(
            "reupload_embedding_defer_failed", dataset_id=str(dataset_uuid)
        )


def _matches_service_origin(
    bound: tuple,
    *,
    source_format: str,
    source_url: str,
    layer_id,
    layer_name: str,
) -> bool:
    """Return whether a fetch still describes the dataset's stored source."""
    stored_ref = bound[1] or {}
    return (
        classify_origin(bound[2]) == "service"
        and stored_ref.get("service_type") == source_format
        and stored_ref.get("url") == source_url
        and stored_ref.get("layer_id")
        == service_layer_identity(
            source_format,
            layer_id=layer_id,
            layer_name=layer_name,
        )
    )


def _require_service_source_url(value: str | None) -> str:
    """Return a usable service URL or fail the re-upload job."""
    if not value:
        from app.processing.ingest.ogr import IngestionError

        raise IngestionError("Missing service source URL for re-upload commit job.")
    return value


@task_app.task(
    queue="ingest",
    retry=0,
    # fix(#1746): the context is how the task learns its own queue-row id, so
    # a terminal failure can strip the raw token out of its own kwargs.
    pass_context=True,
    aliases=["app.ingest.tasks.reupload_service"],
)
@tenant_task
@purge_token_on_failure
@require_scheduled_execution_claim
async def reupload_service(
    job_id: str,
    dataset_id: str,
    source_url: str,
    source_layer: str,
    user_id: str,
    attempt_id: str | None = None,
    token: str | None = None,
    credential_ref: str | None = None,
    **kwargs,
) -> None:
    """Background task: replace dataset data from a remote service source.

    Two dispatching doors since feat(#1676) hand a credential the same
    way: ``credential_ref``, a single-use reference redeemed once here for
    a secret that never touched a committed row. ``token`` is the
    surviving durable argument, produced only when no shared credential
    store is configured (state 3 in ``platform/refresh/credentials``).
    Both optional, at most one ever set — the reference wins if both
    somehow are. Neither required: a public service needs no credential.

    Session lifecycle (gh #100 followup): the AsyncSession is split into
    two short-lived blocks so it is NOT held open across
    ``run_ogr2ogr_service`` (can take 30s+) — see ``ingest_service``'s
    docstring for the ``MissingGreenlet`` root cause this avoids.
    """
    _bind_task_log_context(
        task_name="reupload_service", job_id=job_id, dataset_id=dataset_id
    )
    from app.core.db import async_session
    from app.platform.security import (
        SSRFError,
        validate_url_for_ssrf,
    )
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.metadata import (
        _qtable,
        add_4326_column,
        clip_to_mercator_bounds,
        compute_table_content_digest,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
    )
    from app.processing.ingest.ogr import (
        IngestionError,
        build_pg_conn_str,
    )
    from app.platform.jobs.models import IngestJob
    from sqlalchemy import text
    from sqlalchemy.orm import joinedload

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()

    # fix(#1271): tracks whether the outbound fetch was reached, so the
    # failure handler can date the contact. A failure before this point never
    # touched the origin and must not claim it did.
    origin_contact_attempted = False
    reupload_bound: tuple | None = None

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="reupload"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    dataset_uuid = uuid.UUID(dataset_id)
    staging_tn: str = ""
    heartbeat_task: asyncio.Task[None] | None = None
    measured_feature_count: int | None = None
    measured_schema_diff: dict | None = None
    verification_evidence: dict | None = None
    initial_arcgis_id_plan = None
    job_verification_policy = None

    try:
        # IA-P0-03 defense-in-depth: revalidate source_url at fetch time.
        # The route-level check at commit_import covers the preview→commit
        # TOCTOU, but manifest-path reuploads skip that route entirely.
        # fix(#1274): INSIDE the handled region — this task owns a
        # pending run row, and a refusal that skips the failure handler
        # leaves it active, so the admission index refuses every further
        # refresh until the stale sweep. Must fail the job like any other.
        try:
            await validate_url_for_ssrf(source_url)
        except SSRFError as exc:
            raise RuntimeError(
                f"source_url failed safety check at worker fetch time: {exc}"
            ) from exc

        token = await _resolve_service_token(token, credential_ref)
        # Phase 1 (short-lived session): load job + dataset, mark running,
        # snapshot service-import config, drop stale staging table.
        async with async_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                )
            )
            job = job_result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job not found, skipping", job_id=job_id
                )
                return

            dataset_result = await session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset_uuid)
            )
            dataset = dataset_result.scalar_one_or_none()
            if dataset is None:
                structlog.get_logger().warning(
                    "Dataset not found, skipping", dataset_id=dataset_id
                )
                return

            # fix(#1271): binding snapshot for the failure handler —
            # its contact stamp must be conditional on the dataset still
            # having the origin this task actually fetched from.
            reupload_bound = (
                dataset.origin_uri,
                dataset.origin_ref,
                dataset.source_format,
            )

            staging_tn = attempt_scoped_staging_table(dataset.table_name, attempt_uuid)
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid
            )
            if heartbeat_task is None:
                return

            await claim_run_for_job(session, job_uuid)  # feat(#1219)

            um = job.user_metadata or {}
            service_type_raw = um.get("service_type", "")
            layer_id = um.get("layer_id")
            source_url_value = _require_service_source_url(job.source_url or source_url)
            source_layer_value = job.source_layer or source_layer
            source_filename = job.source_filename
            reupload_oid_field = um.get("object_id_field") or None
            # fix(#1746): which door dispatched this run, so the auth-failure
            # copy can name the call the operator actually made. router_refresh
            # writes "refresh" into user_metadata; reupload_commit does not.
            is_refresh = bool(um.get("refresh"))
            job_verification_policy = um.get("verification_policy")
            accepted_refresh_fingerprint = um.get("accepted_refresh_fingerprint")
            accepted_refresh_run_id = um.get("accepted_refresh_run_id")

            service_type, source_format = resolve_service_type(service_type_raw)
            db_conn_str = build_pg_conn_str()

            # Drop stale staging table from prior failed attempt before
            # closing the session — ogr2ogr_service needs a clean target.
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS "
                    f"{_qtable(staging_tn, schema=_current_tenant_schema())} CASCADE"
                )
            )
            await session.commit()

        # Phase 1.5 (no session): run_ogr2ogr_service subprocess with WFS
        # fallback. Holding an AsyncSession across this would corrupt the
        # greenlet bridge state — same root cause as gh #100.

        # fix(#1271): the failure stamp may only describe the STORED
        # origin — a reupload can target a different source — so it arms
        # only when the COMPLETE attempted binding (type, base URL, layer
        # identity) equals the stored one. A successful swap re-stamps via
        # set_dataset_origin regardless.
        attempt_matches_binding = _matches_service_origin(
            reupload_bound,
            source_format=source_format,
            source_url=source_url_value,
            layer_id=layer_id,
            layer_name=source_layer_value,
        )

        def _arm_contact() -> None:
            # fix(#1271): fired by run_ogr2ogr_service the instant the
            # subprocess exists, which is the first moment an outbound
            # attempt truthfully began — every local preflight (argv checks,
            # token sanitization, spawn itself) happens before it. Monotonic
            # OR, so a fallback retry that dies locally cannot erase the
            # contact its first attempt already made.
            nonlocal origin_contact_attempted
            origin_contact_attempted = (
                origin_contact_attempted or attempt_matches_binding
            )

        expected_feature_count: int | None = None
        verification_policy = kwargs.get("verification_policy", job_verification_policy)
        credential_version = kwargs.get("credential_version")

        async def _run_service_import(layer_name: str) -> None:
            nonlocal expected_feature_count, initial_arcgis_id_plan
            (
                expected_feature_count,
                initial_arcgis_id_plan,
            ) = await _fetch_service_layer_with_paging_guard(
                service_type_raw=service_type_raw,
                service_type=service_type,
                source_url=source_url_value,
                layer_name=layer_name,
                layer_id=layer_id,
                token=token,
                staging_table=staging_tn,
                db_conn_str=db_conn_str,
                schema=_current_tenant_schema(),
                fallback_order_field=reupload_oid_field,
                on_spawn=_arm_contact,
                verification_policy=verification_policy,
            )

        try:
            await _run_service_import_with_wfs_fallback(
                _run_service_import,
                source_layer_value,
                token=token,
                # fix(#1746): serves only the refresh endpoint and the
                # re-upload commit (never a first import), so the message
                # names "the refresh" rather than "Retry commit". Literal
                # string, not an f-string, since this reaches
                # record_refresh_failure through redact_run_error.
                #
                # fix(#1746): says "credential"/`auth` object,
                # not "token" — the deprecated field always means a bearer
                # token, which can't authenticate a basic or named-key origin.
                auth_error_message=(
                    "Remote service authentication failed. Retry the refresh "
                    "with the credential in the request body's `auth` object; "
                    "credentials are request-only and are not stored between "
                    "runs."
                    if is_refresh
                    else "Remote service authentication failed. Retry the "
                    "re-upload with the credential in the commit request's "
                    "`auth` object; credentials are request-only and are not "
                    "stored between runs."
                ),
            )
        except ValueError as exc:
            raise IngestionError(str(exc)) from exc

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): re-load job + dataset, run staging
        # post-processing, apply swap, mark complete.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                )
            )
            job = job_result.scalar_one()

            dataset_result = await session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset_uuid)
            )
            dataset = dataset_result.scalar_one()

            # Rename source columns that collide with GeoLens-internal names.
            # Runs BEFORE ensure_geom_column / add_4326_column.
            from app.processing.ingest.metadata import rename_reserved_columns

            _schema = _current_tenant_schema()
            reserved_renames = await rename_reserved_columns(
                session, staging_tn, schema=_schema
            )
            if reserved_renames:
                from app.processing.ingest.warnings import make_reserved_rename_warning

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            has_geom = await ensure_geom_column(session, staging_tn, schema=_schema)
            # fix(#2031 review): the file door's refusal, before the swap DDL —
            # this path learns geometry from the staging table, never from
            # `_detect_reupload_crs`, so a table layer over a vector dataset
            # reached the same record_type re-derivation.
            _assert_geometry_survives(
                record_type=dataset.record.record_type,
                geometry_type=dataset.geometry_type,
                has_geometry=has_geom,
            )
            if has_geom:
                # fix(#888): same clamp accounting as the file-reupload path.
                _append_mercator_clip_warning(
                    job,
                    await clip_to_mercator_bounds(session, staging_tn, schema=_schema),
                )
                await add_4326_column(session, staging_tn, 4326, schema=_schema)
            await grant_reader_access(
                session,
                staging_tn,
                schema=_schema,
                role=_current_tenant_role(),
            )

            metadata = await extract_metadata(session, staging_tn, schema=_schema)
            # Before the samples, schema diff and content digest, so all three
            # describe the table first ingest builds, `elev` included.
            three_d = await _detect_3d_and_promote_elev(
                session, staging_tn, metadata, schema=_schema
            )
            staged_geometry_type, staged_srid, staged_coordinate_dimension = (
                await _staged_geometry_contract(
                    session, schema=_schema, table=staging_tn
                )
                if is_refresh
                else (None, None, None)
            )
            sample_values = await get_sample_values(
                session,
                staging_tn,
                metadata.get("column_info", []),
                schema=_schema,
            )
            content_digest = (
                await compute_table_content_digest(
                    session,
                    staging_tn,
                    schema=_schema,
                    has_geometry=has_geom,
                )
                if is_refresh
                else None
            )

            reupload_source_url = (
                f"{source_url_value}/{layer_id}"
                if layer_id is not None
                else source_url_value
            )
            measurement = await catalog_projection.measure(
                session,
                dataset,
                table=staging_tn,
                schema=_schema,
                staged=StagingResult(
                    metadata=metadata,
                    sample_values=sample_values,
                    three_d=three_d,
                    has_geometry=has_geom,
                    geometry_type=metadata.get("geometry_type"),
                ),
                score=False,
            )
            # Verification compares this fetch, not the preview's: a live
            # service can have changed since the preview was taken.
            schema_diff = catalog_projection.schema_diff(dataset, measurement)
            measured_feature_count = metadata.get("feature_count")
            measured_schema_diff = schema_diff
            source_binding = {
                "service_type": source_format,
                "url": source_url_value,
                "layer_id": service_layer_identity(
                    source_format,
                    layer_id=layer_id,
                    layer_name=source_layer_value,
                ),
                "verification_policy": verification_policy,
                "credential_version": (
                    credential_version if isinstance(credential_version, str) else None
                ),
            }
            source_binding["arcgis_id_coverage"] = await _arcgis_id_coverage_evidence(
                session,
                initial_id_plan=initial_arcgis_id_plan,
                schema=_schema,
                table_name=staging_tn,
                source_url=source_url_value,
                layer_id=layer_id,
                token=token,
            )
            outcome = await settle_publication(
                PublicationSettlementCommand(
                    session=session,
                    dataset=dataset,
                    dataset_id=dataset_uuid,
                    job_id=job_uuid,
                    attempt_id=attempt_uuid,
                    staging_table=staging_tn,
                    measurement=measurement,
                    user_id=user_id,
                    source_filename=source_filename or source_layer_value,
                    source_format=source_format,
                    original_srid=metadata.get("srid"),
                    source_url=reupload_source_url,
                    origin_ref={
                        "service_type": source_binding["service_type"],
                        "url": source_binding["url"],
                        "layer_id": source_binding["layer_id"],
                        "auth_required": True if token else None,
                    },
                    schema_diff=schema_diff,
                    source_binding=source_binding,
                    is_refresh=is_refresh,
                    expected_feature_count=expected_feature_count,
                    content_digest=content_digest,
                    staged_geometry_type=staged_geometry_type,
                    staged_srid=staged_srid,
                    staged_coordinate_dimension=staged_coordinate_dimension,
                    accepted_fingerprint=accepted_refresh_fingerprint,
                    accepted_run_id=accepted_refresh_run_id,
                    origin_binding=reupload_bound,
                    failure_contacted_origin=origin_contact_attempted,
                    credential_for_error_scrubbing=token,
                )
            )
        await _defer_embedding_after_publication(outcome, Dataset, dataset_uuid)

    except (
        Exception
    ) as exc:  # broad: reupload service-path spans GDAL/PostGIS — any step can fail
        # fix(#1277): exact-value scrub, first thing, before `exc` is
        # read by anything — this task is the only place that knows the
        # credential's literal value, covering an echo the pattern matchers
        # (run_ogr2ogr_service, _cleanup_staging_on_failure) wouldn't
        # recognise as a URL. Mutated in place so the class survives for
        # the error-code handlers below and every reader sees the scrub.
        scrub_secret_from_exception(exc, token)
        if isinstance(exc, PublicationSettlementFailure):
            raise
        # Phase 1/2 sessions are already closed by the time we get here.
        async with async_session() as err_session:
            # fix(#1950): arms the budget, loads the row, and
            # swallows an expiry — the failure below is the task's outcome.
            err_job = await load_job_for_error_write(
                err_session, job_uuid, attempt_uuid, task_name="reupload_service"
            )
            if err_job is not None:
                await _cleanup_staging_on_failure(
                    err_session,
                    staging_table=staging_tn,
                    job=err_job,
                    exc=exc,
                    task_name="reupload_service",
                    attempt_id=attempt_uuid,
                )
            # Two records, one writer each (#1219 x #1222 merge):
            # _record_failed_origin_contact owns the dataset-side contact
            # stamp, record_refresh_failure owns the run row.
            # contacted_origin=False below so the run finalizer doesn't
            # repeat the dataset write a second, weaker way.
            await _record_failed_origin_contact(
                err_session,
                Dataset,
                dataset_uuid,
                contacted=origin_contact_attempted,
                bound=reupload_bound,
            )
            # feat(#1219): last_refreshed_at is untouched by construction,
            # so a failed refresh leaves the live table's freshness exactly
            # as it was (invariant 10).
            #
            # feat(#1220): the two credential failures get their own error
            # codes rather than collapsing into service_refresh_failed
            # (which would send the reader to investigate a working
            # service) — expired means retry with a fresh token, unreachable
            # store means an operator config split-brain.
            await record_refresh_failure(
                err_session,
                ingest_job_id=job_uuid,
                error_code=_service_refresh_error_code(exc),
                error_message=exc,
                contacted_origin=False,
                feature_count_after=measured_feature_count,
                schema_diff=measured_schema_diff,
                verification=verification_evidence,
            )
            await err_session.commit()
        raise
    finally:
        # fix(#1755): `purge_token_on_failure` (`tasks_common.py`), the
        # decorator around this task, must still see whatever exception
        # `reupload_service` itself raised, not one from a cleanup step.
        async with cleanup_step("reupload_service heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("reupload_service staging table", job_id=job_id):
            await _drop_attempt_staging_table(staging_tn)


# Verified refreshes use a task name introduced with the publication protocol;
# pre-change workers therefore cannot run them through the ordinary reupload door.
reupload_verified_refresh = task_app.task(
    reupload_service.func,
    queue="ingest",
    retry=0,
    name="app.ingest.tasks.reupload_verified_refresh",
    pass_context=True,
)
