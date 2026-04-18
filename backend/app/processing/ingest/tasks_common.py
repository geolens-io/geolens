"""Shared helpers, dataclasses, and app configuration for ingest tasks.

Contains the Procrastinate App instance, shared dataclasses (IngestContext,
StagingResult), job lifecycle helpers, metadata extraction utilities,
validation, and the finalize pipeline used across vector, raster, VRT,
and reupload workflows.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from procrastinate import App, PsycopgConnector

from app.platform.cache.tiles import invalidate_catalog_cache
from app.core.config import settings
from app.processing.embeddings.helpers import defer_embedding
from app.platform.storage import get_storage

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.processing.ingest.warnings import IngestJobWarning
    from app.platform.jobs.models import IngestJob


@dataclass
class IngestContext:
    """Bundle of parameters shared across the post-ogr2ogr finalize pipeline.

    KISS-2 / K7: ``_finalize_ingest`` used to take 11 keyword-only
    parameters, which made every call site noisy and hard to keep in sync.
    Collecting them in a dataclass keeps the call sites terse and adds a
    single obvious place to add future finalize inputs.
    """

    session: "AsyncSession"
    job: "IngestJob"
    table_name: str
    user_id: str
    has_geometry: bool | None
    effective_srid: int | None
    source_format: str
    source_filename: str | None
    original_srid: int | None
    user_metadata: dict
    source_url: str | None = None


@dataclass
class StagingResult:
    """Intermediate staging outputs before dataset creation."""

    metadata: dict
    sample_values: dict
    three_d: dict
    has_geometry: bool
    geometry_type: str | None


_connector_kwargs: dict = {"min_size": 1, "max_size": 3}
if settings.db_use_external_pooler:
    _connector_kwargs["kwargs"] = {"prepare_threshold": None}

task_app = App(
    connector=PsycopgConnector(
        conninfo=settings.procrastinate_conninfo,
        **_connector_kwargs,
    ),
    import_paths=[
        "app.processing.ingest.tasks_vector",
        "app.processing.ingest.tasks_raster",
        "app.processing.ingest.tasks_vrt",
        "app.processing.ingest.tasks_reupload",
        "app.processing.embeddings.tasks",
    ],
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


def _append_job_warning(job, warning: "IngestJobWarning") -> None:
    """Append a structured warning to ``job.user_metadata['warnings']``.

    Consolidates the 6× duplicated pattern from the ingest entry points
    (KISS-1). Mutates ``job.user_metadata`` in place, creating the list if
    absent. Caller is responsible for committing the session.

    The ``warning`` argument is a TypedDict from
    ``app.ingest.warnings.IngestJobWarning`` — either
    ``ReservedRenameWarning`` or ``DbfTruncationCollisionWarning``. Routing
    through the producer helpers in that module closes the type gap between
    the Python task code and the Pydantic ``JobStatusResponse`` (TYPE-1).
    """
    warnings_list = list((job.user_metadata or {}).get("warnings", []))
    warnings_list.append(warning)
    job.user_metadata = {
        **(job.user_metadata or {}),
        "warnings": warnings_list,
    }


def _parse_temporal_fields(
    *,
    temporal_start: str | None,
    temporal_end: str | None,
) -> tuple["date | None", "date | None", dict[str, str]]:
    """Parse raster ingest temporal fields, returning (start, end, errors).

    Each field is ISO-8601-parsed independently. Values that fail to parse
    are dropped from the return tuple but recorded in the errors dict (keyed
    by field name, value is the raw input truncated to 100 chars) so the
    caller can persist them to ``job.user_metadata.temporal_parse_errors``
    for the UI to surface (N5).

    Extracted from ``ingest_raster`` to keep the parse branch unit-testable
    without spinning up a raster subprocess.
    """
    from datetime import date as _date

    logger = structlog.get_logger()
    parsed_start: date | None = None
    parsed_end: date | None = None
    errors: dict[str, str] = {}

    if temporal_start:
        try:
            parsed_start = _date.fromisoformat(temporal_start)
        except (ValueError, TypeError) as exc:
            logger.debug(
                "Ignoring unparseable temporal_start on raster ingest",
                raw_value=str(temporal_start)[:100],
                error=str(exc),
            )
            errors["temporal_start"] = str(temporal_start)[:100]

    if temporal_end:
        try:
            parsed_end = _date.fromisoformat(temporal_end)
        except (ValueError, TypeError) as exc:
            logger.debug(
                "Ignoring unparseable temporal_end on raster ingest",
                raw_value=str(temporal_end)[:100],
                error=str(exc),
            )
            errors["temporal_end"] = str(temporal_end)[:100]

    return parsed_start, parsed_end, errors


def _bind_task_log_context(*, task_name: str, job_id: str, **extra: object) -> None:
    """Bind structlog contextvars for a worker task entry point (N1/R-18/R-24).

    The HTTP middleware uses ``structlog.contextvars.bind_contextvars`` to
    attach a ``request_id`` to every log line emitted during a request.
    Procrastinate tasks run outside the request loop, so they need their own
    correlation key — the ``job_id`` is the natural fit: concurrent ingests
    all log into the same stream and ``job_id`` lets operators filter to one
    upload's worth of events. Each task call clears any stale vars first so
    re-used workers cannot leak state from a prior job.
    """

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        service="worker",
        task=task_name,
        job_id=job_id,
        **extra,
    )


async def _validate_upload_file_safety(
    session,
    *,
    file_path: str,
    source_filename: str | None,
) -> None:
    """Run the three-step upload-safety gauntlet before ogr2ogr touches a file.

    - content validation (magic bytes, extension match, CSV parse)
    - size validation (against the persistent_config max)
    - zip-bomb / path-traversal validation (only for .zip uploads)

    Shared by ``ingest_file``, ``reupload_file``, and ``ingest_raster``
    (KISS-3/5/6 consolidation). Raises ``ValueError`` on any check so
    each caller can map to its own job-failure handling.
    """
    from app.processing.ingest.validation import (
        validate_file_content,
        validate_file_size,
        validate_zip_safety,
    )
    from app.core.persistent_config import UPLOAD_MAX_SIZE_MB

    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(session)

    # validate_file_content wants a non-None filename for extension parsing;
    # fall back to the file's own basename so the content-check still runs.
    effective_filename = source_filename or Path(file_path).name
    validate_file_content(file_path, effective_filename)
    validate_file_size(file_path, max_size_mb * 1024 * 1024)
    if file_path.lower().endswith(".zip"):
        validate_zip_safety(file_path)


def _resolve_effective_srid(
    *,
    detected_srid: int | None,
    srid_override: int | None,
) -> int:
    """Decide which SRID to feed to ``add_4326_column``.

    User override takes precedence, otherwise the detected source SRID,
    otherwise 4326 (safe default for GeoJSON/CSV). K1/KISS-3 extraction from
    ``ingest_file``. Callers in non-spatial paths should not invoke this
    helper — the fallback only makes sense when the caller has already
    decided a geometry column will exist.
    """
    if srid_override is not None:
        return int(srid_override)
    if detected_srid is not None:
        return int(detected_srid)
    return 4326


async def _detect_and_override_geometry(
    session,
    *,
    table_name: str,
    user_metadata: dict,
) -> str | None:
    """Apply user x/y or WKT geometry overrides to a freshly-loaded table.

    Runs ``construct_point_geometry`` or ``construct_wkt_geometry`` when the
    user supplied ``x_column + y_column`` or ``geom_column`` in the commit
    metadata. Returns the geometry type string the caller should use in place
    of the ogrinfo-detected value (or ``None`` if neither override is set —
    callers guard on ``user_wants_geom`` so this branch is defensive only).

    Callers are responsible for importing the file as non-spatial (see the
    ``ogr_geometry_type = None if user_wants_geom else ...`` branch in
    ``ingest_file``) before invoking this helper. K1/KISS-3 extraction.
    """
    from app.processing.ingest.metadata import _validate_table_name

    # Defense-in-depth: every other SQL builder in metadata.py validates
    # the table name before interpolating it into raw SQL; match the
    # convention here so the helper stays safe even if a future caller
    # passes an unsanitized name (RESILIENCE-5).
    _validate_table_name(table_name)

    x_column = (user_metadata.get("x_column") or "").lower() or None
    y_column = (user_metadata.get("y_column") or "").lower() or None
    geom_column = (user_metadata.get("geom_column") or "").lower() or None

    if x_column and y_column:
        from app.processing.ingest.metadata import construct_point_geometry

        await construct_point_geometry(session, table_name, x_column, y_column)
        return "Point"

    if geom_column:
        from sqlalchemy import text as _text

        from app.processing.ingest.metadata import construct_wkt_geometry

        await construct_wkt_geometry(session, table_name, geom_column)
        # Re-detect geometry type from the constructed column so downstream
        # metadata reflects what was actually built (lines/polygons/etc).
        result = await session.execute(
            _text(
                f"SELECT GeometryType(geom) FROM data.{table_name} "
                f"WHERE geom IS NOT NULL LIMIT 1"
            )
        )
        geometry_type = result.scalar_one_or_none() or "Geometry"
        return geometry_type

    return None


async def _archive_original_file(
    session,
    *,
    job,
    dataset_id,
    file_path: str,
    log_message: str = "Failed to archive original file to storage",
    commit: bool = True,
) -> None:
    """Upload the original source file to the storage provider (best-effort).

    Archive failures must NOT fail the ingest — the dataset is already
    committed at this point. Instead, record the failure on
    ``job.user_metadata`` so the UI and operators can audit (R-2).
    K1/KISS-3 extraction from ``ingest_file``; CLEANUP-4 extended it to
    support ``reupload_file`` by letting the caller override the log
    message and suppress the inline commit (reupload's caller commits
    the metadata mutation alongside the ``job.status = "complete"``
    transition so the flag is durable without a second round trip).

    When ``commit`` is True the metadata-update ``session.commit()`` is
    wrapped in its own try/except so that a transient DB error
    (deadlock, pooler drop) during the archive-failed flag persistence
    cannot flip the already-successful ingest into a ``failed`` job. If
    the commit fails, we log and give up — the dataset is still
    queryable, the operator just loses the ``archive_failed``
    breadcrumb for this attempt.
    """

    logger = structlog.get_logger()
    archive_key = f"originals/{dataset_id}/{Path(file_path).name}"
    try:
        storage = get_storage()
        with open(file_path, "rb") as fobj:
            await storage.put(archive_key, fobj)
    except Exception as archive_exc:  # broad: archive is best-effort; S3/local I/O can fail for any reason
        logger.warning(
            log_message,
            archive_key=archive_key,
            dataset_id=str(dataset_id),
            error=str(archive_exc)[:500],
        )
        job.user_metadata = {
            **(job.user_metadata or {}),
            "archive_failed": True,
            "archive_error": str(archive_exc)[:500],
        }
        if not commit:
            return
        try:
            await session.commit()
        except Exception as commit_exc:  # broad: transient DB errors (deadlock, pooler drop) during flag persistence
            await session.rollback()
            logger.warning(
                "Failed to persist archive_failed flag on job",
                archive_key=archive_key,
                dataset_id=str(dataset_id),
                error=str(commit_exc)[:500],
            )


async def _run_staging_pipeline(
    session,
    *,
    table_name: str,
    has_geometry: bool,
    effective_srid: int | None,
) -> StagingResult:
    """Run the post-ogr2ogr staging pipeline on a table.

    Shared by ``_ingest_vector_into_staging`` (new ingests) and
    ``reupload_file`` (re-uploads). Performs: ensure_geom_column,
    clip_to_mercator_bounds, add_4326_column, grant_reader_access,
    extract_metadata, detect_3d_metadata, promote_z_to_elev, and
    get_sample_values. Does not commit.
    """
    from app.processing.ingest.metadata import (
        add_4326_column,
        clip_to_mercator_bounds,
        detect_3d_metadata,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
        promote_z_to_elev,
    )

    if has_geometry:
        has_geometry = await ensure_geom_column(session, table_name)
        if has_geometry:
            await clip_to_mercator_bounds(session, table_name)
            if effective_srid is not None:
                await add_4326_column(session, table_name, effective_srid)

    await grant_reader_access(session, table_name)

    metadata = await extract_metadata(session, table_name)
    three_d = await detect_3d_metadata(session, table_name)

    if three_d.get("is_3d"):
        elev_promoted = await promote_z_to_elev(
            session, table_name, metadata.get("geometry_type")
        )
        if elev_promoted:
            from app.processing.ingest.metadata import get_column_info

            metadata["column_info"] = await get_column_info(session, table_name)

    sample_values = await get_sample_values(
        session, table_name, metadata.get("column_info", [])
    )

    return StagingResult(
        metadata=metadata,
        sample_values=sample_values,
        three_d=three_d,
        has_geometry=has_geometry,
        geometry_type=metadata.get("geometry_type"),
    )


async def _cleanup_staging_on_failure(
    session,
    *,
    staging_table: str,
    job,
    exc: Exception,
    task_name: str,
) -> None:
    """Roll back, drop staging table, and mark job as failed.

    Shared by ``reupload_file`` and ``reupload_service`` which have
    structurally identical exception handlers.
    """
    from sqlalchemy import text

    from app.processing.ingest.metadata import _qtable

    await session.rollback()
    try:
        await session.execute(text(f"DROP TABLE IF EXISTS {_qtable(staging_table)}"))
        await session.commit()
    except Exception as cleanup_exc:  # broad: cleanup is best-effort after rollback; DB may be in bad state
        structlog.get_logger().warning(
            f"Staging-table cleanup failed during {task_name} failure",
            staging_table=staging_table,
            cleanup_error=str(cleanup_exc),
            original_error=str(exc),
        )

    job.status = "failed"
    job.error_message = str(exc)
    job.completed_at = datetime.now(timezone.utc)
    structlog.get_logger().exception(
        "Ingest task failed",
        job_id=str(job.id),
        task=task_name,
    )
    await session.commit()


async def _ingest_vector_into_staging(
    session,
    *,
    job,
    file_path: str,
    target_table: str,
    source_srid: int | None,
    ogr_geometry_type: str | None,
    has_geometry: bool,
    effective_srid: int | None,
    layer_name: str | None = None,
    ogrinfo_columns: list[dict] | None = None,
    user_wants_geom: bool = False,
    user_metadata: dict | None = None,
) -> StagingResult:
    """Load a vector source into staging and return extracted staging metadata.

    This helper preserves the staging-pipeline unit-test boundary while the
    production ingest path continues to inline the broader job lifecycle.
    It intentionally performs no commits.
    """
    from app.processing.ingest.metadata import rename_reserved_columns
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr

    if user_wants_geom and user_metadata is None:
        raise ValueError("user_metadata is required when user_wants_geom=True")

    db_conn_str = build_pg_conn_str()
    await run_ogr2ogr(
        file_path,
        target_table,
        db_conn_str,
        source_srid=source_srid,
        geometry_type=ogr_geometry_type,
        layer_name=layer_name,
    )

    reserved_renames = await rename_reserved_columns(session, target_table)
    if reserved_renames:
        from app.processing.ingest.warnings import make_reserved_rename_warning

        _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

    if file_path.lower().endswith(".zip"):
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions
        from app.processing.ingest.ogr import run_ogrinfo_preview
        from app.processing.ingest.warnings import make_dbf_truncation_warning

        preview_cols = ogrinfo_columns or []
        if not preview_cols:
            preview_info = await run_ogrinfo_preview(
                file_path, sample_limit=0, layer_name=layer_name
            )
            preview_cols = preview_info.get("columns") or []
        dbf_collisions = detect_dbf_truncation_collisions(preview_cols)
        if dbf_collisions:
            _append_job_warning(job, make_dbf_truncation_warning(dbf_collisions))

    geometry_type = ogr_geometry_type
    if user_wants_geom:
        override_geom_type = await _detect_and_override_geometry(
            session,
            table_name=target_table,
            user_metadata=user_metadata or {},
        )
        if override_geom_type is not None:
            has_geometry = True
            geometry_type = override_geom_type

    result = await _run_staging_pipeline(
        session,
        table_name=target_table,
        has_geometry=has_geometry,
        effective_srid=effective_srid,
    )

    # Preserve the original geometry_type fallback: if _run_staging_pipeline
    # returned a geometry_type from metadata, use it; otherwise fall back to
    # the ogr_geometry_type (possibly overridden by user_wants_geom).
    if result.geometry_type is None and geometry_type is not None:
        result.geometry_type = geometry_type

    return result


async def _finalize_ingest(ctx: IngestContext):
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
        ctx: IngestContext bundle of finalize parameters. See the dataclass
            docstring for field descriptions (K7 refactor).

    Returns:
        The created Dataset ORM instance.
    """
    from app.modules.catalog.datasets.domain.service import create_dataset
    from app.processing.ingest.metadata import (
        add_4326_column,
        clip_to_mercator_bounds,
        compute_quality_score,
        detect_3d_metadata,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
        promote_z_to_elev,
    )

    session = ctx.session
    job = ctx.job
    table_name = ctx.table_name
    user_metadata = ctx.user_metadata
    source_filename = ctx.source_filename

    # Normalize geometry column name to 'geom'
    has_geometry = ctx.has_geometry
    if has_geometry is None:
        has_geometry = await ensure_geom_column(session, table_name)
    elif has_geometry:
        await ensure_geom_column(session, table_name)

    # Clip geometries to Web Mercator bounds and add 4326 column.
    # When has_geometry is truthy, callers always supply a non-null
    # effective_srid — guard for mypy since the two params are independent
    # at the signature level.
    if has_geometry:
        assert ctx.effective_srid is not None, (
            "effective_srid must be set when has_geometry is True"
        )
        await clip_to_mercator_bounds(session, table_name)
        await add_4326_column(session, table_name, ctx.effective_srid)

    # Grant reader access
    await grant_reader_access(session, table_name)

    # Extract metadata
    metadata = await extract_metadata(session, table_name)

    # Detect 3D geometry properties (per Phase 999.2)
    three_d = await detect_3d_metadata(session, table_name)

    # Attribute promotion: extract ST_Z into elev column for 3D points
    if three_d.get("is_3d"):
        elev_promoted = await promote_z_to_elev(
            session, table_name, metadata.get("geometry_type")
        )
        if elev_promoted:
            # Re-extract column_info so elev appears in the column list
            from app.processing.ingest.metadata import get_column_info

            metadata["column_info"] = await get_column_info(session, table_name)

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
        created_by=uuid.UUID(ctx.user_id),
        summary=user_metadata.get("summary"),
        srid=metadata.get("srid"),
        geometry_type=metadata.get("geometry_type"),
        feature_count=metadata.get("feature_count"),
        extent_wkt=metadata.get("extent_wkt"),
        column_info=metadata.get("column_info"),
        sample_values=sample_values,
        source_format=ctx.source_format,
        source_filename=source_filename,
        original_srid=ctx.original_srid
        if ctx.original_srid is not None
        else metadata.get("srid"),
        is_3d=three_d.get("is_3d"),
        n_dims=three_d.get("n_dims"),
        z_min=three_d.get("z_min"),
        z_max=three_d.get("z_max"),
        visibility=user_metadata.get("visibility", "private"),
    )
    if ctx.source_url is not None:
        create_kwargs["source_url"] = ctx.source_url
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

    # Generate vector quicklook thumbnail (non-fatal, after commit).
    # Runs after commit so a connection-killing query (OOM, timeout on
    # complex geometry) cannot roll back the dataset. N3: the inner
    # try/except splits "generation/upload failed" from "commit failed" so
    # operators can tell which phase died when reading logs.
    if has_geometry:
        import structlog as _sl

        _ql_log = _sl.get_logger()
        try:
            import io as _io

            from app.processing.vector.quicklook import (
                generate_vector_quicklook_with_timeout as generate_vector_quicklook,
            )

            ql_bytes = await generate_vector_quicklook(
                session, table_name, metadata.get("geometry_type", ""), 256
            )
            ql_storage = get_storage()
            ql_key = f"vectors/{dataset.id}/quicklook_256.png"
            await ql_storage.put(ql_key, _io.BytesIO(ql_bytes))
            dataset.quicklook_256_uri = ql_key
        except Exception as _ql_exc:  # broad: quicklook generation is non-fatal; geometry rendering can OOM/timeout
            _ql_log.warning(
                "quicklook_failed",
                phase="generate",
                table=table_name,
                error=str(_ql_exc),
            )
        else:
            try:
                await session.commit()
            except Exception as _ql_commit_exc:  # broad: transient commit failure after successful generation
                await session.rollback()
                _ql_log.warning(
                    "quicklook_failed",
                    phase="commit",
                    table=table_name,
                    error=str(_ql_commit_exc),
                )

    # Invalidate caches after successful ingest
    await invalidate_catalog_cache()

    # Generate embedding (non-fatal)

    await defer_embedding(dataset)

    return dataset


