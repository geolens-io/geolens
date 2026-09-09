"""Procrastinate task definitions for file and service re-upload workflows."""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select, update

from app.core.db.tenant_session import tenant_task
from app.core.failure_reason import redact_failure_reason
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
from app.platform.refresh.credentials import (
    CredentialExpiredError,
    CredentialStoreUnavailable,
    resolve_worker_credential,
)
from app.platform.refresh.service import (
    claim_run_for_job,
    record_refresh_failure,
    record_refresh_success,
)
from app.processing.ingest.source_format import derive_source_format
from app.processing.ingest.tasks_common import (
    _append_job_warning,
    cleanup_step,
    _append_mercator_clip_warning,
    _apply_reupload_swap,
    _archive_original_file,
    _bind_task_log_context,
    _cleanup_staging_on_failure,
    load_job_for_error_write,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
    _current_tenant_role,
    _current_tenant_schema,
    _run_service_import_with_wfs_fallback,
    _run_staging_pipeline,
    _validate_upload_file_safety,
    apply_manifest_record_metadata,
    invalidate_tile_cache_for_table,
    purge_token_on_failure,
    resolve_service_type,
    task_app,
)


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


async def _detect_reupload_crs(
    file_path: str,
    layer_name: str | None,
    user_metadata: dict,
    *,
    original_filename: str | None = None,
) -> tuple[dict, int]:
    """Detect CRS/geometry for a reupload file and resolve the effective SRID.

    GPKG-01 Phase 1058: ``layer_name`` targets the user-chosen layer in a
    multi-layer GPKG rather than defaulting to ``layers[0]``.

    fix(#541): applies the same missing-CRS gate as ``ingest_file``,
    raising ``IngestionError`` rather than silently falling through to the
    4326 default and corrupting the replacement dataset.

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

    effective_srid = (
        srid_override
        if srid_override is not None
        else (srid if srid is not None else 4326)
    )
    return info, effective_srid


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
            file_path, layer_name, user_metadata, original_filename=source_filename
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
            metadata = staging_result.metadata
            sample_values = staging_result.sample_values
            three_d = staging_result.three_d

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
            # feat(#1223): measured HERE, against the staging table, and
            # deliberately not carried forward from the preview. The preview
            # can be minutes old and, for a service, describes a fetch that is
            # not the one about to be installed. Both inputs are still the
            # pre-swap values at this point — `_apply_reupload_swap` overwrites
            # them — so the order of these two calls is load-bearing.
            schema_diff = port.compute_schema_diff(
                dataset.column_info or [],
                metadata.get("column_info") or [],
                dataset.feature_count,
                metadata.get("feature_count"),
            )
            version = await _apply_reupload_swap(
                session,
                dataset=dataset,
                staging_table=staging_tn,
                metadata=metadata,
                sample_values=sample_values,
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
            apply_manifest_record_metadata(dataset.record, user_metadata)

            # Captured pre-commit: the ORM attribute may be expired after commit.
            live_table_name = dataset.table_name

            # Persist 3D fields on dataset record
            dataset.is_3d = three_d.get("is_3d")
            dataset.n_dims = three_d.get("n_dims")
            dataset.z_min = three_d.get("z_min")
            dataset.z_max = three_d.get("z_max")

            # 9. Archive original file to storage provider.
            # Best-effort: failure does NOT fail the reupload (data is already
            # in PostGIS). Suppress the helper's inline commit so the
            # archive_failed flag rides along with the status=complete commit
            # below, avoiding a second round trip (CLEANUP-4).
            await _archive_original_file(
                session,
                job=job,
                dataset_id=dataset.id,
                file_path=file_path,
                log_message="Failed to archive re-uploaded file to storage",
                commit=False,
            )

            # 10. Update job status to complete
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
                feature_count_after=metadata.get("feature_count"),
                schema_diff=schema_diff,
                contacted_origin=False,
            )
            await session.commit()

        final_status = "complete"
        await invalidate_catalog_cache()
        # fix(#394) B-019/VT-01: the swap replaced the table's contents under the
        # same name — purge cached MVT tiles or they 304-serve stale data for up
        # to tile_cache_ttl. Post-commit, mirroring the feature-edit path.
        await invalidate_tile_cache_for_table(live_table_name)

        # Generate embedding (non-fatal). Use a fresh session to load the
        # dataset since both phase 1 and phase 2 sessions are now closed.
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


def _service_refresh_error_code(exc: BaseException) -> str:
    """Map a service-refresh failure onto its run ``error_code``.

    Four codes, because they send the reader to four different places: the
    holder of a contended catalog row, a fresh token, an operator for an
    unreachable credential store, or the origin. ``error_code`` is a closed
    vocabulary the history UI reads, so the mapping lives in one function.
    """
    if isinstance(exc, CatalogLockConflict):
        return CATALOG_LOCK_CONFLICT_CODE
    if isinstance(exc, CredentialExpiredError):
        return "credential_expired"
    if isinstance(exc, CredentialStoreUnavailable):
        return "credential_store_unavailable"
    return "service_refresh_failed"


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
) -> None:
    """Fetch a service layer into staging, paging large ArcGIS layers.

    fix(#1675): parity with the initial-import path. A refresh of a large
    ArcGIS layer used to do ONE unpaged fetch and trust GDAL driver paging —
    the exact behavior the import path's guarded loop exists to distrust.
    Same criteria, same shared loop (tasks_common); the page-info fetch
    resolves through tasks_vector's module attribute so test monkeypatches
    cover both doors.
    """
    from app.platform.extensions import get_processing_port
    from app.processing.ingest import tasks_vector as _tv
    from app.processing.ingest.ogr import run_ogr2ogr_service
    from app.processing.ingest.tasks_common import run_paged_arcgis_service_fetch

    page_size = _tv._ARCGIS_SERVICE_IMPORT_CHUNK_SIZE
    feature_count = None
    supports_pagination = False
    pagination_order_field = None
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
        return

    gdal_source, layer_arg = get_processing_port().build_gdal_source(
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
            source_url_value = job.source_url or source_url
            source_layer_value = job.source_layer or source_layer
            source_filename = job.source_filename
            reupload_oid_field = um.get("object_id_field") or None
            # fix(#1746): which door dispatched this run, so the auth-failure
            # copy can name the call the operator actually made. router_refresh
            # writes "refresh" into user_metadata; reupload_commit does not.
            is_refresh = bool(um.get("refresh"))

            if not source_url_value:
                raise IngestionError(
                    "Missing service source URL for re-upload commit job."
                )

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
        _stored_ref = reupload_bound[1] or {}
        attempt_matches_binding = (
            classify_origin(reupload_bound[2]) == "service"
            and _stored_ref.get("service_type") == source_format
            and _stored_ref.get("url") == source_url_value
            and _stored_ref.get("layer_id")
            == service_layer_identity(
                source_format, layer_id=layer_id, layer_name=source_layer_value
            )
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

        async def _run_service_import(layer_name: str) -> None:
            await _fetch_service_layer_with_paging_guard(
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
            sample_values = await get_sample_values(
                session,
                staging_tn,
                metadata.get("column_info", []),
                schema=_schema,
            )

            reupload_source_url = (
                f"{source_url_value}/{layer_id}"
                if layer_id is not None
                else source_url_value
            )
            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={"heartbeat_at": datetime.now(timezone.utc)},
            )
            # feat(#1223): see the file path — measured against the staging
            # table before the swap overwrites the pre-swap columns. It matters
            # more here: a live service can have changed since the preview, so
            # the previewed diff describes a fetch that is not this one.
            schema_diff = port.compute_schema_diff(
                dataset.column_info or [],
                metadata.get("column_info") or [],
                dataset.feature_count,
                metadata.get("feature_count"),
            )
            version = await _apply_reupload_swap(
                session,
                dataset=dataset,
                staging_table=staging_tn,
                metadata=metadata,
                sample_values=sample_values,
                user_id=user_id,
                source_filename=source_filename or source_layer_value,
                source_format=source_format,
                original_srid=metadata.get("srid"),
                source_url=reupload_source_url,
                # fix(#1218): base URL and layer_id (the
                # SERVICE-NATIVE identifier) stay separate, same as first
                # ingest — see the matching comment in
                # tasks_vector.ingest_service for why build_gdal_source
                # makes them mutually exclusive per service type.
                origin_ref={
                    "service_type": source_format,
                    "url": source_url_value,
                    "layer_id": service_layer_identity(
                        source_format,
                        layer_id=layer_id,
                        layer_name=source_layer_value,
                    ),
                    # fix(#1746): means "made WITH a token", not "origin
                    # demanded one" — see tasks_vector.ingest_service.
                    # Written on the SUCCESS path only: a failed attempt
                    # tells you nothing new, and a token-less success
                    # un-marks a service that went public.
                    "auth_required": True if token else None,
                },
            )
            # Captured pre-commit: the ORM attribute may be expired after commit.
            live_table_name = dataset.table_name

            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={
                    "status": "complete",
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            # feat(#1219, #1223): contacted_origin=True here — this path DID
            # reach the remote service, which is exactly what last_checked_at
            # records. source_health stays untouched on every path: the health
            # vocabulary and its classifier belong to the probe work (#1222),
            # and a second classifier here would be the weaker of the two.
            await record_refresh_success(
                session,
                ingest_job_id=job_uuid,
                dataset=dataset,
                dataset_version_id=version.id,
                feature_count_after=metadata.get("feature_count"),
                schema_diff=schema_diff,
                contacted_origin=True,
            )
            await session.commit()

        await invalidate_catalog_cache()
        # fix(#394) B-019/VT-01: purge cached MVT tiles after the swap (see the
        # file-reupload path above).
        await invalidate_tile_cache_for_table(live_table_name)

        # Generate embedding (non-fatal). Fresh session — both phase 1 and
        # phase 2 sessions are closed by now.
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
