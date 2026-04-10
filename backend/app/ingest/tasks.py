"""Procrastinate task definitions for async file ingestion."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from procrastinate import App, PsycopgConnector
from sqlalchemy import select

from app.cache.tiles import invalidate_catalog_cache
from app.config import settings
from app.database import async_session
from app.embeddings.helpers import defer_embedding
from app.raster.cog import check_and_prepare_cog, extract_raster_metadata, sha256_file
from app.raster.quicklook import generate_quicklook
from app.raster.vrt import build_vrt, resolve_vrt_source_path
from app.storage import get_storage

_connector_kwargs: dict = {"min_size": 1, "max_size": 3}
if settings.db_use_external_pooler:
    _connector_kwargs["kwargs"] = {"prepare_threshold": None}

task_app = App(
    connector=PsycopgConnector(
        conninfo=settings.procrastinate_conninfo,
        **_connector_kwargs,
    ),
    import_paths=["app.ingest.tasks", "app.embeddings.tasks", "app.raster.cog"],
)

# ArcGIS esriFieldType → column_info type mapping
_ARCGIS_TYPE_MAP = {
    "esriFieldTypeString": "text",
    "esriFieldTypeSmallInteger": "integer",
    "esriFieldTypeInteger": "integer",
    "esriFieldTypeSingle": "real",
    "esriFieldTypeDouble": "double precision",
    "esriFieldTypeDate": "timestamp without time zone",
    "esriFieldTypeOID": "integer",
    "esriFieldTypeGlobalID": "text",
    "esriFieldTypeGUID": "text",
    "esriFieldTypeBlob": "text",
    "esriFieldTypeXML": "text",
}


def _arcgis_type_to_column_type(esri_type: str) -> str:
    """Map an ArcGIS esriFieldType string to a PostgreSQL column type name."""
    return _ARCGIS_TYPE_MAP.get(esri_type, "text")


async def _finalize_ingest(
    *,
    session,
    job,
    table_name: str,
    user_id: str,
    has_geometry: bool | None,
    effective_srid: int,
    source_format: str,
    source_filename: str | None,
    original_srid: int | None,
    user_metadata: dict,
    source_url: str | None = None,
):
    """Shared post-ogr2ogr pipeline for both file and service ingestion.

    Steps:
    - Normalize geometry column, clip to valid bounds, add 4326 column
    - Grant reader access
    - Extract column info and sample values
    - Create dataset record
    - Compute quality score
    - Commit job + dataset atomically
    - Generate quicklook thumbnail (non-fatal)
    - Invalidate caches and backfill embedding

    Args:
        session: Active async DB session.
        job: IngestJob ORM instance (will be mutated).
        table_name: Target PostGIS table in data schema.
        user_id: UUID string of the uploading user.
        has_geometry: Whether geometry is expected. If None, auto-detect
            via ensure_geom_column.
        effective_srid: SRID for the ST_Transform to 4326.
        source_format: E.g. "shapefile", "geojson", "wfs".
        source_filename: Original filename from the upload.
        original_srid: Detected SRID from the source, or None.
        user_metadata: Dict with optional title, summary, visibility.
        source_url: Optional source URL for service ingests.

    Returns:
        The created Dataset ORM instance.
    """
    from app.datasets.service import create_dataset
    from app.ingest.metadata import (
        add_4326_column,
        clip_to_mercator_bounds,
        compute_quality_score,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
    )

    # Normalize geometry column name to 'geom'
    if has_geometry is None:
        has_geometry = await ensure_geom_column(session, table_name)
    elif has_geometry:
        await ensure_geom_column(session, table_name)

    # Clip geometries to Web Mercator bounds and add 4326 column
    if has_geometry:
        await clip_to_mercator_bounds(session, table_name)
        await add_4326_column(session, table_name, effective_srid)

    # Grant reader access
    await grant_reader_access(session, table_name)

    # Extract metadata
    metadata = await extract_metadata(session, table_name)

    # ArcGIS column_info fallback: if the DB-based extraction returned empty
    # column_info (e.g., non-spatial table where ogr2ogr only created a gid column),
    # fall back to the ArcGIS fields captured at preview time and stored in user_metadata.
    if not metadata.get("column_info") and user_metadata.get("source_columns"):
        source_columns = user_metadata["source_columns"]
        metadata["column_info"] = [
            {
                "name": col["name"],
                "type": _arcgis_type_to_column_type(col.get("type", "string")),
                "ordinal_position": idx + 1,
                "is_nullable": True,
            }
            for idx, col in enumerate(source_columns)
            if col.get("name")  # skip columns without a name
        ]

    # Extract sample values for attribute search
    sample_values = await get_sample_values(
        session, table_name, metadata.get("column_info", [])
    )

    # Create Dataset record
    dataset_name = user_metadata.get("title") or source_filename or table_name
    create_kwargs: dict = dict(
        table_name=table_name,
        title=dataset_name,
        created_by=uuid.UUID(user_id),
        summary=user_metadata.get("summary"),
        srid=metadata.get("srid"),
        geometry_type=metadata.get("geometry_type"),
        feature_count=metadata.get("feature_count"),
        extent_wkt=metadata.get("extent_wkt"),
        column_info=metadata.get("column_info"),
        sample_values=sample_values,
        source_format=source_format,
        source_filename=source_filename,
        original_srid=original_srid
        if original_srid is not None
        else metadata.get("srid"),
        visibility=user_metadata.get("visibility", "private"),
    )
    if source_url is not None:
        create_kwargs["source_url"] = source_url
    dataset = await create_dataset(session, **create_kwargs)

    # Compute quality score (requires Dataset to exist for metadata checks)
    quality_score = await compute_quality_score(
        session, table_name, metadata.get("column_info", []), dataset
    )
    dataset.quality_detail = quality_score

    # Update job to complete and commit dataset + job atomically
    job.status = "complete"
    job.dataset_id = dataset.id
    job.completed_at = datetime.now(timezone.utc)
    await session.commit()

    # Generate vector quicklook thumbnail (non-fatal, after commit)
    # Runs after commit so a connection-killing query (OOM, timeout on
    # complex geometry) cannot roll back the dataset.
    if has_geometry:
        try:
            import io as _io

            from app.vector.quicklook import (
                generate_vector_quicklook_with_timeout as generate_vector_quicklook,
            )

            ql_bytes = await generate_vector_quicklook(
                session, table_name, metadata.get("geometry_type", ""), 256
            )
            ql_storage = get_storage()
            ql_key = f"vectors/{dataset.id}/quicklook_256.png"
            await ql_storage.put(ql_key, _io.BytesIO(ql_bytes))
            dataset.quicklook_256_uri = ql_key
            await session.commit()
        except Exception as _ql_exc:
            await session.rollback()
            import structlog as _sl

            _sl.get_logger().warning(
                "quicklook_failed", table=table_name, error=str(_ql_exc)
            )

    # Invalidate caches after successful ingest
    await invalidate_catalog_cache()

    # Generate embedding (non-fatal)
    from app.embeddings.helpers import defer_embedding

    await defer_embedding(dataset)

    return dataset


@task_app.task(queue="ingest", retry=2)
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
    from app.database import async_session
    from app.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo
    from app.ingest.service import generate_table_name
    from app.jobs.models import IngestJob

    async with async_session() as session:
        # Load job record
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one()

        try:
            # 1. Update job to running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # Resolve S3 key to local file for ogr2ogr
            from app.ingest.service import resolve_file_path

            original_file_path = file_path
            file_path = await resolve_file_path(file_path, job_id)

            # Validate file content and safety before ogr2ogr
            from app.ingest.validation import (
                validate_file_content,
                validate_file_size,
                validate_zip_safety,
            )

            from app.persistent_config import UPLOAD_MAX_SIZE_MB

            max_size_mb = await UPLOAD_MAX_SIZE_MB.get(session)

            try:
                validate_file_content(file_path, job.source_filename)
                validate_file_size(file_path, max_size_mb * 1024 * 1024)
                if file_path.lower().endswith(".zip"):
                    validate_zip_safety(file_path)
            except ValueError as exc:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(timezone.utc)
                await session.commit()
                Path(file_path).unlink(missing_ok=True)
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
            assumes_4326 = (
                lower_path.endswith(".csv")
                or lower_path.endswith(".geojson")
                or lower_path.endswith(".json")
                or lower_path.endswith(".xlsx")
                or lower_path.endswith(".xls")
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
            # Lowercase column names: ogr2ogr lowercases them in PostGIS
            x_column = (um.get("x_column") or "").lower() or None
            y_column = (um.get("y_column") or "").lower() or None
            geom_column = (um.get("geom_column") or "").lower() or None
            user_wants_geom = (x_column and y_column) or geom_column

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
            from app.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(
                session, table_name, known_source_columns=info.get("columns")
            )
            if reserved_renames:
                warnings_list = list(
                    (job.user_metadata or {}).get("warnings", [])
                )
                warnings_list.append(
                    {"kind": "reserved_rename", "details": reserved_renames}
                )
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "warnings": warnings_list,
                }

            # 3b. Shapefile-only: detect DBF 10-char truncation collisions using
            #     the source column list from ogrinfo (stored in info["columns"]).
            if file_path.lower().endswith(".zip"):
                from app.ingest.metadata import detect_dbf_truncation_collisions
                from app.ingest.ogr import run_ogrinfo_preview as _run_preview

                import structlog as _sl

                preview_cols = (info.get("columns") or [])
                if not preview_cols:
                    preview_info = await _run_preview(
                        file_path, sample_limit=0, layer_name=layer_name
                    )
                    preview_cols = preview_info.get("columns") or []
                dbf_collisions = detect_dbf_truncation_collisions(preview_cols)
                if dbf_collisions:
                    warnings_list = list(
                        (job.user_metadata or {}).get("warnings", [])
                    )
                    warnings_list.append(
                        {"kind": "dbf_truncation_collision", "details": dbf_collisions}
                    )
                    job.user_metadata = {
                        **(job.user_metadata or {}),
                        "warnings": warnings_list,
                    }
                    _sl.stdlib.get_logger(__name__).warning(
                        "Shapefile DBF 10-char truncation collision detected",
                        table=table_name,
                        collisions=dbf_collisions,
                    )

            if user_wants_geom and x_column and y_column:
                from app.ingest.metadata import construct_point_geometry

                await construct_point_geometry(session, table_name, x_column, y_column)
                has_geometry = True
                geometry_type = "Point"
            elif user_wants_geom and geom_column:
                from app.ingest.metadata import construct_wkt_geometry

                await construct_wkt_geometry(session, table_name, geom_column)
                has_geometry = True
                # Re-detect geometry type from constructed column
                from sqlalchemy import text as _text

                _result = await session.execute(
                    _text(
                        f"SELECT GeometryType(geom) FROM data.{table_name} WHERE geom IS NOT NULL LIMIT 1"
                    )
                )
                geometry_type = _result.scalar_one_or_none() or "Geometry"

            # Use srid_override if provided
            effective_srid = (
                srid_override
                if srid_override is not None
                else (srid if srid is not None else 4326)
            )

            # 4. Determine source format from file extension
            suffix = Path(file_path).suffix.lower()
            # Strip leading dot for format name; handle .zip -> look inside filename
            source_format = suffix.lstrip(".")
            if source_format == "zip":
                source_format = "shapefile"

            # 5-9. Shared post-ogr2ogr pipeline
            dataset = await _finalize_ingest(
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

            # 9c. Archive original file to storage provider
            archive_key = f"originals/{dataset.id}/{Path(file_path).name}"
            try:
                storage = get_storage()
                with open(file_path, "rb") as fobj:
                    await storage.put(archive_key, fobj)
            except Exception as archive_exc:
                import structlog

                _log = structlog.get_logger()
                _log.warning(
                    "Failed to archive original file to storage",
                    archive_key=archive_key,
                    error=str(archive_exc),
                )

        except Exception as exc:
            # On any failure, mark job as failed
            await session.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
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


def _resolve_service_type(raw: str) -> tuple[str, str]:
    """Map raw service_type string to (service_type, source_format)."""
    from app.ingest.ogr import IngestionError

    if raw.startswith("ArcGIS"):
        return "arcgis_featureserver", "arcgis_featureserver"
    elif raw.startswith("WFS"):
        return "wfs", "wfs"
    raise IngestionError(
        f"Unrecognized service type '{raw}'. "
        f"Expected a type starting with 'ArcGIS' or 'WFS'."
    )


def _enrich_source_url(base_url: str, layer_id: int | str | None) -> str:
    """Append layer_id to source_url for multi-layer service idempotency."""
    if layer_id is not None:
        return f"{base_url}/{layer_id}"
    return base_url


@task_app.task(queue="ingest", retry=2)
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
    from app.database import async_session
    from app.ingest.ogr import IngestionError, build_pg_conn_str, run_ogr2ogr_service
    from app.ingest.service import generate_table_name
    from app.jobs.models import IngestJob
    from app.services.preview import build_gdal_source

    async with async_session() as session:
        # Load job record
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one()

        try:
            # 1. Update job to running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # 2. Determine service type from job metadata
            um = job.user_metadata or {}
            service_type_raw = um.get("service_type", "")
            layer_id = um.get("layer_id")
            service_type, source_format = _resolve_service_type(service_type_raw)

            # Detect non-spatial tables from preview metadata stored at job creation.
            # When geometry_type is None/null/absent, the layer has no geometry —
            # skip geometry-specific ogr2ogr flags to preserve attribute columns.
            _preview_geom_type = um.get("geometry_type")
            is_non_spatial = _preview_geom_type is None

            # 3. Build GDAL source string
            object_id_field = um.get("object_id_field") or None
            gdal_source, layer_arg = build_gdal_source(
                service_type_raw,
                source_url,
                source_layer,
                layer_id,
                token=token,
                order_field=object_id_field,
            )

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

            # WFS namespace retry: if layer name has a colon prefix, retry with unqualified name
            try:
                await run_ogr2ogr_service(
                    gdal_source,
                    layer_arg,
                    table_name,
                    db_conn_str,
                    service_type,
                    token=token,
                    is_non_spatial=is_non_spatial,
                )
            except IngestionError:
                if ":" in source_layer:
                    unqualified = source_layer.split(":", 1)[1]
                    gdal_source_retry, layer_arg_retry = build_gdal_source(
                        service_type_raw,
                        source_url,
                        unqualified,
                        layer_id,
                        token=token,
                        order_field=object_id_field,
                    )
                    await run_ogr2ogr_service(
                        gdal_source_retry,
                        layer_arg_retry,
                        table_name,
                        db_conn_str,
                        service_type,
                        token=token,
                        is_non_spatial=is_non_spatial,
                    )
                else:
                    raise

            # 4a. Rename any source column that collides with a GeoLens-internal
            #     name. Runs BEFORE _finalize_ingest (which calls add_4326_column).
            from app.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(session, table_name)
            if reserved_renames:
                warnings_list = list(
                    (job.user_metadata or {}).get("warnings", [])
                )
                warnings_list.append(
                    {"kind": "reserved_rename", "details": reserved_renames}
                )
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "warnings": warnings_list,
                }

            # 5-8. Shared post-ogr2ogr pipeline
            dataset_source_url = _enrich_source_url(source_url, layer_id)
            await _finalize_ingest(
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

        except Exception as exc:
            # On any failure, mark job as failed (no staging file to clean up)
            await session.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            raise


def _looks_like_auth_error(error_message: str) -> bool:
    """Best-effort detection for remote auth failures from GDAL stderr."""
    lowered = error_message.lower()
    markers = (
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "authentication",
        "access denied",
        "invalid token",
        "token required",
    )
    return any(marker in lowered for marker in markers)


async def _apply_reupload_swap(
    session,
    *,
    dataset,
    staging_table: str,
    metadata: dict,
    sample_values: dict,
    user_id: str,
    source_filename: str | None,
    source_format: str | None,
    original_srid: int | None,
    source_url: str | None = None,
    file_hash: str | None = None,
) -> None:
    """Apply shared atomic swap + version invariants for all reupload sources."""
    from app.audit.service import log_action
    from app.collections.models import DatasetVersion
    from app.ingest.metadata import compute_quality_score, refresh_attribute_metadata
    from sqlalchemy import func, text

    actor_id = uuid.UUID(user_id)
    new_version = dataset.current_version + 1
    table_name = dataset.table_name

    await session.execute(text("SET LOCAL lock_timeout = '5s'"))

    # Check if live table exists (handle edge case where it was dropped)
    live_exists_result = await session.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='data' AND table_name=:tn)"
        ),
        {"tn": table_name},
    )
    live_exists = live_exists_result.scalar()

    from app.ingest.metadata import _qtable

    if live_exists:
        await session.execute(
            text(f'ALTER TABLE {_qtable(table_name)} RENAME TO "{table_name}_old"')
        )
    await session.execute(
        text(f'ALTER TABLE {_qtable(staging_table)} RENAME TO "{table_name}"')
    )
    if live_exists:
        await session.execute(
            text(f"DROP TABLE IF EXISTS {_qtable(table_name + '_old')}")
        )

    # Update dataset metadata in the same transaction as swap
    dataset.srid = metadata["srid"]
    dataset.geometry_type = metadata["geometry_type"]
    dataset.feature_count = metadata["feature_count"]
    if metadata["extent_wkt"] is not None:
        dataset.record.spatial_extent = func.ST_GeomFromText(
            metadata["extent_wkt"], 4326
        )
    dataset.column_info = metadata["column_info"]
    dataset.sample_values = sample_values

    await refresh_attribute_metadata(
        session,
        dataset.id,
        metadata["column_info"],
        geometry_type=metadata.get("geometry_type"),
        sample_values=sample_values,
    )

    dataset.source_format = source_format
    dataset.source_filename = source_filename
    dataset.original_srid = original_srid
    dataset.current_version = new_version
    dataset.record.updated_by = actor_id
    if source_url is not None:
        dataset.source_url = source_url

    quality_score = await compute_quality_score(
        session, dataset.table_name, metadata["column_info"], dataset
    )
    dataset.quality_detail = quality_score

    session.add(
        DatasetVersion(
            dataset_id=dataset.id,
            version_number=new_version,
            source_filename=source_filename,
            source_format=source_format,
            feature_count=metadata["feature_count"],
            srid=metadata["srid"],
            geometry_type=metadata["geometry_type"],
            file_hash=file_hash,
            uploaded_by=actor_id,
        )
    )
    await log_action(
        session,
        user_id=actor_id,
        action="reupload.commit",
        resource_type="dataset",
        resource_id=dataset.id,
        details={
            "version_number": new_version,
            "source_type": "service_url" if source_url else "file",
            "source_format": source_format,
            "source_filename": source_filename,
        },
    )


async def _post_reupload_success() -> None:
    """Run shared post-commit cache invalidation."""
    await invalidate_catalog_cache()


@task_app.task(queue="ingest", retry=1)
async def reupload_file(
    job_id: str, dataset_id: str, file_path: str, user_id: str, **kwargs
) -> None:
    """Background task: replace dataset data via staging table swap."""
    import asyncio

    from app.database import async_session
    from app.datasets.models import Dataset
    from app.ingest.metadata import (
        _qtable,
        add_4326_column,
        clip_to_mercator_bounds,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
    )
    from app.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo
    from app.jobs.models import IngestJob
    from sqlalchemy import select, text
    from sqlalchemy.orm import joinedload

    async with async_session() as session:
        # Load job and dataset records
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one()

        result = await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == uuid.UUID(dataset_id))
        )
        dataset = result.scalar_one()

        staging_tn = f"{dataset.table_name[:54]}_staging"

        try:
            # 1. Update job to running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # Resolve S3 key to local file for ogr2ogr
            from app.ingest.service import resolve_file_path

            original_file_path = file_path
            file_path = await resolve_file_path(file_path, job_id)

            # Validate file content and safety before ogr2ogr
            from app.ingest.validation import (
                validate_file_content,
                validate_file_size,
                validate_zip_safety,
            )
            from app.persistent_config import UPLOAD_MAX_SIZE_MB

            max_size_mb = await UPLOAD_MAX_SIZE_MB.get(session)

            try:
                validate_file_content(file_path, job.source_filename)
                validate_file_size(file_path, max_size_mb * 1024 * 1024)
                if file_path.lower().endswith(".zip"):
                    validate_zip_safety(file_path)
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
            from app.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(
                session, staging_tn, known_source_columns=info.get("columns")
            )
            if reserved_renames:
                warnings_list = list(
                    (job.user_metadata or {}).get("warnings", [])
                )
                warnings_list.append(
                    {"kind": "reserved_rename", "details": reserved_renames}
                )
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "warnings": warnings_list,
                }

            # 4b. Shapefile-only: detect DBF 10-char truncation collisions.
            if file_path.lower().endswith(".zip"):
                from app.ingest.metadata import detect_dbf_truncation_collisions
                from app.ingest.ogr import run_ogrinfo_preview as _run_preview_ru

                import structlog as _sl_ru

                preview_cols = info.get("columns") or []
                if not preview_cols:
                    preview_info = await _run_preview_ru(file_path, sample_limit=0)
                    preview_cols = preview_info.get("columns") or []
                dbf_collisions = detect_dbf_truncation_collisions(preview_cols)
                if dbf_collisions:
                    warnings_list = list(
                        (job.user_metadata or {}).get("warnings", [])
                    )
                    warnings_list.append(
                        {"kind": "dbf_truncation_collision", "details": dbf_collisions}
                    )
                    job.user_metadata = {
                        **(job.user_metadata or {}),
                        "warnings": warnings_list,
                    }
                    _sl_ru.stdlib.get_logger(__name__).warning(
                        "Shapefile DBF 10-char truncation collision detected",
                        table=staging_tn,
                        collisions=dbf_collisions,
                    )

            # 5. Post-process staging table
            if has_geometry:
                await ensure_geom_column(session, staging_tn)
                await clip_to_mercator_bounds(session, staging_tn)
                await add_4326_column(session, staging_tn, effective_srid)
            await grant_reader_access(session, staging_tn)

            # 6. Extract metadata from staging table
            metadata = await extract_metadata(session, staging_tn)
            sample_values = await get_sample_values(
                session, staging_tn, metadata["column_info"]
            )

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

            # 9. Archive original file to storage provider
            archive_key = f"originals/{dataset.id}/{Path(file_path).name}"
            try:
                from app.storage import get_storage

                storage = get_storage()
                with open(file_path, "rb") as fobj:
                    await storage.put(archive_key, fobj)
            except Exception as archive_exc:
                # Archival failure is non-fatal -- data is already in PostGIS
                import structlog

                _log = structlog.get_logger()
                _log.warning(
                    "Failed to archive re-uploaded file to storage",
                    archive_key=archive_key,
                    error=str(archive_exc),
                )

            # 10. Update job status to complete
            job.status = "complete"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

            await _post_reupload_success()

            # Generate embedding (non-fatal)
            from app.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

        except Exception as exc:
            # Clean up staging table on failure
            await session.rollback()
            try:
                await session.execute(
                    text(f"DROP TABLE IF EXISTS {_qtable(staging_tn)}")
                )
                await session.commit()
            except Exception:
                pass

            # Mark job as failed
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            raise
        finally:
            # Clean up local file on success always; on failure only if it was
            # a resolve_file_path download (source of truth is S3).
            if job.status == "complete":
                Path(file_path).unlink(missing_ok=True)
            elif file_path != original_file_path:
                Path(file_path).unlink(missing_ok=True)


@task_app.task(queue="ingest", retry=1)
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
    from app.database import async_session
    from app.datasets.models import Dataset
    from app.ingest.metadata import (
        _qtable,
        add_4326_column,
        clip_to_mercator_bounds,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
    )
    from app.ingest.ogr import IngestionError, build_pg_conn_str, run_ogr2ogr_service
    from app.jobs.models import IngestJob
    from app.services.preview import build_gdal_source
    from sqlalchemy import select, text
    from sqlalchemy.orm import joinedload

    auth_error_message = (
        "Remote service authentication failed. Retry commit with a service token; "
        "tokens are request-only and are not persisted for retries."
    )

    async with async_session() as session:
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one()

        result = await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == uuid.UUID(dataset_id))
        )
        dataset = result.scalar_one()

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

            service_type, source_format = _resolve_service_type(service_type_raw)

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
                await _run_service_import(source_layer_value)
            except IngestionError as exc:
                if ":" in source_layer_value:
                    unqualified = source_layer_value.split(":", 1)[1]
                    try:
                        await _run_service_import(unqualified)
                    except IngestionError as retry_exc:
                        if token is None and _looks_like_auth_error(str(retry_exc)):
                            raise IngestionError(auth_error_message) from retry_exc
                        raise
                elif token is None and _looks_like_auth_error(str(exc)):
                    raise IngestionError(auth_error_message) from exc
                else:
                    raise
            except ValueError as exc:
                raise IngestionError(str(exc)) from exc

            # Rename any source column that collides with a GeoLens-internal name.
            # Runs BEFORE ensure_geom_column / add_4326_column.
            from app.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(session, staging_tn)
            if reserved_renames:
                warnings_list = list(
                    (job.user_metadata or {}).get("warnings", [])
                )
                warnings_list.append(
                    {"kind": "reserved_rename", "details": reserved_renames}
                )
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "warnings": warnings_list,
                }

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

            reupload_source_url = _enrich_source_url(source_url_value, layer_id)
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

            await _post_reupload_success()

            # Generate embedding (non-fatal)
            from app.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

        except Exception as exc:
            await session.rollback()
            try:
                await session.execute(
                    text(f"DROP TABLE IF EXISTS {_qtable(staging_tn)}")
                )
                await session.commit()
            except Exception:
                pass

            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            raise


async def create_raster_dataset(
    session,
    *,
    meta: dict,
    source_sha256: str,
    asset_sha256: str,
    cog_status: str,
    cog_size: int,
    source_filename: str | None,
    created_by: uuid.UUID,
    title: str,
    summary: str | None,
    visibility: str,
) -> tuple:
    """Create Record + Dataset + RasterAsset records for a raster ingest.

    Returns (record, dataset, raster_asset).
    """
    from sqlalchemy import func

    from app.datasets.models import Dataset, Record
    from app.raster.models import RasterAsset

    # Mirror the vector ingest path (datasets/service.py
    # `create_dataset_record`) which commits directly to `published`.
    # Without this the raster stayed in `draft` and the anonymous public
    # tile-access check at tiles/router.py `_resolve_raster_access`
    # returned 404 for every raster tile fetch, so every public demo map
    # containing a raster layer (Earth as Seen from Space, Global
    # Bathymetry, …) was broken for anonymous users.
    record = Record(
        title=title,
        summary=summary,
        record_type="raster_dataset",
        visibility=visibility,
        record_status="published",
        updated_by=created_by,
    )
    if meta.get("bbox_wkt"):
        record.spatial_extent = func.ST_GeomFromText(meta["bbox_wkt"], 4326)
    session.add(record)
    await session.flush()

    table_name = f"raster_{record.id.hex[:16]}"
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format="geotiff",
        source_filename=source_filename,
        srid=meta.get("epsg"),
    )
    session.add(dataset)
    await session.flush()

    nodata_val = meta.get("nodata")
    nodata_str = str(nodata_val) if nodata_val is not None else None

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri="",  # updated after storage put
        sha256=asset_sha256,
        size_bytes=cog_size,
        driver=meta.get("driver"),
        storage_backend="local",
        ingested_at=datetime.now(timezone.utc),
        crs_wkt=meta.get("crs_wkt"),
        epsg=meta.get("epsg"),
        band_count=meta.get("band_count"),
        dtype=meta.get("dtype"),
        nodata=nodata_str,
        res_x=meta.get("res_x"),
        res_y=meta.get("res_y"),
        width=meta.get("width"),
        height=meta.get("height"),
        compression=meta.get("compression"),
        source_sha256=source_sha256,
        cog_status=cog_status,
        band_info=meta.get("band_info"),
        is_rotated=meta.get("is_rotated", False),
    )
    session.add(raster_asset)
    await session.flush()

    return record, dataset, raster_asset


async def create_vrt_dataset(
    session,
    *,
    meta: dict,
    asset_sha256: str,
    vrt_size: int,
    source_filename: str | None,
    created_by: uuid.UUID,
    title: str,
    summary: str | None,
    visibility: str,
    vrt_type: str,
    resolution_strategy: str,
    source_dataset_ids: list[uuid.UUID],
) -> tuple:
    """Create Record + Dataset + RasterAsset records for a VRT dataset.

    Similar to create_raster_dataset but:
    - record_type="vrt_dataset"
    - source_format=None (avoids chk_datasets_source_format constraint)
    - Sets vrt_type and resolution_strategy on RasterAsset
    - Inserts vrt_source_links rows with position ordering

    Returns (record, dataset, raster_asset).
    """
    from sqlalchemy import func, text

    from app.datasets.models import Dataset, Record
    from app.raster.models import RasterAsset

    record = Record(
        title=title,
        summary=summary,
        record_type="vrt_dataset",
        visibility=visibility,
        updated_by=created_by,
    )
    if meta.get("bbox_wkt"):
        record.spatial_extent = func.ST_GeomFromText(meta["bbox_wkt"], 4326)
    session.add(record)
    await session.flush()

    table_name = f"vrt_{record.id.hex[:16]}"
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format=None,  # VRT datasets have no source_format (avoids chk constraint)
        source_filename=source_filename,
        srid=meta.get("epsg"),
    )
    session.add(dataset)
    await session.flush()

    nodata_val = meta.get("nodata")
    nodata_str = str(nodata_val) if nodata_val is not None else None

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri="",  # updated after storage put
        sha256=asset_sha256,
        size_bytes=vrt_size,
        driver="VRT",
        storage_backend="local",
        ingested_at=datetime.now(timezone.utc),
        crs_wkt=meta.get("crs_wkt"),
        epsg=meta.get("epsg"),
        band_count=meta.get("band_count"),
        dtype=meta.get("dtype"),
        nodata=nodata_str,
        res_x=meta.get("res_x"),
        res_y=meta.get("res_y"),
        width=meta.get("width"),
        height=meta.get("height"),
        compression=meta.get("compression"),
        is_rotated=meta.get("is_rotated", False),
        vrt_type=vrt_type,
        resolution_strategy=resolution_strategy,
        status="ready",
    )
    session.add(raster_asset)
    await session.flush()

    # Insert vrt_source_links with position ordering
    for idx, src_id in enumerate(source_dataset_ids):
        await session.execute(
            text("""
                INSERT INTO catalog.vrt_source_links (vrt_dataset_id, source_dataset_id, position)
                VALUES (:vrt_id, :src_id, :pos)
            """),
            {"vrt_id": str(dataset.id), "src_id": str(src_id), "pos": idx},
        )

    return record, dataset, raster_asset


@task_app.task(queue="raster", retry=2)
async def ingest_raster(job_id: str, file_path: str, user_id: str, **kwargs) -> None:
    """Background task: validate GeoTIFF, convert to COG, extract metadata, register dataset.

    Full pipeline:
    1. Update job status to running
    2. Resolve file path
    3. Validate file content and size
    4. Hash source file (source_sha256)
    5. Extract raster metadata
    6. Check/convert to COG profile
    7. Hash COG file (asset_sha256)
    8. Generate quicklooks (256, 512)
    9. Create Dataset + RasterAsset + Record in DB
    10. Store COG and quicklooks to managed storage
    11. Update asset URIs and create distribution record
    12. Update job to complete
    13. Invalidate cache, defer embedding
    """
    import asyncio
    import io
    import os
    import shutil
    import tempfile
    from pathlib import Path as _Path

    # Register all FK target models so SQLAlchemy can resolve FKs on IngestJob
    from app.auth.models import User  # noqa: F401
    from app.datasets.models import Dataset  # noqa: F401

    from app.jobs.models import IngestJob

    async with async_session() as session:
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one()

        local_cog_path: str | None = None
        tmp_dir: str | None = None
        original_file_path = file_path

        try:
            # 1. Mark running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # 2. Resolve file path
            from app.ingest.service import resolve_file_path

            file_path = await resolve_file_path(file_path, job_id)

            # 3. Validate file content and size
            from app.ingest.validation import validate_file_content, validate_file_size
            from app.persistent_config import UPLOAD_MAX_SIZE_MB

            max_size_mb = await UPLOAD_MAX_SIZE_MB.get(session)
            try:
                validate_file_content(file_path, job.source_filename)
                validate_file_size(file_path, max_size_mb * 1024 * 1024)
            except ValueError as exc:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(timezone.utc)
                await session.commit()
                _Path(file_path).unlink(missing_ok=True)
                return

            # 4. Hash source file
            source_sha256 = await asyncio.to_thread(sha256_file, file_path)

            # 5. Extract metadata
            meta = await asyncio.to_thread(extract_raster_metadata, file_path)

            # Read GDAL options from user_metadata (set at commit time)
            um = job.user_metadata or {}
            assign_crs = um.get("srid_override")
            user_compression = um.get("compression") or "DEFLATE"
            user_resampling = um.get("resampling") or None
            user_nodata = um.get("nodata_override")
            crs_missing = um.get("crs_missing", False)

            if not meta.get("crs_wkt") and not assign_crs:
                if crs_missing:
                    raise ValueError(
                        "Missing CRS: raster has no coordinate reference system. "
                        "Provide a CRS override (EPSG code) at import time."
                    )
                raise ValueError(
                    "Missing CRS: raster has no coordinate reference system."
                )

            # 6. Check/convert to COG
            tmp_dir = tempfile.mkdtemp()
            local_cog_path, cog_status = await asyncio.to_thread(
                check_and_prepare_cog,
                file_path,
                tmp_dir,
                compression=user_compression,
                resampling=user_resampling,
                nodata=user_nodata,
                assign_crs=assign_crs if assign_crs and crs_missing else None,
            )

            # 7. Hash COG
            asset_sha256 = await asyncio.to_thread(sha256_file, local_cog_path)
            cog_size = os.path.getsize(local_cog_path)

            # 8. Generate quicklooks
            ql256 = await asyncio.to_thread(generate_quicklook, local_cog_path, 256)
            ql512 = await asyncio.to_thread(generate_quicklook, local_cog_path, 512)

            # 9. Create DB records
            um = job.user_metadata or {}
            title = um.get("title") or job.source_filename or "raster_dataset"
            record, dataset, raster_asset = await create_raster_dataset(
                session,
                meta=meta,
                source_sha256=source_sha256,
                asset_sha256=asset_sha256,
                cog_status=cog_status,
                cog_size=cog_size,
                source_filename=job.source_filename,
                created_by=uuid.UUID(user_id),
                title=title,
                summary=um.get("summary"),
                visibility=um.get("visibility", "private"),
            )

            # 9b. Set temporal fields on Record
            from datetime import date as _date

            ts_raw = um.get("temporal_start") or meta.get("temporal_start")
            te_raw = um.get("temporal_end")
            if ts_raw:
                try:
                    record.temporal_start = _date.fromisoformat(ts_raw)
                except (ValueError, TypeError):
                    pass
            if te_raw:
                try:
                    record.temporal_end = _date.fromisoformat(te_raw)
                except (ValueError, TypeError):
                    pass
            await session.flush()

            # 10. Store COG and quicklooks to managed storage
            from app.storage import get_storage

            storage = get_storage()
            base_key = f"rasters/{dataset.id}/{asset_sha256}"
            cog_key = f"{base_key}/source.cog.tif"
            ql256_key = f"{base_key}/quicklook_256.png"
            ql512_key = f"{base_key}/quicklook_512.png"

            with open(local_cog_path, "rb") as fobj:
                await storage.put(cog_key, fobj)
            await storage.put(ql256_key, io.BytesIO(ql256))
            await storage.put(ql512_key, io.BytesIO(ql512))

            # 11. Update asset URIs and create distribution
            raster_asset.asset_uri = cog_key
            raster_asset.quicklook_256_uri = ql256_key
            raster_asset.quicklook_512_uri = ql512_key
            await session.flush()

            from app.datasets.models import RecordDistribution

            distribution = RecordDistribution(
                record_id=record.id,
                distribution_type="download",
                format="geotiff",
                url=cog_key,
            )
            session.add(distribution)

            # 12. Finalize job
            job.status = "complete"
            job.dataset_id = dataset.id
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

            # Invalidate cache
            await invalidate_catalog_cache()

            # 13. Generate embedding (non-fatal)
            from app.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

        except Exception as exc:
            await session.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            raise
        finally:
            # Clean up temp COG dir
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            # Clean up local staging file
            if job.status == "complete":
                _Path(file_path).unlink(missing_ok=True)
            elif file_path != original_file_path:
                _Path(file_path).unlink(missing_ok=True)


@task_app.task(queue="raster", retry=1)
async def ingest_vrt(
    job_id: str,
    user_id: str,
    source_dataset_ids: str,
    vrt_type: str,
    resolution_strategy: str,
    **kwargs,
) -> None:
    """Background task: build a VRT, extract metadata, and register as a catalog dataset.

    Full pipeline:
    1. Update job status to running
    2. Parse source_dataset_ids JSON
    3. Load RasterAsset rows for each source dataset
    4. Resolve asset_uri -> filesystem/S3 paths
    5. Build VRT via gdalbuildvrt (spatial mosaic or band stack)
    6. Extract metadata from assembled VRT via rasterio
    7. Hash VRT file
    8. Generate quicklooks (non-fatal)
    9. Create DB records (Record + Dataset + RasterAsset + vrt_source_links)
    10. Store VRT and quicklooks to managed storage
    11. Update asset URIs and create distribution record
    12. Set job.dataset_id on completion
    13. Invalidate cache, defer embedding
    """
    import asyncio
    import io
    import json as _json
    import os
    import shutil
    import tempfile

    from app.datasets.models import Dataset, RecordDistribution  # noqa: F401
    from app.jobs.models import IngestJob
    from app.raster.models import RasterAsset

    logger_vrt = __import__("logging").getLogger(__name__)

    tmp_dir: str | None = None

    async with async_session() as session:
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one()

        try:
            # 1. Mark running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # 2. Parse source dataset IDs
            ids = [uuid.UUID(sid) for sid in _json.loads(source_dataset_ids)]

            # 3. Load RasterAsset rows for source datasets
            asset_result = await session.execute(
                select(RasterAsset)
                .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                .where(Dataset.id.in_(ids))
            )
            asset_map = {
                asset.dataset_id: asset for asset in asset_result.scalars().all()
            }
            # Preserve insertion order
            ordered_assets = [asset_map[sid] for sid in ids if sid in asset_map]

            # 4. Resolve paths
            source_paths = [
                resolve_vrt_source_path(asset.asset_uri) for asset in ordered_assets
            ]

            # 5. Build VRT
            tmp_dir = tempfile.mkdtemp()
            vrt_path = os.path.join(tmp_dir, "source.vrt")
            await asyncio.to_thread(
                build_vrt, vrt_type, source_paths, vrt_path, resolution_strategy
            )

            # 6. Extract metadata from assembled VRT
            meta = await asyncio.to_thread(extract_raster_metadata, vrt_path)
            if not meta.get("crs_wkt"):
                raise ValueError("Assembled VRT has no coordinate reference system.")

            # 7. Hash and size VRT file
            asset_sha256 = await asyncio.to_thread(sha256_file, vrt_path)
            vrt_size = os.path.getsize(vrt_path)

            # 8. Generate quicklooks (non-fatal)
            try:
                ql256 = await asyncio.to_thread(generate_quicklook, vrt_path, 256)
                ql512 = await asyncio.to_thread(generate_quicklook, vrt_path, 512)
            except Exception:
                logger_vrt.warning("Quicklook generation failed for VRT %s", job_id)
                ql256 = ql512 = None

            # 9. Create DB records
            um = job.user_metadata or {}
            title = um.get("title") or f"vrt_{vrt_type}"
            record, dataset, raster_asset = await create_vrt_dataset(
                session,
                meta=meta,
                asset_sha256=asset_sha256,
                vrt_size=vrt_size,
                source_filename=None,
                created_by=uuid.UUID(user_id),
                title=title,
                summary=um.get("summary"),
                visibility=um.get("visibility", "private"),
                vrt_type=vrt_type,
                resolution_strategy=resolution_strategy,
                source_dataset_ids=ids,
            )

            # 10. Store VRT and quicklooks to managed storage
            from app.storage import get_storage

            storage = get_storage()
            base_key = f"rasters/{dataset.id}/{asset_sha256}"
            vrt_key = f"{base_key}/source.vrt"
            ql256_key = f"{base_key}/quicklook_256.png"
            ql512_key = f"{base_key}/quicklook_512.png"

            with open(vrt_path, "rb") as fobj:
                await storage.put(vrt_key, fobj)

            if ql256 is not None:
                await storage.put(ql256_key, io.BytesIO(ql256))
            if ql512 is not None:
                await storage.put(ql512_key, io.BytesIO(ql512))

            # 11. Update asset URIs and create distribution
            raster_asset.asset_uri = vrt_key
            if ql256 is not None:
                raster_asset.quicklook_256_uri = ql256_key
            if ql512 is not None:
                raster_asset.quicklook_512_uri = ql512_key
            await session.flush()

            from app.datasets.models import RecordDistribution

            distribution = RecordDistribution(
                record_id=record.id,
                distribution_type="download",
                format="vrt",
                url=vrt_key,
            )
            session.add(distribution)

            # 12. Finalize job
            job.status = "complete"
            job.dataset_id = dataset.id
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

            # Invalidate cache
            await invalidate_catalog_cache()

            # 13. Generate embedding (non-fatal)
            from app.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

        except Exception as exc:
            await session.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            raise
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)


@task_app.task(queue="raster", retry=1)
async def regenerate_vrt(
    job_id: str, vrt_dataset_id: str, triggered_by: str = "system", **kwargs
) -> None:
    """Background task: rebuild a VRT file after source add/remove and update metadata.

    Atomic swap: new VRT is built to a temp path, then written to the SAME storage key
    as the existing VRT (asset_uri stays unchanged). Titiler continues serving the old
    file until the overwrite completes.

    Full pipeline:
    1. Mark job running
    2. Load VRT RasterAsset
    3. Load vrt_source_links ordered by position -> source dataset IDs
    4. Load source RasterAsset rows, resolve paths
    5. Build new VRT to temp path
    6. Post-validate via rasterio
    7. Extract metadata from new VRT
    8. Hash and size new VRT
    9. Generate quicklooks (non-fatal)
    10. Overwrite existing storage key (atomic swap)
    11. Update RasterAsset metadata fields
    12. Set status='ready', last_regenerated_at, clear current_generation_id
    13. Update dataset footprint geometry
    14. Mark job complete
    15. Invalidate cache, defer embedding
    """
    import asyncio
    import io
    import os
    import shutil
    import tempfile

    from app.datasets.models import Dataset
    from app.jobs.models import IngestJob
    from app.raster.models import RasterAsset, VrtGeneration
    from sqlalchemy import func, select, text

    logger_regen = __import__("logging").getLogger(__name__)

    tmp_dir: str | None = None
    vrt_asset = None
    generation_id: uuid.UUID | None = None

    async with async_session() as session:
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one()

        try:
            # 1. Mark running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # 2. Load VRT RasterAsset
            vrt_id = uuid.UUID(vrt_dataset_id)
            asset_result = await session.execute(
                select(RasterAsset)
                .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                .where(Dataset.id == vrt_id)
            )
            vrt_asset = asset_result.scalar_one_or_none()
            if vrt_asset is None:
                raise ValueError(f"VRT dataset {vrt_dataset_id} not found")

            # 3. Load vrt_source_links ordered by position
            links_result = await session.execute(
                text(
                    "SELECT source_dataset_id FROM catalog.vrt_source_links "
                    "WHERE vrt_dataset_id = :vrt_id ORDER BY position ASC"
                ),
                {"vrt_id": vrt_id},
            )
            source_ids = [row.source_dataset_id for row in links_result.fetchall()]
            if not source_ids:
                raise ValueError(f"VRT {vrt_dataset_id} has no source links")

            # 3b. Create VrtGeneration record
            generation = VrtGeneration(
                vrt_dataset_id=vrt_id,
                status="running",
                started_at=datetime.now(timezone.utc),
                source_count=len(source_ids),
                triggered_by=triggered_by,
            )
            session.add(generation)
            await session.flush()
            generation_id = generation.id
            vrt_asset.current_generation_id = generation.id
            await session.commit()

            # 4. Load source RasterAsset rows and resolve paths
            source_assets_result = await session.execute(
                select(RasterAsset)
                .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                .where(Dataset.id.in_(source_ids))
            )
            asset_map = {a.dataset_id: a for a in source_assets_result.scalars().all()}
            ordered_assets = [asset_map[sid] for sid in source_ids if sid in asset_map]
            source_paths = [
                resolve_vrt_source_path(a.asset_uri) for a in ordered_assets
            ]

            # 5. Build VRT to temp path
            tmp_dir = tempfile.mkdtemp()
            vrt_path = os.path.join(tmp_dir, "source.vrt")
            vrt_type = vrt_asset.vrt_type or "mosaic"
            resolution_strategy = vrt_asset.resolution_strategy or "finest"

            await asyncio.to_thread(
                build_vrt, vrt_type, source_paths, vrt_path, resolution_strategy
            )

            # 6 & 7. Extract metadata (also serves as post-validation)
            meta = await asyncio.to_thread(extract_raster_metadata, vrt_path)
            if not meta.get("crs_wkt"):
                raise ValueError("Regenerated VRT has no coordinate reference system.")

            # 8. Hash and size
            new_sha256 = await asyncio.to_thread(sha256_file, vrt_path)
            new_size = os.path.getsize(vrt_path)

            # 9. Generate quicklooks (non-fatal)
            try:
                ql256 = await asyncio.to_thread(generate_quicklook, vrt_path, 256)
                ql512 = await asyncio.to_thread(generate_quicklook, vrt_path, 512)
            except Exception:
                logger_regen.warning(
                    "Quicklook regeneration failed for VRT %s", vrt_dataset_id
                )
                ql256 = ql512 = None

            # 10. Overwrite existing storage key (atomic swap -- same URI, new content)
            storage = get_storage()
            vrt_key = vrt_asset.asset_uri  # unchanged -- same key

            with open(vrt_path, "rb") as fobj:
                await storage.put(vrt_key, fobj)

            if ql256 is not None and vrt_asset.quicklook_256_uri:
                await storage.put(vrt_asset.quicklook_256_uri, io.BytesIO(ql256))
            if ql512 is not None and vrt_asset.quicklook_512_uri:
                await storage.put(vrt_asset.quicklook_512_uri, io.BytesIO(ql512))

            # 11. Update RasterAsset metadata fields
            nodata_val = meta.get("nodata")
            vrt_asset.sha256 = new_sha256
            vrt_asset.size_bytes = new_size
            vrt_asset.crs_wkt = meta.get("crs_wkt")
            vrt_asset.epsg = meta.get("epsg")
            vrt_asset.band_count = meta.get("band_count")
            vrt_asset.dtype = meta.get("dtype")
            vrt_asset.nodata = str(nodata_val) if nodata_val is not None else None
            vrt_asset.res_x = meta.get("res_x")
            vrt_asset.res_y = meta.get("res_y")
            vrt_asset.width = meta.get("width")
            vrt_asset.height = meta.get("height")
            vrt_asset.compression = meta.get("compression")

            # 12. Status transitions
            vrt_asset.status = "ready"
            vrt_asset.last_regenerated_at = datetime.now(timezone.utc)
            vrt_asset.current_generation_id = None

            # 12b. Update generation record
            generation.status = "completed"
            generation.completed_at = datetime.now(timezone.utc)
            generation.duration_seconds = (
                generation.completed_at - generation.started_at
            ).total_seconds()

            # 13. Update dataset footprint geometry
            dataset_result = await session.execute(
                select(Dataset).where(Dataset.id == vrt_id)
            )
            vrt_dataset = dataset_result.scalar_one_or_none()
            if vrt_dataset is not None and meta.get("bbox_wkt"):
                vrt_dataset.record.spatial_extent = func.ST_GeomFromText(
                    meta["bbox_wkt"], 4326
                )

            # 14. Finalize job
            job.status = "complete"
            job.dataset_id = vrt_id
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

            # 15. Invalidate cache and defer embedding
            await invalidate_catalog_cache()
            await defer_embedding(vrt_dataset)

        except Exception as exc:
            await session.rollback()
            if vrt_asset is not None:
                vrt_asset.status = "failed"
                vrt_asset.current_generation_id = None
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)

            # Update generation record on failure
            if generation_id is not None:
                gen_result = await session.execute(
                    select(VrtGeneration).where(VrtGeneration.id == generation_id)
                )
                gen = gen_result.scalar_one_or_none()
                if gen:
                    gen.status = "failed"
                    gen.completed_at = datetime.now(timezone.utc)
                    if gen.started_at:
                        gen.duration_seconds = (
                            gen.completed_at - gen.started_at
                        ).total_seconds()
                    gen.error_message = str(exc)

            await session.commit()
            raise
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
