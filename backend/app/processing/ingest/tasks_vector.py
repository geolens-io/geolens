"""Procrastinate task definitions for vector file and service ingestion."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog

from sqlalchemy import select

from app.processing.ingest.tasks_common import (
    IngestContext,
    _append_job_warning,
    _archive_original_file,
    _bind_task_log_context,
    _detect_and_override_geometry,
    _finalize_ingest,
    _resolve_effective_srid,
    _run_service_import_with_wfs_fallback,
    _validate_upload_file_safety,
    resolve_service_type,
    task_app,
)


@task_app.task(queue="ingest", retry=0, aliases=["app.ingest.tasks.ingest_file"])
async def ingest_file(job_id: str, file_path: str, user_id: str, **kwargs) -> None:
    """Background task: run ogr2ogr, extract metadata, register dataset.

    Full pipeline:
    1. Update job status to running
    2. Run ogrinfo to detect CRS
    3. Run ogr2ogr to load file into PostGIS
    4. Add geom_4326 column via ST_Transform
    5. Grant geolens_reader SELECT access
    6. Extract metadata (extent, columns, row count, geometry type)
    7. Create Dataset record in catalog
    8. Update job status to complete
    9. Clean up staging file
    """
    _bind_task_log_context(task_name="ingest_file", job_id=job_id)
    from app.core.db import async_session
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo
    from app.processing.ingest.service import generate_table_name
    from app.platform.jobs.models import IngestJob

    async with async_session() as session:
        # Load job record
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one_or_none()
        if job is None:
            structlog.get_logger().warning("Ingest job not found, skipping", job_id=job_id)
            return

        try:
            # 1. Update job to running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # Resolve S3 key to local file for ogr2ogr
            from app.processing.ingest.service import resolve_file_path

            original_file_path = file_path
            file_path = await resolve_file_path(file_path, job_id)

            # Validate file content and safety before ogr2ogr (KISS-3).
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
                # N2: do NOT unlink here. The finally block keeps local
                # uploads around for retry and only cleans up S3-downloaded
                # copies (source of truth is S3). Deleting validation
                # failures inline contradicted that retry-preserving contract.
                return

            # Check for user-supplied metadata from commit step
            um = job.user_metadata or {}
            srid_override = um.get("srid_override")
            layer_name = um.get("layer_name")

            # 2. Detect CRS via ogrinfo
            info = await run_ogrinfo(file_path, layer_name=layer_name)
            srid = info.get("srid")
            geometry_type = info.get("geometry_type")
            has_geometry = geometry_type is not None

            # Check for missing CRS (CSV and GeoJSON default to EPSG:4326)
            # Non-spatial files don't need CRS at all
            lower_path = file_path.lower()
            assumes_4326 = any(
                lower_path.endswith(ext)
                for ext in (".csv", ".geojson", ".json", ".xlsx", ".xls")
            )
            if (
                has_geometry
                and srid is None
                and not assumes_4326
                and srid_override is None
            ):
                job.status = "failed"
                job.error_message = (
                    "Missing CRS: no coordinate system detected. "
                    "Ensure the file includes CRS information "
                    "(e.g., .prj file for Shapefiles)."
                )
                job.completed_at = datetime.now(timezone.utc)
                await session.commit()
                return

            # 3. Generate table name and run ogr2ogr
            dataset_name = um.get("title") or job.source_filename or "dataset"
            table_name, collision_warning = await generate_table_name(
                dataset_name, session
            )
            if collision_warning:
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "collision_warning": collision_warning,
                }
            db_conn_str = build_pg_conn_str()

            # Check for user-specified geometry columns (override)
            # Lowercase column names: ogr2ogr lowercases them in PostGIS.
            # CLEANUP-2: the individual column locals are re-derived inside
            # ``_detect_and_override_geometry`` from ``um``, so we only need
            # the boolean here to gate the import-as-non-spatial branch.
            user_wants_geom = bool(
                ((um.get("x_column") or "") and (um.get("y_column") or ""))
                or (um.get("geom_column") or "")
            )

            # When user specifies geometry columns, import as non-spatial
            # then construct geometry post-import. This ensures the override
            # works even for CSVs where GDAL would auto-detect geometry.
            ogr_geometry_type = None if user_wants_geom else geometry_type
            await run_ogr2ogr(
                file_path,
                table_name,
                db_conn_str,
                source_srid=srid,
                geometry_type=ogr_geometry_type,
                layer_name=layer_name,
            )

            # 3a. Rename any source column that collides with a GeoLens-internal
            #     name (gid, geom, geometry, geom_4326, fid, ogc_fid). Runs BEFORE
            #     the user-geometry-override and _finalize_ingest steps so that
            #     construct_point_geometry / add_4326_column cannot clash with a
            #     source attribute of the same name.
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(session, table_name)
            if reserved_renames:
                from app.processing.ingest.warnings import make_reserved_rename_warning

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            # 3b. Shapefile-only: detect DBF 10-char truncation collisions using
            #     the source column list from ogrinfo (stored in info["columns"]).
            if file_path.lower().endswith(".zip"):
                from app.processing.ingest.metadata import detect_dbf_truncation_collisions
                from app.processing.ingest.ogr import run_ogrinfo_preview
                from app.processing.ingest.warnings import make_dbf_truncation_warning

                preview_cols = info.get("columns") or []
                if not preview_cols:
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
                        table=table_name,
                        collisions=dbf_collisions,
                    )

            if user_wants_geom:
                override_geom_type = await _detect_and_override_geometry(
                    session,
                    table_name=table_name,
                    user_metadata=um,
                )
                if override_geom_type is not None:
                    has_geometry = True
                    geometry_type = override_geom_type

            # Use srid_override if provided
            effective_srid = _resolve_effective_srid(
                detected_srid=srid,
                srid_override=srid_override,
            )

            # 4. Determine source format from file extension
            suffix = Path(file_path).suffix.lower()
            # Strip leading dot for format name; handle .zip -> look inside filename
            source_format = suffix.lstrip(".")
            if source_format == "zip":
                source_format = "shapefile"

            # 5-9. Shared post-ogr2ogr pipeline
            dataset = await _finalize_ingest(
                IngestContext(
                    session=session,
                    job=job,
                    table_name=table_name,
                    user_id=user_id,
                    has_geometry=has_geometry,
                    effective_srid=effective_srid,
                    source_format=source_format,
                    source_filename=job.source_filename,
                    original_srid=srid,
                    user_metadata=um,
                )
            )

            # 9c. Archive original file to storage provider (R-2).
            await _archive_original_file(
                session,
                job=job,
                dataset_id=dataset.id,
                file_path=file_path,
            )

        except Exception as exc:
            # On any failure, mark job as failed
            await session.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            structlog.get_logger().exception(
                "Ingest task failed",
                job_id=str(job.id),
                task="ingest_file",
            )
            await session.commit()
            raise
        finally:
            # Clean up local file on success always; on failure only if it was
            # a resolve_file_path download (source of truth is S3, not the
            # local copy). Local-only uploads are kept for retry.
            if job.status == "complete":
                Path(file_path).unlink(missing_ok=True)
            elif file_path != original_file_path:
                # Downloaded from S3 for processing -- safe to clean up
                Path(file_path).unlink(missing_ok=True)


@task_app.task(queue="ingest", retry=0, aliases=["app.ingest.tasks.ingest_service"])
async def ingest_service(
    job_id: str,
    source_url: str,
    source_layer: str,
    user_id: str,
    token: str | None = None,
    **kwargs,
) -> None:
    """Background task: import a remote service layer via ogr2ogr.

    Full pipeline:
    1. Update job status to running
    2. Determine service type from job metadata
    3. Build GDAL source string and run ogr2ogr
    4. Post-process (clip, geom_4326, grants, metadata, samples)
    5. Create Dataset record with source_format and source_url
    6. Compute quality score
    7. Update job status to complete
    """
    _bind_task_log_context(task_name="ingest_service", job_id=job_id)
    from app.core.db import async_session
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr_service
    from app.processing.ingest.service import generate_table_name
    from app.platform.jobs.models import IngestJob
    from app.modules.catalog.sources.preview import build_gdal_source

    async with async_session() as session:
        # Load job record
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one_or_none()
        if job is None:
            structlog.get_logger().warning("Ingest job not found, skipping", job_id=job_id)
            return

        try:
            # 1. Update job to running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # 2. Determine service type from job metadata
            um = job.user_metadata or {}
            service_type_raw = um.get("service_type", "")
            layer_id = um.get("layer_id")
            service_type, source_format = resolve_service_type(service_type_raw)

            # Detect non-spatial tables from preview metadata stored at job creation.
            # When geometry_type is None/null/absent, the layer has no geometry —
            # skip geometry-specific ogr2ogr flags to preserve attribute columns.
            _preview_geom_type = um.get("geometry_type")
            is_non_spatial = _preview_geom_type is None

            # 3. Resolve service parameters
            object_id_field = um.get("object_id_field") or None

            # 4. Generate table name and run ogr2ogr
            dataset_name = um.get("title") or job.source_filename or "dataset"
            table_name, collision_warning = await generate_table_name(
                dataset_name, session
            )
            if collision_warning:
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "collision_warning": collision_warning,
                }
            db_conn_str = build_pg_conn_str()

            # WFS namespace retry via shared helper (KISS-8).
            async def _do_import(layer_name: str) -> None:
                _src, _layer = build_gdal_source(
                    service_type_raw,
                    source_url,
                    layer_name,
                    layer_id,
                    token=token,
                    order_field=object_id_field,
                )
                await run_ogr2ogr_service(
                    _src,
                    _layer,
                    table_name,
                    db_conn_str,
                    service_type,
                    token=token,
                    is_non_spatial=is_non_spatial,
                )

            await _run_service_import_with_wfs_fallback(
                _do_import, source_layer, token=token
            )

            # 4a. Rename any source column that collides with a GeoLens-internal
            #     name. Runs BEFORE _finalize_ingest (which calls add_4326_column).
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(session, table_name)
            if reserved_renames:
                from app.processing.ingest.warnings import make_reserved_rename_warning

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            # 5-8. Shared post-ogr2ogr pipeline
            dataset_source_url = (
                f"{source_url}/{layer_id}" if layer_id is not None else source_url
            )
            await _finalize_ingest(
                IngestContext(
                    session=session,
                    job=job,
                    table_name=table_name,
                    user_id=user_id,
                    has_geometry=False if is_non_spatial else None,
                    effective_srid=None if is_non_spatial else 4326,
                    source_format=source_format,
                    source_filename=job.source_filename,
                    original_srid=None,
                    user_metadata=um,
                    source_url=dataset_source_url,
                )
            )

        except Exception as exc:
            # On any failure, mark job as failed (no staging file to clean up)
            await session.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            structlog.get_logger().exception(
                "Ingest task failed",
                job_id=str(job.id),
                task="ingest_service",
            )
            await session.commit()
            raise