def resolve_service_type(raw: str) -> tuple[str, str]:
    """Map raw service_type string to (service_type, source_format)."""
    from app.processing.ingest.ogr import IngestionError

    if raw.startswith("ArcGIS"):
        return "arcgis_featureserver", "arcgis_featureserver"
    elif raw.startswith("WFS"):
        return "wfs", "wfs"
    elif raw.startswith("OGC API"):
        return "ogcapi_features", "ogcapi_features"
    raise IngestionError(
        f"Unrecognized service type '{raw}'. "
        f"Expected a type starting with 'ArcGIS', 'WFS', or 'OGC API'."
    )


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


async def _run_service_import_with_wfs_fallback(
    import_fn,
    source_layer: str,
    *,
    token: str | None = None,
    auth_error_message: str | None = None,
) -> None:
    """Run a service import with WFS namespace retry + optional auth detection.

    Extracts the retry pattern that appears in both ingest_service and
    reupload_service (KISS-8). If the initial import raises
    ``IngestionError`` and the layer name has a ``ns:name`` prefix,
    retries with the unqualified name. If ``auth_error_message`` is
    provided and the token is None and the error looks like an auth
    failure, re-raises with the custom message so users get a clear
    "you probably need a token" hint instead of the raw GDAL stderr.

    ``import_fn`` must be an async callable that accepts a single
    ``layer_name: str`` argument and does the actual ogr2ogr work.
    """
    from app.processing.ingest.ogr import IngestionError

    try:
        await import_fn(source_layer)
    except IngestionError as exc:
        if ":" in source_layer:
            unqualified = source_layer.split(":", 1)[1]
            try:
                await import_fn(unqualified)
            except IngestionError as retry_exc:
                if (
                    auth_error_message is not None
                    and token is None
                    and _looks_like_auth_error(str(retry_exc))
                ):
                    raise IngestionError(auth_error_message) from retry_exc
                raise
        elif (
            auth_error_message is not None
            and token is None
            and _looks_like_auth_error(str(exc))
        ):
            raise IngestionError(auth_error_message) from exc
        else:
            raise


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
    from app.modules.audit.service import log_action
    from app.modules.catalog.collections.models import DatasetVersion
    from app.processing.ingest.metadata import (
        compute_quality_score,
        refresh_attribute_metadata,
    )
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

    from app.processing.ingest.metadata import _qtable

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
