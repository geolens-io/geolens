"""Export API endpoint: download datasets in various formats."""

import asyncio
import os
import re
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.failure_reason import redact_failure_reason
from app.core.identity import Identity
from app.core.record_types import capabilities
from app.modules.auth.dependencies import get_optional_user
from app.core.dependencies import get_db
from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var
from app.platform.dataset_origin import geolens_owns_table
from app.platform.extensions import get_processing_port
from app.platform.http.ranges import (
    if_match_passes,
    if_none_match_matches,
    not_modified_response,
    parse_byte_range,
)
from app.platform.storage import get_storage
from app.processing.export import artifact_cache, artifact_response
from app.processing.export.ogr import (
    FORMAT_MAP,
    MAX_EXPORT_FEATURES as _MAX_EXPORT_FEATURES,
    PARQUET_MEDIA_TYPE,
    ExportError,
    bbox_where_sql,
    pmtiles_maxzoom_for_extent,
)
from app.processing.export.schemas import ExportFormat
from app.processing.export.service import (
    export_dataset,
    export_descriptor,
    file_response_content_disposition,
    validate_where_clause,
)
from app.processing.export.where_validator import canonical_where
from app.processing.ingest.metadata import _qtable
from app.processing.ingest.url_fetch import EDGE_PROXY_READ_TIMEOUT_SECONDS
from app.standards.ogc.errors import (
    BAD_REQUEST_RESPONSE,
    FORBIDDEN_RESPONSE,
    NOT_FOUND_RESPONSE,
    PAYLOAD_TOO_LARGE_RESPONSE,
    PRECONDITION_FAILED_RESPONSE,
    RATE_LIMIT_RESPONSE,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets"],
    responses={
        400: BAD_REQUEST_RESPONSE,
        403: FORBIDDEN_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        413: PAYLOAD_TOO_LARGE_RESPONSE,
    },
)

# Bytes per format, so sync()/asyncio() return a File, not None. Derived from
# FORMAT_MAP/PARQUET_MEDIA_TYPE. Excludes "application/geo+json" (geojson):
# it also names unrelated GeoJSON model responses elsewhere in the API.
_EXPORT_BODY = {
    media_type: {"schema": {"type": "string", "format": "binary"}}
    for media_type in (
        [fmt["media"] for fmt in FORMAT_MAP.values()] + [PARQUET_MEDIA_TYPE]
    )
    if media_type != "application/geo+json"
}

# Each cold conversion spawns ogr2ogr or streams rows into a temp file, so
# concurrent ones are capped per process and the overflow is shed with a retry.
_MAX_CONCURRENT_CONVERSIONS = 4
_conversion_slots = asyncio.Semaphore(_MAX_CONCURRENT_CONVERSIONS)


def _bare_satisfiable_range(request: Request, size: int) -> tuple[int, int] | None:
    """The resolved slice a bare Range (no If-Range) asks for, if it could be a 206.

    Parsed with the function ``read_response`` uses, so a malformed,
    multi-range or unsatisfiable header, which the response ignores or
    rejects, never costs the URL-history listing.
    """
    if request.headers.get("if-range") is not None:
        return None
    resolved = parse_byte_range(request.headers.get("range"), size)
    return resolved if isinstance(resolved, tuple) else None


def _leading_bare_range(request: Request, size: int) -> bool:
    """A bare, satisfiable Range whose first byte is 0 — the only one a fresh build honours."""
    resolved = _bare_satisfiable_range(request, size)
    return resolved is not None and resolved[0] == 0


def _cleanup_export(path: str) -> None:
    """Remove the temporary export directory after response is sent."""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


