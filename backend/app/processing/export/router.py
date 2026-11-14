"""Export API endpoint: download datasets in various formats."""

import asyncio
import functools
import os
import re
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
import structlog
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
from app.platform.extensions import get_processing_port
from app.platform.http.ranges import (
    if_match_passes,
    if_none_match_matches,
    not_modified_response,
)
from app.platform.storage import get_storage
from app.processing.export import artifact_cache, artifact_response, selection
from app.processing.export.artifact_cache import ExportArtifact
from app.processing.export.ogr import FORMAT_MAP, PARQUET_MEDIA_TYPE, ExportError
from app.processing.export.schemas import ExportFormat
from app.processing.export.service import (
    export_descriptor,
    file_response_content_disposition,
)
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


def _head_export_response(
    dataset_title: str, format_key: str, *, gzipped: bool = False
) -> Response:
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
            **artifact_response.representation_headers(media_type, gzipped=gzipped),
        },
    )
    # Starlette defaults an empty body to `content-length: 0`, a wrong answer
    # about the export's size that a client would read as an empty file.
    response.raw_headers = [
        (key, value) for key, value in response.raw_headers if key != b"content-length"
    ]
    return response


def _request_deadline(request: Request) -> float:
    """When the edge proxy gives up on this request, on the monotonic clock.

    Runs from the request's start (stamped by RequestLoggingMiddleware), not
    the handler's, because `Depends` resolution can block on a pool checkout.
    Monotonic, so an NTP step can't shorten or extend a running export.
    """
    request_started = getattr(request.state, "started_at_monotonic", None)
    if request_started is None:
        request_started = time.monotonic()
    return request_started + EDGE_PROXY_READ_TIMEOUT_SECONDS


def _validated_bbox(
    dataset, *, format: ExportFormat, target_crs: str | None, bbox: str | None
) -> list[float] | None:
    """The parsed bbox, after refusing as 400 a request this dataset can't serve."""
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

    if target_crs is not None:
        if not re.fullmatch(r"EPSG:[0-9]{1,6}", target_crs, re.IGNORECASE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid target_crs: must match EPSG:<code> (e.g. EPSG:3857)",
            )
        # The pyarrow writer has no reprojection, so a conflicting target is
        # refused rather than silently emitting 4326.
        if format == ExportFormat.parquet and target_crs.upper() != "EPSG:4326":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GeoParquet export is emitted in EPSG:4326; omit target_crs.",
            )
        # ogr2ogr ignores -t_srs for PMTiles and exits 0, so another CRS would
        # silently come back as EPSG:3857.
        if format == ExportFormat.pmtiles and target_crs.upper() != "EPSG:3857":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "PMTiles export is always rendered in EPSG:3857 "
                    "(Web Mercator); omit target_crs."
                ),
            )

    # Keyed on record_type, not geometry_type: a non-spatial TABLE dataset also
    # has geometry_type=None but is CSV-exportable.
    if not capabilities(dataset.record.record_type).feature_table:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Raster datasets have no tabular feature data to export; "
                "use the raster tile/COG endpoints."
            ),
        )

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
    return bbox_parsed


async def _answer_from_artifact(
    request: Request,
    artifact: ExportArtifact,
    *,
    dataset_id: uuid.UUID,
    selection_key: str,
    gzipped: bool,
) -> tuple[Response, bool]:
    """Answer from a fresh cached artifact; the flag says whether bytes transfer.

    Preconditions run in RFC 9110 13.2.2 order, above the HEAD return since a
    probe revalidates too. HEAD answers before planning, so a cached parquet
    probe never runs the planner.
    """
    if not if_match_passes(request.headers.get("if-match"), artifact.etag):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Export has changed since the version you hold",
            headers={"etag": artifact.etag},
        )
    if artifact_response.revalidates(
        request.headers.get("if-none-match"), artifact.etag, gzipped=gzipped
    ):
        return artifact_response.not_modified(artifact.etag, gzipped=gzipped), False
    if request.method == "HEAD":
        return artifact_response.head_response(artifact, gzipped=gzipped), False
    may_serve_range = await selection.cached_range_allowed(
        artifact,
        dataset_id=dataset_id,
        selection=selection_key,
        range_header=request.headers.get("range"),
        if_range=request.headers.get("if-range"),
    )
    response = artifact_response.read_response(
        get_storage(),
        artifact,
        range_header=request.headers.get("range"),
        if_range=request.headers.get("if-range"),
        may_serve_range=may_serve_range,
        gzipped=gzipped,
    )
    return response, True


