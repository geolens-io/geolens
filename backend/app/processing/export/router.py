"""Export API endpoint: download datasets in various formats."""

import os
import re
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
from app.modules.auth.dependencies import get_optional_user
from app.modules.auth.permissions import get_effective_permissions
from app.core.dependencies import get_db
from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var
from app.platform.extensions import get_permission_extension, get_processing_port
from app.platform.http.ranges import (
    if_match_passes,
    if_none_match_matches,
    not_modified_response,
    parse_byte_range,
)
from app.platform.storage import get_storage
from app.processing.export import artifact_cache, artifact_response
from app.processing.export.ogr import (
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
)

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

# fix(#430): ceiling for full-table exports (by feature count) — an
# unbounded ogr2ogr writes an arbitrarily large temp file and holds a worker
# for the duration. Codex r8: a tautological filter (where=1=1) used to
# bypass the cap; oversized datasets now get a bounded COUNT with the
# caller's filters applied. BA-06's subprocess timeout bounds runtime
# regardless.
_MAX_EXPORT_FEATURES = 5_000_000


def _bare_satisfiable_range(request: Request, size: int) -> tuple[int, int] | None:
    """The resolved slice a bare Range (no If-Range) asks for, if it could be a 206.

    Parsed with the same function ``read_response`` uses, so a malformed,
    multi-range or unsatisfiable header — which the response ignores or
    rejects — never costs the URL-history listing (#1585 review r4).
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
    """Record one export download. user_id may be None for anonymous (EXP-01).

    fix(#1532): one function for both paths that transfer bytes (conversion
    and cache-hit) so they write the same row; only HEAD stays out of the log.
    fix(#1778): takes the id, not ``Identity`` — the conversion path calls
    this after rollback, and reading ``user.id`` from the expired ORM
    instance would refresh from a context with no greenlet. ``details.range``
    lets a range-probing client's rows be told apart from one full download.
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
    # The COMMIT is the caller's, deliberately: test_api_key_scope_875's
    # writing-GET tripwire reads the handler's source one level deep to
    # classify this route. A commit buried in a helper is invisible to it.


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

    Cap guard for oversized datasets (fix(#430), codex r8): validated
    WHERE (AST allowlist + column check), then an inner LIMIT stops the scan
    at cap+1 — strictly less work than the export it gates.
    """
    clauses: list[str] = []
    params: dict = {"limit": _MAX_EXPORT_FEATURES + 1}
    if where is not None:
        try:
            validate_where_clause(where, column_info)
            # Interpolate the canonical AST re-render, not the caller's raw
            # bytes — the count query never splices unvalidated user input.
            safe_where = canonical_where(where)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        # fix(#823): mirrors parquet.py — text() reads ":name" as a bind, so
        # a colon in a validated string literal (e.g. 'A:B', an ISO
        # timestamp) misparsed and 500'd. Escaped to text()'s literal-colon
        # form (\:); the real :limit/:minx binds below stay unescaped.
        safe_where = safe_where.replace(":", "\\:")
        clauses.append(f"({safe_where})")
    if bbox is not None and has_geometry:
        # fix(#905): crossing bboxes must count with the SAME predicate the
        # export runs (bbox_where_sql), not && alone — -spat's envelope
        # overlap can pass counts && would miss, so && errs toward 413.
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
    """fix(#1513): the HEAD half of the export route.

    Every status-deciding check already ran in the shared handler; the
    conversion itself is skipped, so an anonymous caller can't spend a
    worker per request. Can't promise 500/503 (only knowable by attempting
    the export) — pinned by
    ``test_head_cannot_promise_conversion_failure_status``.

    ``Accept-Ranges: bytes``: ranges are slices of ONE stored artifact
    (fix(#1532)), never spliced across conversions; the no-artifact path
    streams the conversion whole for the same reason, NOT through
    starlette's ``FileResponse``.

    Content-Length is deliberately absent (RFC 9110 9.3.2) since BUILDING
    an export to learn its length is the DoS foot-gun this branch avoids;
    GDAL retries with a ranged GET instead, at no extra cost.
    """
    filename, media_type = export_descriptor(dataset_title, format_key)
    response = Response(
        status_code=status.HTTP_200_OK,
        media_type=media_type,
        headers={
            "content-disposition": file_response_content_disposition(filename),
            # Lets a size-less HEAD work too: vsicurl learns the length from
            # the first range response (fix(#1532); see docstring above).
            "accept-ranges": "bytes",
        },
    )
    # Starlette defaults an empty body to `content-length: 0` — a WRONG
    # answer about the export's size, worse than the 405 this replaces
    # (a client would read it as an empty file). Strip it.
    response.raw_headers = [
        (key, value) for key, value in response.raw_headers if key != b"content-length"
    ]
    return response


# fix(#1513): HEAD alongside GET — FastAPI's APIRoute doesn't add it
# automatically, so this 405'd for HEAD, breaking GDAL/QGIS probes.
# include_in_schema=False: a derived route publishes nothing new.
@router.head("/{dataset_id}/export", include_in_schema=False)
@router.get(
    "/{dataset_id}/export",
    response_class=FileResponse,
    # fix(#1778): the handler raises 412 on both the
    # cache-hit and rebuild branches (If-Match no longer matching); the
    # published contract omitted it.
    responses={412: PRECONDITION_FAILED_RESPONSE},
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
    # IA-P1-01 (Phase 1069/1157 EXP-01): "export" is enforced only on the
    # authenticated branch (see body) — anonymous callers get
    # public+published datasets without a capability check (OGC/tiles parity).
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), CSV, GeoParquet,
    FlatGeobuf, and PMTiles formats. Optional CRS reprojection, spatial
    filtering, and attribute filtering. GeoParquet is always emitted in
    EPSG:4326 (OGC:CRS84). PMTiles renders zooms 0..N where N is extent-budgeted (ceiling 14).
    """
    # fix(#1778): the conversion's bound is what's LEFT of the
    # request clock after everything before it, not a fresh allowance — a
    # slow pre-conversion step (count scan, parquet plan) eats into it.
    #
    # fix(#1778): read from the REQUEST's start (stamped by
    # RequestLoggingMiddleware), not this function — `Depends` resolution
    # can block on a pool checkout a later clock would miss. Monotonic, so
    # an NTP step can't shorten or extend a running export.
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

    # 2. Visibility + permission check (branches on authenticated vs
    # anonymous). Function-level import: processing/ must not import
    # app.modules.catalog at module scope (test_layering.py).
    from app.modules.catalog.authorization import (
        check_dataset_access,
        check_dataset_access_or_anonymous,
        get_user_roles,
    )

    if user is None:
        # Anonymous export: enforce public+published gate via the anon-aware
        # helper (raises 404 to hide existence on denial), then a
        # defense-in-depth guard requiring public visibility.
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
        if dataset.record.visibility != "public":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anonymous export requires public dataset",
            )
    else:
        # Authenticated path: full RBAC visibility check + export capability.
        await check_dataset_access(db, dataset, dataset_id, user)
        user_roles = await get_user_roles(db, user)
        matrix = await get_effective_permissions(db)
        # Enforce via the permission extension (same path as
        # require_permission("export")) so a custom PermissionExtension's
        # policy applies here too; default reduces to role/matrix check.
        granted = await get_permission_extension().check_permission(
            db,
            user,
            "export",
            user_roles=user_roles,
            permission_matrix=matrix,
        )
        if not granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission: export",
            )

    # fix(#1778): read once, here, while the session that loaded it is still
    # in a transaction — `user` is the ORM instance on this session, and the
    # release below expires it along with every other instance.
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
        # PMTiles ignores -t_srs (always tiles in Web Mercator) and only
        # warns on stderr, which ogr2ogr exits 0 through — a caller asking
        # for another CRS would silently get EPSG:3857 back. Reject instead.
        if format == ExportFormat.pmtiles and target_crs.upper() != "EPSG:3857":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "PMTiles export is always rendered in EPSG:3857 "
                    "(Web Mercator); omit target_crs."
                ),
            )

    # 5. Reject raster/VRT: no tabular feature table. Keyed on record_type,
    # NOT geometry_type (a non-spatial TABLE dataset also has
    # geometry_type=None but IS CSV-exportable).
    if dataset.record.record_type in RASTER_FAMILY_RECORD_TYPES:
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

    # 6c. fix(#1532): the cached artifact for this selection, if usable.
    #
    # fix(#1532): resolved BEFORE the expensive work below —
    # `plan_parquet_export`'s bounded count ran on every range slice of an
    # existing artifact otherwise.
    #
    # fix(#1532): same reason, the ogr COUNT moved below
    # too. Safe by construction: an artifact exists only because an earlier
    # request with THIS key (table_name+title+tile_cache_version) passed
    # every gate already.
    selection = artifact_cache.selection_key(
        dataset_id=dataset_id,
        table_name=dataset.table_name,
        dataset_title=dataset.record.title,
        tile_cache_version=dataset.tile_cache_version,
        format_key=str(format),
        target_crs=target_crs,
        bbox=bbox,
        where=where,
    )
    # fix(#1532): filename/media_type are derived, not stored —
    # `export_descriptor` answers both from title+format without touching
    # the DB, and the HEAD branch below already calls it.
    cached_filename, cached_media_type = export_descriptor(
        dataset.record.title, str(format)
    )
    artifact = await artifact_cache.lookup(
        dataset_id,
        selection,
        filename=cached_filename,
        media_type=cached_media_type,
    )

    if artifact is not None:
        # fix(#1532): preconditions first, in RFC 9110 13.2.2
        # order (If-Match, If-None-Match, Range/If-Range), above the HEAD
        # return since a probe revalidates too.
        if not if_match_passes(request.headers.get("if-match"), artifact.etag):
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail="Export has changed since the version you hold",
                headers={"etag": artifact.etag},
            )
        if if_none_match_matches(request.headers.get("if-none-match"), artifact.etag):
            return not_modified_response(artifact.etag)
        # fix(#1532): the HEAD answer for a hit lives HERE, above
        # planning — left below, every cached parquet PROBE ran the planner,
        # which is the request a range-reading client makes first and most.
        if request.method == "HEAD":
            return artifact_response.head_response(artifact)
        # A cache hit still audits (bytes transfer); built only if the
        # response carries bytes, since `read_response` may 416.
        #
        # fix(#1532): a contested selection (>1 distinct
        # digest fresh under this key) answers ranges whole — overlapping
        # cold builders are the ordinary case, not rare.
        #
        # fix(#1585): so does a hit inside the first TTL after
        # this URL's bytes CHANGED, closing the resume-splice window; the
        # URL's prefix says whether other bytes were answered recently.
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

    # 6b. fix(#430): bound full-table exports (codex r8: a filter
    # must actually narrow the selection under the cap).
    #
    # fix(#1532): below the cache hit, same reason as r4 —
    # an artifact exists only because an earlier request already passed
    # this gate. Parquet is exempt: it owns its own bounded-count cap
    # against LIVE columns (Codex r10).
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

    # 6d. fix(#1513, codex P2 on #1522): remaining status-deciding checks,
    # hoisted above the HEAD return — previously inside
    # export_dataset()/export_parquet(), so HEAD lied with a 200.
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

    # 6d-b. fix(#1778): hand the pooled connection back before conversion —
    # `port.get_dataset` checked one out and nothing released it, and a
    # handful of concurrent exports could starve the pool otherwise (same
    # hazard as #1451 in tiles/router.py).
    #
    # Every value the handler needs is copied out FIRST: rollback expires
    # the ORM instances, so a later attribute read raises MissingGreenlet;
    # dropping the name makes that a NameError instead.
    dataset_title = dataset.record.title
    dataset_table = dataset.table_name
    dataset_columns = dataset.column_info
    dataset_has_geometry = dataset.geometry_type is not None
    dataset_extent = dataset.record.spatial_extent
    del dataset
    await db.rollback()

    # 6e. HEAD stops here — after every status-deciding gate, before the
    # conversion. No audit event: nothing exported.
    #
    # fix(#1532): with an artifact in hand, HEAD answers a real
    # Content-Length/ETag; without one, length is omitted (RFC 9110
    # 9.3.2) — BUILDING to learn the length is the DoS foot-gun this avoids.
    #
    # fix(#1532): preconditions run against NO validator on
    # the cold path, in RFC 9110 13.2.2 order (If-Match before
    # If-None-Match). HEAD refuses a specific If-Match rather than guessing
    # (`If-Match: *` still passes); GET proceeds to the build, which
    # evaluates both exactly.
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

    # 7. Run export. GeoParquet uses the pyarrow writer (no Arrow driver in
    # Debian's GDAL); every other format uses ogr2ogr.
    #
    # fix(#1532): stamped when conversion starts reading, not at
    # publication — ages the artifact from before build+upload+TTL, so it's
    # never older than that bound.
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
                # fix(#1778): bound the row stream by the edge window the same
                # way the ogr2ogr formats below are bounded.
                deadline=request_deadline,
            )
        else:
            pmtiles_maxzoom = None
            if format == ExportFormat.pmtiles:
                # fix(#1686): MAXZOOM is budgeted from the
                # dataset extent, not the request bbox — -spat selects
                # whole features without clipping.
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
                # fix(#885): a bbox only travels with geometry — csv is the
                # one ogr format a non-spatial dataset can reach, where
                # -spat is already a no-op.
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
    except ExportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Export failed",
        )
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export temporarily unavailable",
        )

    # fix(#435): the export file exists from here, but nothing owns it until
    # the response below attaches background cleanup.
    temp_dir = os.path.dirname(file_path)

    # 8. fix(#1532): publish before the response, so the next
    # range-probing request is a slice of THIS object.
    #
    # A store failure isn't a download failure (`store` returns None, not
    # raising). fix(#1532): if this request LOST the publish
    # race, `store` returns the incumbent instead, and THAT is served.
    #
    # fix(#1532): under the same cancellation ownership as the
    # audit step — CancelledError is a BaseException, so a disconnect
    # during hash/upload/sweep must not strand the conversion directory
    # forever (bounded by the four-hour orphan sweep).
    #
    # fix(#1532): hashed HERE, before `store`, since the
    # preconditions below must be answered from what was built whether or
    # not it's published.
    try:
        # fix(#1778): released again — the GeoParquet branch streams rows
        # through this session, so the hash/upload below would hold it
        # otherwise (no-op on the ogr2ogr branch).
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
    # fix(#1532): validator comes from the PUBLISHED artifact
    # when there is one — `store` recomputes the digest if handed None, so
    # a hash mismatch here vs there must not leave `etag` stale.
    if stored is not None:
        etag = stored.etag
    elif digest is not None:
        etag = artifact_cache.strong_etag(digest)
    else:
        etag = None

    # fix(#1532): the hit path's preconditions, evaluated here
    # too — without them a matching client got the whole export it already
    # had, and a stale If-Match got the new one instead of a refusal.
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

    # 8b. Build the response BEFORE the audit row, on both branches.
    #
    # fix(#1532): `read_response` can still 416 after
    # preconditions pass — building first releases the conversion directory
    # on that exit, and the audit row is written only once bytes exist.
    #
    # Cleanup rides the response (fix(#435)) — deleting eagerly looked
    # safe, but test_export_antimeridian caught a non-per-export temp dir
    # losing more than the export.
    try:
        if stored is not None:
            # may_serve_range=False: this request BUILT the artifact (or
            # lost the publish race), so it can't know what the client's
            # offsets were measured against — whole is the safe half of
            # RFC 9110 14.2. A matching If-Range or a byte-0 Range (a cold
            # GDAL open's first request) overrides it, honoured unless this
            # URL answered different bytes inside the last TTL (#1585 r1).
            leading_slice_ok = not stored.contested
            if leading_slice_ok and _leading_bare_range(request, stored.size):
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
                may_serve_range=False,
                leading_slice_ok=leading_slice_ok,
                background=BackgroundTask(_cleanup_export, temp_dir),
            )
        else:
            # 9. Serve the conversion itself, with background cleanup.
            # fix(#1435): touch mtime right before the
            # response — sweep_orphaned_exports reads it as recent activity,
            # resetting the age clock instead of freezing at generation end.
            try:
                os.utime(file_path, None)
            except OSError:
                pass  # best-effort freshness signal; must not block the download
            # fix(#1532): NOT a FileResponse — starlette's
            # own Range handling repeats #1532's splice on this degraded
            # path, and its mtime ETag disagreed with the artifact path's.
            #
            # fix(#1532): same rule as the stored branch — a
            # Range needs an If-Range naming this file's ETag to get a
            # slice; otherwise whole.
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

    # 8c. Audit log. user_id may be None for anonymous exports (EXP-01).
    #
    # fix(#1532): BELOW the precondition exits — a rebuild
    # answering 412/304 must not record `dataset.export`, matching the hit
    # path; the two paths must agree on what "this data left the building"
    # means.
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
