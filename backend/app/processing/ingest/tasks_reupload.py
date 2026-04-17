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


@task_app.task(queue="ingest", retry=1, aliases=["app.ingest.tasks.reupload_file"])
async def reupload_file(
    job_id: str, dataset_id: str, file_path: str, user_id: str, **kwargs
) -> None:
    """Background task: replace dataset data via staging table swap."""
    _bind_task_log_context(
        task_name="reupload_file", job_id=job_id, dataset_id=dataset_id
    )
    import asyncio

    from app.core.db import async_session
    from app.modules.catalog.datasets.domain.models import Dataset
    from app.processing.ingest.metadata import _qtable
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo
    from app.platform.jobs.models import IngestJob
    from sqlalchemy import select, text
    from sqlalchemy.orm import joinedload

    async with async_session() as session:
        # Load job and dataset records — separate variable names so mypy
        # tracks each query's row type independently.
        job_result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = job_result.scalar_one()

        dataset_result = await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == uuid.UUID(dataset_id))
        )
        dataset = dataset_result.scalar_one()

        staging_tn = f"{dataset.table_name[:54]}_staging"

        try:
            # 1. Update job to running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # Resolve S3 key to local file for ogr2ogr
            from app.processing.ingest.service import resolve_file_path

            original_file_path = file_path
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
                return

            # 2. Detect CRS from new file
            info = await run_ogrinfo(file_path)
            srid = info.get("srid")
            geometry_type = info.get("geometry_type")
            has_geometry = geometry_type is not None

            # 3. Check for srid_override from user metadata
            um = job.user_metadata or {}
            srid_override = um.get("srid_override")
            effective_srid = (
                srid_override
                if srid_override is not None
                else (srid if srid is not None else 4326)
            )

            # 4. Load into staging table (drop stale staging table first)
            db_conn_str = build_pg_conn_str()
            await session.execute(
                text(f"DROP TABLE IF EXISTS {_qtable(staging_tn)} CASCADE")
            )
            await session.commit()
            await run_ogr2ogr(
                file_path,
                staging_tn,
                db_conn_str,
                source_srid=srid,
                geometry_type=geometry_type,
            )

            # 4a. Rename any source column that collides with a GeoLens-internal
            #     name. Runs BEFORE post-process steps (ensure_geom_column /
            #     add_4326_column) so they cannot clash with source attributes.
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(session, staging_tn)
            if reserved_renames:
                from app.processing.ingest.warnings import make_reserved_rename_warning

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            # 4b. Shapefile-only: detect DBF 10-char truncation collisions.
            if file_path.lower().endswith(".zip"):
                import structlog
                from app.processing.ingest.metadata import detect_dbf_truncation_collisions
                from app.processing.ingest.ogr import run_ogrinfo_preview
                from app.processing.ingest.warnings import make_dbf_truncation_warning

                preview_cols = info.get("columns") or []
                if not preview_cols:
                    preview_info = await run_ogrinfo_preview(file_path, sample_limit=0)
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

            # 7. Compute file hash + source format
            file_hash = await asyncio.to_thread(sha256_file, file_path)
            suffix = Path(file_path).suffix.lower().lstrip(".")
            source_format = "shapefile" if suffix == "zip" else suffix

            # 8. Apply shared reupload swap/version invariants
            await _apply_reupload_swap(
                session,
                dataset=dataset,
                staging_table=staging_tn,
                metadata=metadata,
                sample_values=sample_values,
                user_id=user_id,
                source_filename=job.source_filename,
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
            # in PostGIS). We suppress the helper's inline commit so the
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

            await invalidate_catalog_cache()

            # Generate embedding (non-fatal)
            from app.processing.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

        except Exception as exc:
            await _cleanup_staging_on_failure(
                session,
                staging_table=staging_tn,
                job=job,
                exc=exc,
                task_name="reupload_file",
            )
            raise
        finally:
            # Clean up local file on success always; on failure only if it was
            # a resolve_file_path download (source of truth is S3).
            if job.status == "complete":
                Path(file_path).unlink(missing_ok=True)
            elif file_path != original_file_path:
                Path(file_path).unlink(missing_ok=True)


@task_app.task(queue="ingest", retry=1, aliases=["app.ingest.tasks.reupload_service"])
async def reupload_service(
    job_id: str,
    dataset_id: str,
    source_url: str,
    source_layer: str,
    user_id: str,
    token: str | None = None,
    **kwargs,
) -> None:
    """Background task: replace dataset data from a remote service source."""
    _bind_task_log_context(
        task_name="reupload_service", job_id=job_id, dataset_id=dataset_id
    )
    from app.core.db import async_session
    from app.modules.catalog.datasets.domain.models import Dataset
    from app.processing.ingest.metadata import (
        _qtable,
        add_4326_column,
        clip_to_mercator_bounds,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
    )
    from app.processing.ingest.ogr import IngestionError, build_pg_conn_str, run_ogr2ogr_service
    from app.platform.jobs.models import IngestJob
    from app.modules.catalog.sources.preview import build_gdal_source
    from sqlalchemy import select, text
    from sqlalchemy.orm import joinedload

    auth_error_message = (
        "Remote service authentication failed. Retry commit with a service token; "
        "tokens are request-only and are not persisted for retries."
    )

    async with async_session() as session:
        job_result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = job_result.scalar_one()

        dataset_result = await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == uuid.UUID(dataset_id))
        )
        dataset = dataset_result.scalar_one()

        staging_tn = f"{dataset.table_name[:54]}_staging"

        try:
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            um = job.user_metadata or {}
            service_type_raw = um.get("service_type", "")
            layer_id = um.get("layer_id")
            source_url_value = job.source_url or source_url
            source_layer_value = job.source_layer or source_layer

            if not source_url_value:
                raise IngestionError(
                    "Missing service source URL for re-upload commit job."
                )

            service_type, source_format = resolve_service_type(service_type_raw)

            db_conn_str = build_pg_conn_str()
            reupload_oid_field = um.get("object_id_field") or None

            # Drop stale staging table from prior failed attempt
            await session.execute(
                text(f"DROP TABLE IF EXISTS {_qtable(staging_tn)} CASCADE")
            )
            await session.commit()

            async def _run_service_import(layer_name: str) -> None:
                gdal_source, layer_arg = build_gdal_source(
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

            # Rename any source column that collides with a GeoLens-internal name.
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
                source_filename=job.source_filename or source_layer_value,
                source_format=source_format,
                original_srid=metadata.get("srid"),
                source_url=reupload_source_url,
            )

            job.status = "complete"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

            await invalidate_catalog_cache()

            # Generate embedding (non-fatal)
            from app.processing.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

        except Exception as exc:
            await _cleanup_staging_on_failure(
                session,
                staging_table=staging_tn,
                job=job,
                exc=exc,
                task_name="reupload_service",
            )
            raise
