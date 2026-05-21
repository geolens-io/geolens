"""Procrastinate task definitions for file and service re-upload workflows."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select

from app.platform.cache.tiles import invalidate_catalog_cache
from app.processing.raster.cog import sha256_file

from app.processing.ingest.tasks_common import (
    _append_job_warning,
    _apply_reupload_swap,
    _archive_original_file,
    _bind_task_log_context,
    _cleanup_staging_on_failure,
    _run_service_import_with_wfs_fallback,
    _run_staging_pipeline,
    _validate_upload_file_safety,
    resolve_service_type,
    task_app,
)


@task_app.task(queue="ingest", retry=0, aliases=["app.ingest.tasks.reupload_file"])
async def reupload_file(
    job_id: str, dataset_id: str, file_path: str, user_id: str, **kwargs
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
    import asyncio

    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.metadata import _qtable
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo
    from app.platform.jobs.models import IngestJob
    from sqlalchemy import text
    from sqlalchemy.orm import joinedload

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()

    job_uuid = uuid.UUID(job_id)
    dataset_uuid = uuid.UUID(dataset_id)
    original_file_path = file_path
    final_status: str = "pending"
    staging_tn: str = ""

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session): load job + dataset, mark running,
        # resolve, validate, drop stale staging table. Snapshot the values
        # needed for the long async work into local variables.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
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

            staging_tn = f"{dataset.table_name[:54]}_staging"

            # 1. Update job to running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
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
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(timezone.utc)
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
                text(f"DROP TABLE IF EXISTS {_qtable(staging_tn)} CASCADE")
            )
            await session.commit()

        # ----------------------------------------------------------------- #
        # Phase 1.5 (no session): ogrinfo, ogr2ogr subprocess, sha256.
        # Holding an AsyncSession across these would corrupt the greenlet
        # bridge state — same root cause as gh #100.
        # ----------------------------------------------------------------- #

        # 2. Detect CRS from new file
        # GPKG-01 Phase 1058: pass layer_name so ogrinfo targets the user-chosen
        # layer in multi-layer GPKG files rather than defaulting to layers[0].
        info = await run_ogrinfo(file_path, layer_name=layer_name)
        srid = info.get("srid")
        geometry_type = info.get("geometry_type")
        has_geometry = geometry_type is not None

        # 3. Check for srid_override from user metadata
        srid_override = user_metadata.get("srid_override")
        effective_srid = (
            srid_override
            if srid_override is not None
            else (srid if srid is not None else 4326)
        )

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
        )

        # 7. Compute file hash (moved up — must be outside any session)
        file_hash = await asyncio.to_thread(sha256_file, file_path)
        suffix = Path(file_path).suffix.lower().lstrip(".")
        source_format = "shapefile" if suffix == "zip" else suffix

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): re-load job + dataset, run staging
        # pipeline, apply swap, archive, mark complete.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
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

            reserved_renames = await rename_reserved_columns(session, staging_tn)
            if reserved_renames:
                from app.processing.ingest.warnings import make_reserved_rename_warning

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            # 4b. Shapefile-only: detect DBF 10-char truncation collisions.
            if file_path.lower().endswith(".zip"):
                from app.processing.ingest.metadata import (
                    detect_dbf_truncation_collisions,
                )
                from app.processing.ingest.ogr import run_ogrinfo_preview
                from app.processing.ingest.warnings import make_dbf_truncation_warning

                preview_cols = info.get("columns") or []
                if not preview_cols:
                    # GPKG-01 Phase 1058: pass layer_name for multi-layer shapefiles (rare)
                    preview_info = await run_ogrinfo_preview(file_path, sample_limit=0, layer_name=layer_name)
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

            # 8. Apply shared reupload swap/version invariants
            await _apply_reupload_swap(
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
            )

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
            job.status = "complete"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

        final_status = "complete"
        await invalidate_catalog_cache()

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
        async with async_session() as err_session:
            err_job_result = await err_session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
            )
            err_job = err_job_result.scalar_one_or_none()
            if err_job is not None:
                await _cleanup_staging_on_failure(
                    err_session,
                    staging_table=staging_tn,
                    job=err_job,
                    exc=exc,
                    task_name="reupload_file",
                )
        raise
    finally:
        # Clean up local file on success always; on failure only if it was
        # a resolve_file_path download (source of truth is S3).
        if final_status == "complete":
            Path(file_path).unlink(missing_ok=True)
        elif file_path != original_file_path:
            Path(file_path).unlink(missing_ok=True)


@task_app.task(queue="ingest", retry=0, aliases=["app.ingest.tasks.reupload_service"])
async def reupload_service(
    job_id: str,
    dataset_id: str,
    source_url: str,
    source_layer: str,
    user_id: str,
    token: str | None = None,
    **kwargs,
) -> None:
    """Background task: replace dataset data from a remote service source.

    Session lifecycle (gh #100 followup): the AsyncSession is split into two
    short-lived blocks so it is NOT held open across ``run_ogr2ogr_service``
    (an asyncio subprocess that can take 30s+ for large remote layers).
    Holding a session across that subprocess in
    Python 3.14 + SQLAlchemy 2.0 + greenlet 3.3 corrupts the greenlet bridge
    state and the next ``session.execute()`` raises ``MissingGreenlet``
    (same root cause as gh #100 in ``ingest_service`` / ``reupload_file``).
    """
    _bind_task_log_context(
        task_name="reupload_service", job_id=job_id, dataset_id=dataset_id
    )
    from app.core.db import async_session
    from app.modules.catalog.sources.security import (
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
        run_ogr2ogr_service,
    )
    from app.platform.jobs.models import IngestJob
    from sqlalchemy import text
    from sqlalchemy.orm import joinedload

    # IA-P0-03 defense-in-depth: revalidate source_url at fetch time.
    # The route-level check at commit_import covers the preview→commit
    # TOCTOU, but manifest-path reuploads skip that route entirely.
    try:
        await validate_url_for_ssrf(source_url)
    except SSRFError as exc:
        raise RuntimeError(
            f"source_url failed safety check at worker fetch time: {exc}"
        ) from exc

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()

    auth_error_message = (
        "Remote service authentication failed. Retry commit with a service token; "
        "tokens are request-only and are not persisted for retries."
    )

    job_uuid = uuid.UUID(job_id)
    dataset_uuid = uuid.UUID(dataset_id)
    staging_tn: str = ""

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session): load job + dataset, mark running,
        # snapshot service-import config, drop stale staging table.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
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

            staging_tn = f"{dataset.table_name[:54]}_staging"

            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            um = job.user_metadata or {}
            service_type_raw = um.get("service_type", "")
            layer_id = um.get("layer_id")
            source_url_value = job.source_url or source_url
            source_layer_value = job.source_layer or source_layer
            source_filename = job.source_filename
            reupload_oid_field = um.get("object_id_field") or None

            if not source_url_value:
                raise IngestionError(
                    "Missing service source URL for re-upload commit job."
                )

            service_type, source_format = resolve_service_type(service_type_raw)
            db_conn_str = build_pg_conn_str()

            # Drop stale staging table from prior failed attempt before
            # closing the session — ogr2ogr_service needs a clean target.
            await session.execute(
                text(f"DROP TABLE IF EXISTS {_qtable(staging_tn)} CASCADE")
            )
            await session.commit()

        # ----------------------------------------------------------------- #
        # Phase 1.5 (no session): run_ogr2ogr_service subprocess with WFS
        # fallback. Holding an AsyncSession across this would corrupt the
        # greenlet bridge state — same root cause as gh #100.
        # ----------------------------------------------------------------- #

        async def _run_service_import(layer_name: str) -> None:
            gdal_source, layer_arg = port.build_gdal_source(
                service_type_raw,
                source_url_value,
                layer_name,
                layer_id,
                token=token,
                order_field=reupload_oid_field,
            )
            await run_ogr2ogr_service(
                gdal_source,
                layer_arg,
                staging_tn,
                db_conn_str,
                service_type,
                token=token,
            )

        try:
            await _run_service_import_with_wfs_fallback(
                _run_service_import,
                source_layer_value,
                token=token,
                auth_error_message=auth_error_message,
            )
        except ValueError as exc:
            raise IngestionError(str(exc)) from exc

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): re-load job + dataset, run staging
        # post-processing, apply swap, mark complete.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
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

            reserved_renames = await rename_reserved_columns(session, staging_tn)
            if reserved_renames:
                from app.processing.ingest.warnings import make_reserved_rename_warning

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            has_geom = await ensure_geom_column(session, staging_tn)
            if has_geom:
                await clip_to_mercator_bounds(session, staging_tn)
                await add_4326_column(session, staging_tn, 4326)
            await grant_reader_access(session, staging_tn)

            metadata = await extract_metadata(session, staging_tn)
            sample_values = await get_sample_values(
                session,
                staging_tn,
                metadata.get("column_info", []),
            )

            reupload_source_url = (
                f"{source_url_value}/{layer_id}"
                if layer_id is not None
                else source_url_value
            )
            await _apply_reupload_swap(
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
            )

            job.status = "complete"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

        await invalidate_catalog_cache()

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
        # Phase 1/2 sessions are already closed by the time we get here.
        async with async_session() as err_session:
            err_job_result = await err_session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
            )
            err_job = err_job_result.scalar_one_or_none()
            if err_job is not None:
                await _cleanup_staging_on_failure(
                    err_session,
                    staging_table=staging_tn,
                    job=err_job,
                    exc=exc,
                    task_name="reupload_service",
                )
        raise