async def _answer_unbuilt(
    request: Request,
    *,
    dataset_id: uuid.UUID,
    chosen: selection.ArtifactSelection,
    bytes_follow_key: bool,
    gzipped: bool,
    dataset_title: str,
    format: ExportFormat,
) -> Response | None:
    """The answer for a request no fresh artifact serves; None when a GET must build.

    HEAD never builds. It answers from the stored artifact when that is the
    only bytes this URL holds, else without a length (RFC 9110 9.3.2).
    """
    if request.method == "HEAD" and bytes_follow_key:
        settled = await artifact_cache.settled_artifact(
            dataset_id,
            chosen.key,
            filename=chosen.filename,
            media_type=chosen.media_type,
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

    # Preconditions against no validator, If-Match first. HEAD refuses a
    # specific If-Match rather than guessing (`If-Match: *` still passes); a
    # wildcard If-None-Match answers 304 for both verbs, for GET before building.
    if_match_ok_unbuilt = if_match_passes(request.headers.get("if-match"), None)
    if request.method == "HEAD" and not if_match_ok_unbuilt:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Export has changed since the version you hold",
        )
    if if_match_ok_unbuilt and artifact_response.revalidates(
        request.headers.get("if-none-match"), None, gzipped=gzipped
    ):
        return artifact_response.not_modified(None, gzipped=gzipped)
    if request.method == "HEAD":
        return _head_export_response(dataset_title, format, gzipped=gzipped)
    return None


async def _convert(
    db: AsyncSession,
    source: selection.ExportSource,
    format: ExportFormat,
    *,
    dataset_id: uuid.UUID,
    **options,
) -> tuple[str, str, str, float]:
    """Run the conversion in a slot; returns its file, name, type and start time.

    The start time is when conversion begins reading, not publication, so the
    artifact ages from before build+upload+TTL.
    """
    if _conversion_slots.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Export service busy, please retry",
            headers={"Retry-After": "5", "Cache-Control": "no-store"},
        )
    await _conversion_slots.acquire()
    snapshot_at = time.time()
    try:
        file_path, filename, media_type = await selection.convert(
            db, source, format, **options
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
    return file_path, filename, media_type, snapshot_at


async def _publish_conversion(
    db: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    selection_key: str,
    file_path: str,
    filename: str,
    media_type: str,
    snapshot_at: float,
) -> tuple[ExportArtifact | None, str | None]:
    """Publish the conversion so the next range request slices it; returns it and its ETag.

    A store failure isn't a download failure: `store` returns None, or the
    incumbent when this request lost the publish race.
    """
    # The GeoParquet branch streams rows through this session, which the hash
    # and upload would otherwise hold (a no-op on the ogr2ogr branch).
    await db.rollback()
    try:
        digest, size = await artifact_cache.digest_and_size(file_path)
    except Exception:  # broad: an unhashable file still downloads
        digest, size = None, None
    stored = await artifact_cache.store(
        dataset_id,
        selection_key,
        file_path=file_path,
        filename=filename,
        media_type=media_type,
        digest=digest,
        size=size,
        snapshot_at=snapshot_at,
    )
    return stored, selection.built_etag(stored, digest)


def _built_not_modified(
    request: Request, etag: str | None, *, gzipped: bool, temp_dir: str
) -> Response | None:
    """The hit path's preconditions against a fresh build, releasing it on either exit.

    A matching client isn't sent an export it already has, and a stale If-Match is refused.
    """
    if not if_match_passes(request.headers.get("if-match"), etag):
        _cleanup_export(temp_dir)
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Export has changed since the version you hold",
            headers={"etag": etag} if etag is not None else None,
        )
    if artifact_response.revalidates(
        request.headers.get("if-none-match"), etag, gzipped=gzipped
    ):
        _cleanup_export(temp_dir)
        return artifact_response.not_modified(etag, gzipped=gzipped)
    return None