async def _emit_export_audit(
    db: AsyncSession,
    request: Request,
    *,
    user_id: uuid.UUID | None,
    dataset_id: uuid.UUID,
    format: ExportFormat,
    target_crs: str | None,
    bbox: str | None,
    where: str | None,
) -> None:
    """Record one export download. user_id may be None for anonymous.

    One function for both paths that transfer bytes (conversion and cache-hit)
    so they write the same row; only HEAD stays out of the log. Takes the id,
    not ``Identity``: the conversion path calls this after rollback, and
    reading ``user.id`` from the expired ORM instance would refresh from a
    context with no greenlet. ``details.range`` lets a range-probing client's
    rows be told apart from one full download.
    """
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="dataset.export",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "format": format,
                "target_crs": target_crs,
                "bbox": bbox,
                "where": where,
                "range": request.headers.get("range"),
            },
            ip_address=request.client.host if request.client else None,
        ),
    )
    # The commit is the caller's: test_api_key_scope_875's writing-GET tripwire
    # reads the handler's source one level deep, so a commit buried in a helper
    # would be invisible to it.


async def _count_selected_features(
    db: AsyncSession,
    *,
    table_name: str,
    where: str | None,
    column_info: list[dict] | None,
    bbox: list[float] | None,
    has_geometry: bool,
    schema: str,
) -> int:
    """Bounded COUNT of the rows an export's filters actually select.

    Cap guard for oversized datasets: validated WHERE (AST allowlist + column
    check), then an inner LIMIT stops the scan at cap+1, strictly less work than
    the export it gates.
    """
    clauses: list[str] = []
    params: dict = {"limit": _MAX_EXPORT_FEATURES + 1}
    if where is not None:
        try:
            validate_where_clause(where, column_info)
            # The canonical AST re-render, never the caller's raw bytes, so
            # the count query splices no unvalidated user input.
            safe_where = canonical_where(where)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        # Mirrors parquet.py: text() reads ":name" as a bind, so a colon in a
        # validated string literal (e.g. an ISO timestamp) is escaped to
        # text()'s literal-colon form (\:); the real :limit/:minx binds below
        # stay unescaped.
        safe_where = safe_where.replace(":", "\\:")
        clauses.append(f"({safe_where})")
    if bbox is not None and has_geometry:
        # A crossing bbox counts with the predicate the export runs
        # (bbox_where_sql). An ordinary bbox counts with && only: ogr2ogr -spat
        # permits envelope false positives, so an exact ST_Intersects count
        # could pass <=cap while -spat exports more. && errs toward 413.
        if bbox[0] > bbox[2]:
            clauses.append(bbox_where_sql(bbox))
        else:
            clauses.append(
                "geom_4326 && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)"
            )
        params.update(minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3])
    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    sql = (
        f"SELECT COUNT(*) FROM (SELECT 1 FROM "
        f"{_qtable(table_name, schema=schema)} "
        f"WHERE {where_sql} LIMIT :limit) sub"
    )
    result = await db.execute(text(sql).bindparams(**params))
    return result.scalar_one()


def _head_export_response(dataset_title: str, format_key: str) -> Response:
    """The HEAD half of the export route.

    Not `_register_standards_head_routes` (app/api/main.py): that clones the
    route and would run the full conversion on HEAD.

    Every status-deciding check already ran in the shared handler; the
    conversion itself is skipped, so an anonymous caller can't spend a worker
    per request. Can't promise 500/503, which are only knowable by attempting
    the export (``test_head_cannot_promise_conversion_failure_status``).

    ``Accept-Ranges: bytes``: ranges are slices of one stored artifact, never
    spliced across conversions; the no-artifact path streams the conversion
    whole for the same reason, not through starlette's ``FileResponse``.

    Content-Length is deliberately absent (RFC 9110 9.3.2): building an export
    to learn its length is the DoS foot-gun this branch avoids, and GDAL
    retries with a ranged GET instead.
    """
    filename, media_type = export_descriptor(dataset_title, format_key)
    response = Response(
        status_code=status.HTTP_200_OK,
        media_type=media_type,
        headers={
            "content-disposition": file_response_content_disposition(filename),
            # vsicurl learns the length from the first range response.
            "accept-ranges": "bytes",
        },
    )
    # Starlette defaults an empty body to `content-length: 0`, a wrong answer
    # about the export's size that a client would read as an empty file.
    response.raw_headers = [
        (key, value) for key, value in response.raw_headers if key != b"content-length"
    ]
    return response


# HEAD alongside GET, which FastAPI's APIRoute doesn't add automatically;
# GDAL/QGIS probe with it. include_in_schema=False: a derived route publishes
# nothing new.
@router.head("/{dataset_id}/export", include_in_schema=False)
@router.get(
    "/{dataset_id}/export",
    response_class=FileResponse,
    # The handler raises 412 on both the cache-hit and rebuild branches
    # (If-Match no longer matching).
    responses={
        200: {"description": "The exported file", "content": _EXPORT_BODY},
        206: {
            "description": "One byte range of the exported file",
            "content": _EXPORT_BODY,
        },
        304: {"description": "The caller already holds this version of the file"},
        412: PRECONDITION_FAILED_RESPONSE,
        429: RATE_LIMIT_RESPONSE,
    },
)
async def export_dataset_endpoint(
    dataset_id: uuid.UUID,
    request: Request,
    format: ExportFormat = Query(ExportFormat.gpkg, description="Export format"),
    target_crs: str | None = Query(None, description="Target CRS, e.g. EPSG:3857"),
    bbox: str | None = Query(
        None, description="Bounding box: minx,miny,maxx,maxy (WGS84)"
    ),
    where: str | None = Query(
        None, description="Attribute filter expression, e.g. pop > 1000"
    ),
    # Optional: every caller gets public+published datasets without the
    # export capability (OGC/tiles parity); the body gates the rest.
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), CSV, GeoParquet,
    FlatGeobuf, and PMTiles formats. Optional CRS reprojection, spatial
    filtering, and attribute filtering. GeoParquet is always emitted in
    EPSG:4326 (OGC:CRS84). PMTiles renders zooms 0..N where N is extent-budgeted (ceiling 14).
    """
    # The conversion's bound is what's left of the request clock after
    # everything before it, so a slow pre-conversion step (count scan, parquet
    # plan) eats into it. It runs from the request's start (stamped by
    # RequestLoggingMiddleware), not this function, because `Depends`
    # resolution can block on a pool checkout a later clock would miss.
    # Monotonic, so an NTP step can't shorten or extend a running export.
    request_started = getattr(request.state, "started_at_monotonic", None)
    if request_started is None:
        request_started = time.monotonic()
    request_deadline = request_started + EDGE_PROXY_READ_TIMEOUT_SECONDS

    port = get_processing_port()
    data_schema = tenant_data_schema(current_tenant_var.get())
    # 1. Fetch dataset
    dataset = await port.get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # 2. Visibility + permission check. Function-level import: processing/
    # must not import app.modules.catalog at module scope (test_layering.py).
    from app.modules.catalog.authorization import (
        can_export_dataset,
        check_dataset_access_or_anonymous,
    )

    user_roles = await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
    if not await can_export_dataset(db, dataset, dataset_id, user, user_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Anonymous export requires public dataset"
                if user is None
                else "Missing permission: export"
            ),
        )

    # Read while the session that loaded it is still in a transaction: `user`
    # is the ORM instance on this session, and the release below expires it.
    user_id = user.id if user is not None else None

    # 3. Parse bbox
    from app.modules.catalog.features.service import parse_bbox

    bbox_parsed: list[float] | None = None
    if bbox:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )

    # 4. Validate target_crs
    if target_crs is not None:
        if not re.match(r"^EPSG:\d+$", target_crs, re.IGNORECASE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid target_crs: must match EPSG:<code> (e.g. EPSG:3857)",
            )
        # GeoParquet is written directly via pyarrow in EPSG:4326 (OGC:CRS84);
        # reprojection/PROJJSON isn't implemented on that path, so reject a
        # conflicting target rather than silently emitting 4326.
        if format == ExportFormat.parquet and target_crs.upper() != "EPSG:4326":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GeoParquet export is emitted in EPSG:4326; omit target_crs.",
            )
        # PMTiles ignores -t_srs (always tiles in Web Mercator) and only warns
        # on stderr while ogr2ogr exits 0, so a caller asking for another CRS
        # would silently get EPSG:3857 back.
        if format == ExportFormat.pmtiles and target_crs.upper() != "EPSG:3857":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "PMTiles export is always rendered in EPSG:3857 "
                    "(Web Mercator); omit target_crs."
                ),
            )

    # 5. Reject raster/VRT: no tabular feature table. Keyed on record_type, not
    # geometry_type: a non-spatial TABLE dataset also has geometry_type=None but
    # is CSV-exportable.
    if not capabilities(dataset.record.record_type).feature_table:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Raster datasets have no tabular feature data to export; "
                "use the raster tile/COG endpoints."
            ),
        )

    # 6. Check geometry compatibility
    if dataset.geometry_type is None and format in (
        "gpkg",
        "geojson",
        "shp",
        "parquet",
        "fgb",
        "pmtiles",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot export non-spatial dataset as {format}. Use csv format.",
        )

    # 6c. The cached artifact for this selection, if usable. Resolved before
    # the expensive work below, which would otherwise run `plan_parquet_export`'s
    # bounded count on every range slice of an existing artifact; the ogr COUNT
    # sits below it for the same reason. Safe by construction: an artifact
    # exists only because an earlier request with this key
    # (table_name+title+tile_cache_version) passed every gate.
    selection = artifact_cache.selection_key(
        dataset_id=dataset_id,
        table_name=dataset.table_name,
        dataset_title=dataset.record.title,
        tile_cache_version=dataset.tile_cache_version,
        format_key=str(format),
        target_crs=target_crs,
        bbox=bbox,
        where=where,
        exporter_version=request.app.version,
    )
    # filename/media_type are derived, not stored: `export_descriptor` answers
    # both from title+format without touching the DB.
    cached_filename, cached_media_type = export_descriptor(
        dataset.record.title, str(format)
    )
    held_before_build: set[str] = set()
    artifact = await artifact_cache.lookup(
        dataset_id,
        selection,
        filename=cached_filename,
        media_type=cached_media_type,
        seen_digests=held_before_build,
    )

    if artifact is not None:
        # Preconditions first, in RFC 9110 13.2.2 order (If-Match,
        # If-None-Match, Range/If-Range), above the HEAD return since a probe
        # revalidates too.
        if not if_match_passes(request.headers.get("if-match"), artifact.etag):
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail="Export has changed since the version you hold",
                headers={"etag": artifact.etag},
            )
        if if_none_match_matches(request.headers.get("if-none-match"), artifact.etag):
            return not_modified_response(artifact.etag)
        # Answered here, above planning, so a cached parquet probe, the request
        # a range-reading client makes first and most, never runs the planner.
        if request.method == "HEAD":
            return artifact_response.head_response(artifact)
        # A cache hit still audits (bytes transfer); built only if the response
        # carries bytes, since `read_response` may 416.
        #
        # A contested selection (more than one distinct digest fresh under this
        # key) answers ranges whole; overlapping cold builders are common. So
        # does a hit inside the first TTL after this URL's bytes changed,
        # closing the resume-splice window; the URL's prefix says whether other
        # bytes were answered recently.
        may_serve_range = not artifact.contested
        if may_serve_range and _bare_satisfiable_range(request, artifact.size):
            may_serve_range = (
                not await artifact_cache.url_answered_other_bytes_recently(
                    dataset_id, selection, artifact.digest
                )
            )
        response = artifact_response.read_response(
            get_storage(),
            artifact,
            range_header=request.headers.get("range"),
            if_range=request.headers.get("if-range"),
            may_serve_range=may_serve_range,
        )
        await _emit_export_audit(
            db,
            request,
            user_id=user_id,
            dataset_id=dataset_id,
            format=format,
            target_crs=target_crs,
            bbox=bbox,
            where=where,
        )
        await db.commit()
        return response

    # 6b. Bound full-table exports (a filter must actually narrow the selection
    # under the cap). Below the cache hit, as above: an artifact exists only
    # because an earlier request passed this gate. Parquet is exempt: it owns
    # its own bounded-count cap against live columns.
    if (
        format != ExportFormat.parquet
        and dataset.feature_count is not None
        and dataset.feature_count > _MAX_EXPORT_FEATURES
    ):
        if bbox_parsed is None and where is None:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Dataset has {dataset.feature_count} features, exceeding the "
                    f"{_MAX_EXPORT_FEATURES} unfiltered-export limit; narrow the "
                    "export with a bbox or attribute filter."
                ),
            )

        selected = await _count_selected_features(
            db,
            table_name=dataset.table_name,
            where=where,
            column_info=dataset.column_info,
            bbox=bbox_parsed,
            has_geometry=dataset.geometry_type is not None,
            schema=data_schema,
        )
        if selected > _MAX_EXPORT_FEATURES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Export filter still selects more than "
                    f"{_MAX_EXPORT_FEATURES} features; narrow the export with a "
                    "more selective bbox or attribute filter."
                ),
            )

    # 6d. Remaining status-deciding checks, above the HEAD return so HEAD does
    # not answer 200 for a request the GET refuses.
    parquet_plan = None
    if format == ExportFormat.parquet:
        # Parquet validates the filter against the LIVE columns, not the
        # nullable dataset.column_info (see plan_parquet_export), and owns the
        # bounded count the cap guard above deliberately skips for it.
        from app.processing.export.parquet import (
            ExportTooLargeError,
            plan_parquet_export,
        )

        try:
            parquet_plan = await plan_parquet_export(
                db,
                dataset.table_name,
                schema=data_schema,
                bbox=bbox_parsed,
                where=where,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except ExportTooLargeError as e:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=str(e),
            )
    elif where is not None:
        # ogr2ogr path: same check export_dataset runs, against the same
        # column_info, just early enough for HEAD to see it.
        try:
            validate_where_clause(where, dataset.column_info)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # 6d-b. Hand the pooled connection back before conversion:
    # `port.get_dataset` checked one out and nothing released it, so a handful
    # of concurrent exports could starve the pool (the same hazard as in
    # tiles/router.py). Every value the handler needs is copied out first,
    # because rollback expires the ORM instances and a later attribute read
    # raises MissingGreenlet; dropping the name makes that a NameError instead.
    dataset_title = dataset.record.title
    dataset_table = dataset.table_name
    dataset_columns = dataset.column_info
    dataset_has_geometry = dataset.geometry_type is not None
    dataset_extent = dataset.record.spatial_extent
    # Every in-app write to a table GeoLens owns rolls tile_cache_version or
    # the title, both in the selection key. A registered table can change in
    # place by direct SQL, and a `where` filter can resolve against the clock
    # ('now', 'today'); only the TTL bounds either. Parquet only: ogr2ogr reads
    # a PostGIS layer in heap order, which an UPDATE or synchronized scan moves.
    bytes_follow_key = (
        where is None
        and parquet_plan is not None
        and parquet_plan.has_gid
        and geolens_owns_table(
            dataset.source_format, dataset.record.record_type, dataset.origin_ref
        )
    )
    del dataset
    await db.rollback()

    # A HEAD with nothing fresh still answers a real length and validator when
    # the stored artifact is the only bytes this URL holds; it never builds.
    if request.method == "HEAD" and bytes_follow_key:
        settled = await artifact_cache.settled_artifact(
            dataset_id,
            selection,
            filename=cached_filename,
            media_type=cached_media_type,
        )
        if settled is not None:
            if not if_match_passes(request.headers.get("if-match"), settled.etag):
                raise HTTPException(
                    status_code=status.HTTP_412_PRECONDITION_FAILED,
                    detail="Export has changed since the version you hold",
                    headers={"etag": settled.etag},
                )
            if if_none_match_matches(
                request.headers.get("if-none-match"), settled.etag
            ):
                return not_modified_response(settled.etag)
            return artifact_response.head_response(settled)

    # 6e. HEAD stops here, after every status-deciding gate and before the
    # conversion. No audit event: nothing exported. With an artifact in hand,
    # HEAD answers a real Content-Length/ETag; without one, length is omitted
    # (RFC 9110 9.3.2) because building to learn it is the DoS foot-gun this
    # avoids.
    #
    # Preconditions run against no validator on the cold path, in RFC 9110
    # 13.2.2 order (If-Match before If-None-Match). HEAD refuses a specific
    # If-Match rather than guessing (`If-Match: *` still passes). A wildcard
    # If-None-Match against no validator answers 304 for both verbs, for GET
    # before the conversion.
    if_match_ok_unbuilt = if_match_passes(request.headers.get("if-match"), None)
    if request.method == "HEAD" and not if_match_ok_unbuilt:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Export has changed since the version you hold",
        )
    if if_match_ok_unbuilt and if_none_match_matches(
        request.headers.get("if-none-match"), None
    ):
        return not_modified_response(None)
    if request.method == "HEAD":
        # Only the cold case reaches here; a hit returned above.
        return _head_export_response(dataset_title, format)

    if _conversion_slots.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Export service busy, please retry",
            headers={"Retry-After": "5", "Cache-Control": "no-store"},
        )
    await _conversion_slots.acquire()

    # 7. Run export. GeoParquet uses the pyarrow writer (no Arrow driver in
    # Debian's GDAL); every other format uses ogr2ogr.
    #
    # Stamped when conversion starts reading, not at publication, so the
    # artifact ages from before build+upload+TTL and is never older than that.
    snapshot_at = time.time()
    try:
        if format == ExportFormat.parquet:
            from app.processing.export.parquet import export_parquet

            assert parquet_plan is not None  # set by the parquet branch above
            file_path, filename, media_type = await export_parquet(
                db,
                dataset_table,
                dataset_title,
                schema=data_schema,
                plan=parquet_plan,
                ordered=bytes_follow_key,
                # Bounds the row stream by the edge window, like the ogr2ogr
                # formats below.
                deadline=request_deadline,
            )
        else:
            pmtiles_maxzoom = None
            if format == ExportFormat.pmtiles:
                # MAXZOOM is budgeted from the dataset extent, not the request
                # bbox, since -spat selects whole features without clipping.
                from geoalchemy2.shape import to_shape

                bounds: tuple[float, float, float, float] | None = None
                if dataset_extent is not None:
                    bounds = to_shape(dataset_extent).bounds
                pmtiles_maxzoom = pmtiles_maxzoom_for_extent(bounds)

            file_path, filename, media_type = await export_dataset(
                dataset_table,
                dataset_title,
                format,
                schema=data_schema,
                target_srs=target_crs,
                # A bbox only travels with geometry; csv is the one ogr format
                # a non-spatial dataset can reach, where -spat is a no-op.
                bbox=bbox_parsed if dataset_has_geometry else None,
                where=where,
                column_info=dataset_columns,
                pmtiles_maxzoom=pmtiles_maxzoom,
                deadline=request_deadline,
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ExportError as exc:
        logger.warning(
            "export_failed",
            dataset_id=str(dataset_id),
            format=format.value,
            reason=redact_failure_reason(str(exc)),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Export failed",
        )
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export temporarily unavailable",
        )
    finally:
        _conversion_slots.release()

    # The export file exists from here, but nothing owns it until the response
    # below attaches background cleanup.
    temp_dir = os.path.dirname(file_path)

    # 8. Publish before the response, so the next range-probing request is a
    # slice of this object. A store failure isn't a download failure (`store`
    # returns None rather than raising). If this request lost the publish race,
    # `store` returns the incumbent, and that is served.
    #
    # Under the same cancellation ownership as the audit step: CancelledError
    # is a BaseException, so a disconnect during hash/upload/sweep must not
    # strand the conversion directory (the four-hour orphan sweep bounds it).
    #
    # Hashed here, before `store`, since the preconditions below must be
    # answered from what was built whether or not it's published.
    try:
        # Released again: the GeoParquet branch streams rows through this
        # session, which the hash/upload below would otherwise hold (a no-op
        # on the ogr2ogr branch).
        await db.rollback()
        try:
            digest, size = await artifact_cache.digest_and_size(file_path)
        except Exception:  # broad: an unhashable file still downloads
            digest, size = None, None
        stored = await artifact_cache.store(
            dataset_id,
            selection,
            file_path=file_path,
            filename=filename,
            media_type=media_type,
            digest=digest,
            size=size,
            snapshot_at=snapshot_at,
        )
    except BaseException:
        _cleanup_export(temp_dir)
        raise
    # The validator comes from the published artifact when there is one:
    # `store` recomputes the digest if handed None, so a mismatch with the
    # digest hashed here must not leave `etag` stale.
    if stored is not None:
        etag = stored.etag
    elif digest is not None:
        etag = artifact_cache.strong_etag(digest)
    else:
        etag = None

    # The hit path's preconditions, evaluated here too, so a matching client
    # isn't sent an export it already has and a stale If-Match is refused.
    if not if_match_passes(request.headers.get("if-match"), etag):
        _cleanup_export(temp_dir)
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Export has changed since the version you hold",
            headers={"etag": etag} if etag is not None else None,
        )
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        _cleanup_export(temp_dir)
        return not_modified_response(etag)

    # 8b. Build the response before the audit row, on both branches.
    # `read_response` can still 416 after preconditions pass; building first
    # releases the conversion directory on that exit, and the audit row is
    # written only once bytes exist. Cleanup rides the response because eager
    # deletion can remove more than the export when the temp dir isn't
    # per-export (test_export_antimeridian).
    try:
        if stored is not None:
            # This request BUILT the artifact (or lost the publish race), so
            # a bare Range is sliced only when the selection held these bytes
            # before the build began, the URL holds nothing else and the key
            # pins the bytes: a TTL rollover of unchanged data. Otherwise
            # whole, the safe half of RFC 9110 14.2, except a byte-0 Range (a
            # cold GDAL open's first request) while this URL answered no other
            # bytes recently.
            may_serve_range = False
            leading_slice_ok = False
            if not stored.contested and _bare_satisfiable_range(request, stored.size):
                may_serve_range = (
                    bytes_follow_key
                    and stored.digest in held_before_build
                    and await artifact_cache.url_held_only_these_bytes(
                        dataset_id, selection, stored.digest
                    )
                )
                if not may_serve_range and _leading_bare_range(request, stored.size):
                    leading_slice_ok = (
                        not await artifact_cache.url_answered_other_bytes_recently(
                            dataset_id, selection, stored.digest
                        )
                    )
            response = artifact_response.read_response(
                get_storage(),
                stored,
                range_header=request.headers.get("range"),
                if_range=request.headers.get("if-range"),
                may_serve_range=may_serve_range,
                leading_slice_ok=leading_slice_ok,
                background=BackgroundTask(_cleanup_export, temp_dir),
            )
        else:
            # 9. Serve the conversion itself, with background cleanup. Touch
            # mtime right before the response: sweep_orphaned_exports reads it
            # as recent activity, so the age clock restarts here rather than
            # at the end of generation.
            try:
                os.utime(file_path, None)
            except OSError:
                pass  # best-effort freshness signal; must not block the download
            # Not a FileResponse: starlette's own Range handling would splice
            # representations on this degraded path, and its mtime ETag
            # disagrees with the artifact path's. As on the stored branch, a
            # Range needs an If-Range naming this file's ETag to get a slice.
            response = artifact_response.temp_file_response(
                file_path,
                filename=filename,
                media_type=media_type,
                etag=etag,
                range_header=request.headers.get("range"),
                if_range=request.headers.get("if-range"),
                background=BackgroundTask(_cleanup_export, temp_dir),
            )
    except BaseException:
        _cleanup_export(temp_dir)
        raise

    # 8c. Audit log. user_id may be None for anonymous exports. Below the
    # precondition exits: a rebuild answering 412/304 must not record
    # `dataset.export`, matching the hit path.
    try:
        await _emit_export_audit(
            db,
            request,
            user_id=user_id,
            dataset_id=dataset_id,
            format=format,
            target_crs=target_crs,
            bbox=bbox,
            where=where,
        )
        await db.commit()
    except BaseException:
        _cleanup_export(temp_dir)
        raise
    return response