# HEAD alongside GET, which FastAPI's APIRoute doesn't add automatically;
# GDAL/QGIS probe with it. include_in_schema=False: a derived route publishes
# nothing new.
@router.head(
    "/{dataset_id}/export", include_in_schema=False, summary="Export a dataset"
)
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
    summary="Export a dataset",
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
    xy: bool = Query(
        False,
        description=(
            "CSV only: add WGS 84 longitude and latitude columns after the "
            "geometry, filled for a point or a one-point multipoint and empty "
            "otherwise. Ignored for other formats, for layers that are not "
            "point or multipoint, and for a dataset that already has a "
            "longitude or latitude column."
        ),
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
    request_deadline = _request_deadline(request)
    port = get_processing_port()
    data_schema = tenant_data_schema(current_tenant_var.get())
    dataset = await port.get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Function-level import: processing/ must not import app.modules.catalog at
    # module scope (test_layering.py).
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
    bbox_parsed = _validated_bbox(
        dataset, format=format, target_crs=target_crs, bbox=bbox
    )
    with_xy = selection.wants_xy(xy, format, dataset.geometry_type, dataset.column_info)

    # Looked up before the bounded counts and the parquet planner, which would
    # otherwise run on every range slice of an existing artifact. An artifact
    # exists only because an earlier request with this key passed every gate.
    chosen = selection.artifact_selection(
        dataset,
        dataset_id=dataset_id,
        format=format,
        target_crs=target_crs,
        bbox=bbox,
        where=where,
        exporter_version=request.app.version,
        xy=with_xy,
    )
    gzipped = artifact_response.client_offers_gzip(request, chosen.media_type)
    held_before_build: set[str] = set()
    artifact = await artifact_cache.lookup(
        dataset_id,
        chosen.key,
        filename=chosen.filename,
        media_type=chosen.media_type,
        seen_digests=held_before_build,
    )
    audit = functools.partial(
        _emit_export_audit,
        db,
        request,
        user_id=user_id,
        dataset_id=dataset_id,
        format=format,
        target_crs=target_crs,
        bbox=bbox,
        where=where,
    )

    if artifact is not None:
        response, transfers_bytes = await _answer_from_artifact(
            request,
            artifact,
            dataset_id=dataset_id,
            selection_key=chosen.key,
            gzipped=gzipped,
        )
        if transfers_bytes:
            await audit()
            await db.commit()
        return response

    # Remaining status-deciding checks, above the HEAD return so HEAD does not
    # answer 200 for a request the GET refuses.
    try:
        parquet_plan = await selection.check_selection(
            db,
            dataset,
            format=format,
            bbox=bbox_parsed,
            where=where,
            schema=data_schema,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except selection.SelectionTooLargeError as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(e),
        )

    # Hand the pooled connection back before conversion. Rollback expires the
    # ORM instances, so every value needed later is copied out first; dropping
    # the name turns a stray read into a NameError rather than MissingGreenlet.
    source = selection.ExportSource.of(dataset)
    bytes_follow_key = selection.bytes_follow_key(
        dataset, where=where, parquet_plan=parquet_plan
    )
    del dataset
    await db.rollback()

    unbuilt = await _answer_unbuilt(
        request,
        dataset_id=dataset_id,
        chosen=chosen,
        bytes_follow_key=bytes_follow_key,
        gzipped=gzipped,
        dataset_title=source.title,
        format=format,
    )
    if unbuilt is not None:
        return unbuilt

    file_path, filename, media_type, snapshot_at = await _convert(
        db,
        source,
        format,
        dataset_id=dataset_id,
        schema=data_schema,
        target_crs=target_crs,
        bbox=bbox_parsed,
        where=where,
        parquet_plan=parquet_plan,
        ordered=bytes_follow_key,
        xy=with_xy,
        deadline=request_deadline,
    )
    # Nothing owns the export file until the response attaches background
    # cleanup, and a disconnect's CancelledError is a BaseException.
    temp_dir = os.path.dirname(file_path)
    try:
        stored, etag = await _publish_conversion(
            db,
            dataset_id=dataset_id,
            selection_key=chosen.key,
            file_path=file_path,
            filename=filename,
            media_type=media_type,
            snapshot_at=snapshot_at,
        )
    except BaseException:
        _cleanup_export(temp_dir)
        raise
    not_modified = _built_not_modified(
        request, etag, gzipped=gzipped, temp_dir=temp_dir
    )
    if not_modified is not None:
        return not_modified

    # Built before the audit row, so a 416 from `read_response` releases the
    # conversion and records nothing. Cleanup rides the response: eager deletion
    # can remove more than the export when the temp dir isn't per-export.
    try:
        if stored is not None:
            may_serve_range, leading_slice_ok = await selection.built_range_policy(
                stored,
                dataset_id=dataset_id,
                selection=chosen.key,
                bytes_follow_key=bytes_follow_key,
                held_before_build=held_before_build,
                range_header=request.headers.get("range"),
                if_range=request.headers.get("if-range"),
            )
            response = artifact_response.read_response(
                get_storage(),
                stored,
                range_header=request.headers.get("range"),
                if_range=request.headers.get("if-range"),
                may_serve_range=may_serve_range,
                leading_slice_ok=leading_slice_ok,
                gzipped=gzipped,
                background=BackgroundTask(_cleanup_export, temp_dir),
            )
        else:
            # sweep_orphaned_exports reads mtime as recent activity, so the age
            # clock restarts here rather than at the end of generation.
            try:
                os.utime(file_path, None)
            except OSError:
                pass  # best-effort freshness signal; must not block the download
            # Not a FileResponse: starlette's own Range handling would splice
            # representations on this path, and its mtime ETag disagrees with the
            # artifact path's.
            response = artifact_response.temp_file_response(
                file_path,
                filename=filename,
                media_type=media_type,
                etag=etag,
                range_header=request.headers.get("range"),
                if_range=request.headers.get("if-range"),
                gzipped=gzipped,
                background=BackgroundTask(_cleanup_export, temp_dir),
            )
    except BaseException:
        _cleanup_export(temp_dir)
        raise

    # Below the precondition exits: a rebuild answering 412/304 records no
    # `dataset.export`, matching the hit path.
    try:
        await audit()
        await db.commit()
    except BaseException:
        _cleanup_export(temp_dir)
        raise
    return response
