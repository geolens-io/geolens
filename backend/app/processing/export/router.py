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

# fix(#430 BA-08): ceiling for full-table exports (by feature count). An
# unbounded ogr2ogr over the whole table writes an arbitrarily large temp file
# and holds a worker for the full duration; require callers to narrow very
# large datasets with bbox/where. Codex r8: a filter must actually narrow the
# selection — a merely-present tautological filter (e.g. where=1=1) previously
# bypassed the cap entirely, so oversized datasets now get a bounded COUNT with
# the caller's filters applied. BA-06's subprocess timeout bounds runtime
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

    fix(#1532): one function because there are two paths that transfer bytes
    now — the conversion path and the cache-hit path — and they must write the
    same row. A cached read is still a download; only HEAD, which transfers
    nothing, stays out of the log.

    fix(#1778): takes the id, not the ``Identity``. The conversion path calls
    this after the session has been rolled back to release its pooled
    connection, and the request's ``user`` is a live ORM instance on that
    session, so reading ``user.id`` here would be an expired-attribute
    refresh from a context with no greenlet.

    ``details.range`` distinguishes a tile-sized read from a full download when
    the log is read back. A range-probing client emits a row per read, which is
    a deliberate volume cost taken because the alternative is an audit blind
    spot: a caller could otherwise pull a whole export in ranges and appear
    once.
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
    # The COMMIT is the caller's, on the handler, deliberately: the writing-GET
    # tripwire in test_api_key_scope_875 reads the handler's source one level
    # deep and classifies this route as "commits an audit row for the read". A
    # commit buried in a helper is invisible to it, and the route silently
    # dropped out of the classification while still writing.


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

    Cap guard for oversized datasets (fix(#430 BA-08), codex r8). The WHERE
    fragment is validated (AST allowlist + column check) before interpolation —
    the same trust boundary as the ogr2ogr -where path that executes the same
    fragment right after — and the inner LIMIT stops the scan at cap+1 rows, so
    this check does strictly less work than the export it gates.
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
        # fix(#823): mirror parquet.py — text() reads ":name" as a bind param,
        # so a colon inside a validated string literal (e.g. name = 'A:B' or an
        # ISO timestamp) misparsed as an unbound parameter and 500'd. Escape to
        # text()'s literal-colon form (\:); the real :limit/:minx binds below
        # are added separately and stay unescaped.
        safe_where = safe_where.replace(":", "\\:")
        clauses.append(f"({safe_where})")
    if bbox is not None and has_geometry:
        # fix(#905): a west>east (antimeridian-crossing) bbox used to skip
        # this clause entirely and count the dataset unfiltered, so a narrow
        # Pacific AOI over an oversized dataset 413'd. Count each branch with
        # the predicate its export actually executes:
        #
        # - crossing: bbox_where_sql, the exact split predicate the ogr2ogr
        #   path runs via -where (and parquet.py runs verbatim), so count and
        #   export select identical rows. Measured (EXPLAIN ANALYZE, 5M-row
        #   point table, gist index): both halves of the OR run as bitmap
        #   index scans on geom_4326 (3.5 ms) vs 509 ms for the unfiltered
        #   cap+1 seq scan — the docstring's "strictly less work" holds.
        # - ordinary: envelope && only (superset of exact intersects), NOT
        #   bbox_where_sql — the export runs ogr2ogr -spat, whose GDAL
        #   contract permits envelope-overlap false positives, so an exact
        #   ST_Intersects count could pass ≤cap while -spat exports more
        #   (fix(#905 codex r1)). && errs toward 413, the safe direction.
        #
        # Non-spatial datasets still skip the clause: ogr2ogr -spat is a
        # no-op on a layer with no geometry, so the unfiltered count matches
        # what the export would actually emit.
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

    Every check that can decide the status WITHOUT producing bytes has already
    run in the shared handler above: access control, the export capability,
    bbox/CRS validation, the raster and geometry gates, the feature-count
    ceiling, filter validation, and for parquet the live-column check and the
    bounded count. The conversion itself is skipped, which is the whole point:
    a HEAD that ran ogr2ogr and discarded the bytes would hand any anonymous
    caller a way to spend a worker per request on a public dataset.

    Two statuses HEAD therefore cannot promise, and does not claim to: 500
    (ogr2ogr or the parquet build fails) and 503 (the staging volume is
    unavailable). Both are knowable only by attempting the export, so a HEAD
    answers 200 for a request whose GET would fail that way. That limit is
    deliberate and pinned by
    ``test_head_cannot_promise_conversion_failure_status``; everything else a
    GET can reject, HEAD rejects identically.

    An earlier revision claimed full parity while filter validation still lived
    inside ``export_dataset``/``export_parquet``, below the HEAD return, so a
    bad filter got 200 from HEAD and 400 from the GET (codex P2 on #1522).
    Those checks are hoisted now; the parity claim above is the narrower one
    the code actually supports.

    ``Accept-Ranges: bytes`` says the endpoint serves byte ranges, and since
    fix(#1532) it also says they are slices of ONE stored artifact rather than of
    a sequence of fresh conversions. This docstring described the old behaviour
    as current for one revision too long; what follows is what the route does
    now.

    A range is served from the cached artifact when one exists, and a request
    that had to build the representation answers 200 with the whole of it
    instead — so no two responses are ever parts of different files presented as
    parts of one. The path with no artifact at all (a storage outage, a contested
    selection, an exhausted budget) streams the conversion whole for the same
    reason, deliberately NOT through starlette's ``FileResponse``, which parses
    ``Range`` itself.

    The header stays and is now backed by an actual 206. GDAL ranges because a
    size-less HEAD gives it no length, not because it read this header.

    Content-Length is deliberately absent. An export's length is knowable only
    after the conversion, and RFC 9110 section 9.3.2 lets a HEAD omit header
    fields "for which a value is determined only while generating the
    content". Measured against GDAL 3.13.0 ``/vsicurl/``, omitting it costs
    nothing: HEAD without a length logs "HEAD did not provide file size.
    Retrying with limited range GET", and the 206's Content-Range supplies the
    size — same request count as a HEAD that carried Content-Length, and one
    fewer full-body GET than the 405 this replaces.
    """
    filename, media_type = export_descriptor(dataset_title, format_key)
    response = Response(
        status_code=status.HTTP_200_OK,
        media_type=media_type,
        headers={
            "content-disposition": file_response_content_disposition(filename),
            # The GET this describes serves 206 byte ranges off the cached
            # artifact, and this is also what lets a size-less HEAD work:
            # vsicurl learns the length from the first range response. On the
            # cold path it promises range SERVICE — the first GET builds and
            # answers whole — see the docstring and fix(#1532).
            "accept-ranges": "bytes",
        },
    )
    # Starlette gives every non-204 response a Content-Length from its body,
    # which for an empty body is `content-length: 0` — a WRONG answer about the
    # export's size rather than no answer, and strictly worse than the 405 it
    # replaces: a client would read the export as an empty file. Strip it.
    response.raw_headers = [
        (key, value) for key, value in response.raw_headers if key != b"content-length"
    ]
    return response


# fix(#1513): HEAD alongside GET. FastAPI's APIRoute does not add it the way
# starlette's plain Route does, so this answered `405 allow: GET` — which RFC
# 9110 forbids for a GET-able resource, and which breaks every client that
# probes before downloading (GDAL/QGIS `/vsicurl/`, resumable downloaders,
# link checkers). `_register_standards_head_routes` in app/api/main.py closes
# the same gap for the standards surface, but by CLONING the route, which
# would run the full conversion here; this route needs a handler that stops
# before it, so it is registered explicitly instead.
#
# include_in_schema=False for the reason `_clone_api_route` gives: a derived
# route documents nothing the canonical one does not, and publishing it would
# churn both SDKs and the CLI.
@router.head("/{dataset_id}/export", include_in_schema=False)
@router.get("/{dataset_id}/export", response_class=FileResponse)
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
    # IA-P1-01 (Phase 1069, updated Phase 1157 EXP-01): the "export" capability
    # is now enforced on the authenticated branch only (see handler body).
    # Anonymous callers are allowed to export public+published datasets without
    # a capability check — matching the OGC/tiles anonymous-access contract.
    # Authenticated callers still require the "export" capability via the
    # per-role matrix check below.
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), CSV, GeoParquet,
    FlatGeobuf, and PMTiles formats. Optional CRS reprojection, spatial
    filtering, and attribute filtering. GeoParquet is always emitted in
    EPSG:4326 (OGC:CRS84). PMTiles renders zooms 0..N where N is extent-budgeted (ceiling 14).
    """
    # fix(#1778 codex r1): the request's own clock, stamped before anything
    # else runs. Everything this handler does between here and the conversion
    # spends part of the edge proxy's window, so the conversion's bound has to
    # be what is LEFT of it rather than an allowance computed from scratch.
    # An unindexed `_count_selected_features` scan, or a parquet plan over a
    # wide table, can eat a minute here; a warm cold path costs milliseconds,
    # and the conversion should get that time back.
    #
    # Monotonic, not wall clock: a clock step (NTP, a suspend) must not shorten
    # or extend a running export.
    request_deadline = time.monotonic() + EDGE_PROXY_READ_TIMEOUT_SECONDS

    port = get_processing_port()
    data_schema = tenant_data_schema(current_tenant_var.get())
    # 1. Fetch dataset
    dataset = await port.get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # 2. Visibility + permission check (branches on authenticated vs anonymous).
    # Function-level import: processing/ must not import app.modules.catalog at
    # module scope (Phase 225 PROCESS-02/04 layering guard — test_layering.py).
    # Mirrors the existing parse_bbox import below.
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
        # Enforce the export capability through the permission extension — the
        # same path as require_permission("export") — so deployments that
        # register a custom PermissionExtension apply their policy here too. The
        # default extension reduces to the role/matrix check, so OSS behavior is
        # unchanged. (Codex review: export/router.py:92.)
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

    # fix(#1778): read once, here, while the session that loaded it is still in
    # a transaction. `user` is the concrete User ORM instance on this request's
    # session, and the release below expires it along with every other
    # instance.
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
        # The PMTiles driver ignores -t_srs outright (it always tiles in Web
        # Mercator) and only warns on stderr, which ogr2ogr exits 0 through --
        # so a caller asking for some other CRS would silently get EPSG:3857
        # back with no signal anything was ignored. Reject the mismatch
        # instead, same reasoning as GeoParquet above.
        if format == ExportFormat.pmtiles and target_crs.upper() != "EPSG:3857":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "PMTiles export is always rendered in EPSG:3857 "
                    "(Web Mercator); omit target_crs."
                ),
            )

    # 5. Reject raster/VRT datasets: they have no tabular feature table.
    # Key on record_type (loaded via joinedload(Dataset.record) in
    # get_dataset), NOT geometry_type — a legitimate non-spatial TABLE
    # dataset (record_type="table") also has geometry_type=None but IS a
    # real CSV-exportable table and must NOT be blocked. A raster/VRT
    # dataset has a synthetic table_name with no backing table, so letting
    # csv proceed would hit ogr2ogr on a nonexistent table -> raw 500.
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

    # 6c. fix(#1532): the cached artifact this selection would be served from,
    # if there is a usable one.
    #
    # fix(#1532 review r4): resolved BEFORE the expensive work below, not after.
    # `plan_parquet_export` introspects the live table and runs a bounded count
    # up to a million rows, and it ran on every request including every range
    # slice of an artifact that already existed — so a range-probing client
    # repeated that scan per slice and kept most of the load this cache exists
    # to remove.
    #
    # fix(#1532 review, internal): the ogr path's bounded COUNT moved below this
    # for the same reason. `_count_selected_features` scans to 5,000,001 rows
    # with the caller's WHERE on an unindexed column, and it ran on every hit
    # too. The UNFILTERED 413 stays above, because it is a dataset-level fact
    # that costs nothing to check and HEAD should keep answering it.
    #
    # Skipping those gates on a hit is safe by construction rather than by
    # argument: an artifact only exists because an earlier request with THIS
    # key passed every one of them and produced bytes. The key carries
    # table_name, the dataset title and tile_cache_version, so a schema change,
    # a replace or a feature edit all move it — a stored artifact cannot
    # outlive the validation that produced it.
    #
    # The gates above stay above: access control, the raster and geometry
    # checks, bbox and CRS parsing. Those decide whether the CALLER may have
    # this representation, which a previous request cannot answer on their
    # behalf.
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
    # fix(#1532 review r3): filename and media_type are derived, not stored.
    # `export_descriptor` answers both from the title and the format without
    # touching the database or the filesystem, and the HEAD branch below already
    # calls it — persisting them alongside the artifact would have been a second
    # copy of a value cheaper to recompute than to keep consistent.
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
        # fix(#1532 review r9): preconditions first, in the order RFC 9110
        # section 13.2.2 fixes — If-Match, then If-None-Match, then Range and
        # If-Range. The artifact publishes a strong ETag, so a client CAN
        # revalidate it, and until now one that did was answered with the whole
        # export it already had. Both verbs, and above the HEAD return because
        # a probe revalidates too.
        #
        # The same evaluation the COG route settled over seven rounds of #1540,
        # through the shared helpers rather than a second copy.
        if not if_match_passes(request.headers.get("if-match"), artifact.etag):
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail="Export has changed since the version you hold",
                headers={"etag": artifact.etag},
            )
        if if_none_match_matches(request.headers.get("if-none-match"), artifact.etag):
            return not_modified_response(artifact.etag)
        # fix(#1532 review r4): the HEAD answer for a hit lives HERE, above the
        # planning, not below it. Left below, every cached parquet PROBE ran the
        # planner — which is the request a range-reading client makes first and
        # most often.
        if request.method == "HEAD":
            return artifact_response.head_response(artifact)
        # A cache hit still audits: bytes are being transferred, and the audit
        # row is what makes a range read distinguishable from a full download
        # when the log is read back.
        #
        # fix(#1532 review, internal): built first, emitted only if the response
        # actually carries bytes. `read_response` may raise a 416 for a range
        # that names nothing, and a `dataset.export` row for a refused request
        # records a download that did not happen — the same reason HEAD is out
        # of the log.
        # fix(#1532 review, internal): a contested selection — more than one
        # distinct set of bytes fresh under this key — answers ranges with the
        # whole representation. Two overlapping cold builders is the ordinary
        # case, not a rare one, and a client reading in slices can otherwise be
        # flipped from one to the other mid-sequence.
        #
        # fix(#1532) follow-up (#1585 review r3/r4): and so does a hit inside
        # the first TTL after this URL's bytes CHANGED. A client that read a
        # block of the earlier representation and comes back for the next one
        # lands here, on the new artifact, and a 206 would splice the two. The
        # URL's own prefix says whether other bytes were answered within the
        # last TTL; consulted only for a bare, satisfiable Range — the request
        # that could receive a 206.
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

    # 6b. fix(#430 BA-08): bound full-table exports. Codex r8: for oversized
    # datasets a filter only passes if it actually narrows the selection under
    # the cap (bounded filtered COUNT), closing the where=1=1 bypass.
    #
    # fix(#1532 review, internal): below the cache hit, not above it.
    # `_count_selected_features` scans to 5,000,001 rows with the caller's WHERE
    # on an unindexed column, and it ran on every hit — every range slice, every
    # HEAD — for an artifact that already existed. Same argument review r4 made
    # about the parquet planner, and the same justification: an artifact exists
    # only because an earlier request with THIS key passed this gate and produced
    # bytes, and the key carries table_name, the title and tile_cache_version, so
    # a replace or a feature edit moves it. The whole block moves, the unfiltered
    # branch included: it is cheap, but a cache hit is proof it already passed.
    #
    # Parquet is exempt here: export_parquet() runs its own bounded-count cap
    # against the LIVE-introspected columns. Running this guard for parquet too
    # would validate the filter against the nullable dataset.column_info and
    # wrongly reject a valid filter on a metadata-less oversized dataset before
    # the parquet path's introspection can run (Codex r10).
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

    # 6d. fix(#1513, codex P2 on #1522): the remaining checks that decide the
    # STATUS, hoisted above the HEAD return. These used to live inside
    # export_dataset()/export_parquet(), i.e. below it, so HEAD answered 200
    # for a filter GET rejects with 400 and for a parquet selection GET rejects
    # with 413. A probing client accepted that HEAD and then failed its range
    # GET, which is worse than the 405 this route replaced: the 405 did not
    # lie. Validation only — running the conversion to learn a status is the
    # denial-of-service foot-gun the HEAD branch exists to avoid.
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

    # 6d-b. fix(#1778): hand the pooled connection back before the conversion.
    #
    # `get_db` yields one session for the whole request and nothing released
    # it, so the `port.get_dataset` above checked a connection out and this
    # handler then kept it across ogr2ogr, the hash and the object-store
    # upload. The API process has `db_pool_size` + `db_max_overflow`
    # connections in total, and export is reachable anonymously for a
    # public+published dataset, so a handful of concurrent exports could
    # starve every other request in the process on `pool_timeout`. Same fix
    # and same reasoning as fix(#1451 codex P1) in processing/tiles/router.py,
    # which had already recognised the hazard for a query that holds the
    # connection roughly a thousand times less long. Everything above is
    # read-only, so the rollback discards nothing.
    #
    # Every value the rest of the handler needs is copied out FIRST. A
    # rollback expires the ORM instances, so an attribute read afterwards
    # would go back to the database from a context with no greenlet and raise
    # MissingGreenlet; dropping the name makes that a NameError while the code
    # is being written rather than a 500 in production.
    dataset_title = dataset.record.title
    dataset_table = dataset.table_name
    dataset_columns = dataset.column_info
    dataset_has_geometry = dataset.geometry_type is not None
    dataset_extent = dataset.record.spatial_extent
    del dataset
    await db.rollback()

    # 6e. HEAD stops here — after every gate that decides the status, before
    # the conversion that decides the bytes. No audit event either: nothing was
    # exported, and a `dataset.export` row for a probe would misreport who
    # downloaded what.
    #
    # fix(#1532): with an artifact in hand, HEAD answers a real Content-Length
    # and the artifact's ETag. Without one it answers as before, length omitted
    # under RFC 9110 section 9.3.2 — deliberately, because BUILDING an export to
    # learn its length is the denial-of-service foot-gun this branch exists to
    # avoid, and a size-less HEAD is a case GDAL already handles (it retries
    # with a limited range GET). So a first open costs one conversion on the
    # range GET, and every open after that gets its length for free.
    # fix(#1532 review r21): the preconditions, against NO validator, on the
    # cold path. Nothing has been built, so there is no entity-tag — but the
    # resource still has a current representation (a GET is about to produce
    # one), and whether a conditional request is honoured must not depend on
    # whether the cache happens to be warm.
    #
    # `If-None-Match: *` is therefore a 304 for BOTH verbs, and for GET it is
    # answered before the conversion: the client has said it holds some
    # representation and wants bytes only if there is none, so building a
    # multi-gigabyte export to tell it to keep what it has is work the answer
    # never needed. A specific If-None-Match tag cannot match no validator and
    # proceeds — to the build, which then evaluates it exactly.
    #
    # fix(#1532 review r22): in the ORDER section 13.2.2 fixes — If-Match is
    # authoritative before If-None-Match, so a request carrying a stale
    # specific If-Match beside `If-None-Match: *` is a 412, never a 304. HEAD
    # holds no validator and will not build one, so a specific If-Match tag,
    # which nothing here can verify, is refused rather than guessed — the call
    # the shared helpers already make for a COG row with no stored digest, and
    # the one the rebuild path makes when the file could not be hashed.
    # (`If-Match: *` passes: the representation exists.) GET takes the
    # wildcard shortcut only when If-Match cannot fail without a validator;
    # otherwise it proceeds to the build, which answers both exactly and in
    # order.
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

    # 7. Run export. GeoParquet goes through the pyarrow writer (the Debian GDAL
    # build has no Arrow driver); all other formats use the ogr2ogr path.
    #
    # fix(#1532 review r25): the moment the conversion is about to read the
    # data, carried into publication as the artifact's stamp. A mutation that
    # misses `tile_cache_version` and lands DURING a long conversion makes an
    # artifact stale at birth; stamping publication time let it age from after
    # that, so it served for the rest of the build plus the upload plus the
    # TTL. Stamped from here, the cache's ceiling on "publication after stamp"
    # bounds build plus upload, and the data behind a served artifact is never
    # older than TTL plus that ceiling.
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
            )
        else:
            pmtiles_maxzoom = None
            if format == ExportFormat.pmtiles:
                # fix(#1686 codex r1): the PMTiles writer materializes the
                # whole pyramid eagerly (unlike the on-demand tile endpoint),
                # so MAXZOOM is budgeted from the dataset extent.
                # fix(#1686 codex r3): the request bbox must NOT narrow this
                # budget — -spat SELECTS whole features without clipping
                # (ogr.py), so a tiny bbox over a world-spanning polygon still
                # renders tiles across the polygon's full extent. The dataset
                # extent bounds every selectable feature, so it is the sound
                # ceiling; a per-request ST_Extent of the selected rows is the
                # upgrade path if city slices of world datasets need deeper
                # zooms than this yields.
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
                # fix(#885): an antimeridian bbox is filtered by a server-side
                # geom_4326 predicate, so a bbox only travels with a dataset that
                # HAS geometry. csv is the one ogr format a non-spatial dataset
                # can reach (gate 6 blocks the rest), and -spat was already a
                # no-op there ("Cannot set spatial filter: no geometry field").
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

    # fix(#435): the export file exists from here on, but nothing owns it until the
    # FileResponse below attaches the background cleanup. An audit or commit failure
    # in between used to strand the directory on the staging volume.
    temp_dir = os.path.dirname(file_path)

    # 8. fix(#1532): publish what was just built, so the next request — which
    # for a range-probing client is moments away — is a slice of THIS object
    # rather than a fresh conversion. Storing before the response is what makes
    # the artifact available to the next probe; storing after would leave the
    # burst of ranges that follows a HEAD racing the write that serves them.
    #
    # A store failure is not a download failure: the file is in hand and the
    # response below still works, which is why `store` returns None instead of
    # raising. fix(#1532 review r29): and when this request LOST the publish
    # race, `store` returns the incumbent artifact instead, and that is what is
    # served — not this request's own bytes — so a client interrupted here and
    # resuming with a bare Range lands on the same representation.
    # fix(#1532 review r3): publication runs under the same cancellation
    # ownership as the audit step above. `store` catches Exception, and a
    # CancelledError is a BaseException — a client disconnect or a worker
    # shutdown during the hash, the upload or the sweep therefore propagates
    # through an await that sits OUTSIDE any cleanup, stranding a conversion
    # directory that can be multiple gigabytes until the four-hour orphan sweep.
    # Repeated cancels fill the staging volume. Same distinction fix(#1550)
    # turned on: CancelledError is not an Exception.
    #
    # fix(#1532 review r18): hashed HERE, before `store`, and handed in. The
    # digest is the response's validator, and the preconditions below have to
    # be answered from what was built whether or not it gets published — a full
    # store, a lost race with another publisher, an outage. Evaluating them only
    # on the stored branch (r10) left the fallback streaming a byte-identical
    # export to a client whose `If-None-Match` named it, and ignoring a stale
    # `If-Match` instead of refusing. A hash that fails is treated the way a
    # store that fails is: the download still goes out, with no validator, and
    # a specific tag against no validator is refused rather than guessed — the
    # same call the shared helpers make for a COG row with no stored digest.
    try:
        # fix(#1778): released again, for the same reason and in the same
        # shape. The GeoParquet branch streams its rows through this session,
        # so it checks a connection back out; without this the hash and the
        # upload below would hold it exactly as the conversion used to. A
        # no-op on the ogr2ogr branch, which opens no transaction of its own,
        # and inside this try so a rollback that fails on a dead connection
        # cleans the conversion directory up rather than stranding it. The
        # audit row at the end re-acquires.
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
    # fix(#1532 review r20): the validator comes from the PUBLISHED artifact
    # when there is one. `store` recomputes the digest if it was handed None, so
    # a hash that failed here and succeeded there left `etag` None beside a
    # response advertising `stored.etag` — a matching If-Match was refused and
    # a matching If-None-Match transferred the export it named.
    if stored is not None:
        etag = stored.etag
    elif digest is not None:
        etag = artifact_cache.strong_etag(digest)
    else:
        etag = None

    # fix(#1532 review r10): the same preconditions the hit path evaluates.
    # They were only on that branch, so a client whose validator matched what
    # this request just built — the ordinary case, since the export is
    # byte-deterministic for unchanged data — was handed the whole export it
    # already had, and a stale If-Match got the new representation instead of a
    # refusal. A rebuild is exactly when a client's version claim matters most.
    # r18: on BOTH branches, from the digest of the built file.
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
    # fix(#1532 review r17): `read_response` can still exit without a
    # response after the preconditions above have passed — a Range that names
    # no byte, resumed with an `If-Range` that matches what this request just
    # built (the ordinary case, since the export is byte-deterministic), is a
    # 416 raised as an HTTPException. Constructing the response first does two
    # things the old order did not: the conversion directory is released on
    # that exit (the BackgroundTask that would have taken it was never attached
    # to anything), and the audit row is written only once a response that
    # carries bytes exists — the same order the hit path uses, for the same
    # reason r16 gave for moving the audit below the 412 and 304 exits.
    #
    # The cleanup rides the response, exactly as fix(#435) arranged it for the
    # FileResponse this replaced. Deleting eagerly — the bytes are in storage,
    # so it looked safe — is what an earlier revision did, and
    # test_export_antimeridian caught it: a caller whose temp directory is not
    # per-export loses more than the export.
    try:
        if stored is not None:
            # may_serve_range=False: this request BUILT the artifact — or lost
            # the publish race and was handed the incumbent (r29), which its
            # client has never seen either — so it cannot know which
            # representation the client's offsets were measured against.
            # Ignoring the Range and answering with the whole thing is the safe
            # half of RFC 9110 section 14.2 and is what keeps a rebuild from
            # splicing; a matching If-Range (r12) overrides it, because that
            # client has named these exact bytes, and so does a Range that
            # starts at byte 0 (fix(#1532) follow-up): that is a probe, never a
            # resume, and it is the first request of a cold GDAL open, which a
            # 200 turned into "Range downloading not supported".
            # The leading slice of a fresh build is honoured unless this URL
            # answered with different bytes inside the last TTL: a client that
            # read a later block from that representation and re-reads the
            # header after the change would splice (#1585 review r1). The
            # listing is consulted only for the request that could use the
            # answer — a bare, satisfiable Range starting at 0 (r3/r4).
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
            # fix(#1435 codex round 2): touch the file's mtime right before
            # handing it to the response. sweep_orphaned_exports (periodic +
            # boot) reads it as "most recent activity" — ogr2ogr's writes
            # already keep it fresh while the file is being generated, but once
            # ogr2ogr closes it the mtime freezes for the rest of a (possibly
            # long, possibly slow-client) download. This resets the
            # age-threshold clock to "streaming is about to begin" instead of
            # "generation finished sometime earlier."
            try:
                os.utime(file_path, None)
            except OSError:
                pass  # best-effort freshness signal; must not block the download
            # fix(#1532 review, internal): NOT a FileResponse. Starlette parses
            # `Range` inside it — single and multipart, no `If-Range` needed —
            # so this path answered a resuming client with a 206 of a fresh
            # conversion at offsets measured against a previous one. That is
            # #1532's defect alive on the degraded path, and the degraded path
            # is the one that fires under load: a full store, a contested
            # selection, an exhausted budget. It also sent an mtime ETag and a
            # Last-Modified the artifact path never sends, so one URL disagreed
            # with itself about which validators it has.
            #
            # fix(#1532 review r19): the same range inputs the stored branch
            # gets, under the same rule — a Range is honoured only behind an
            # If-Range naming this file's ETag, and then it is a slice of the
            # local file rather than the whole of it on every resume.
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
    # The audit_logs.user_id column is nullable; AuditEvent.user_id is typed
    # uuid.UUID | None to match.
    #
    # fix(#1532 review r16): BELOW the precondition exits above, not above them.
    # It used to run before the store, so a rebuild that answered 412 or 304
    # still recorded a `dataset.export` while the hit path deliberately does not.
    # Whether a download appears in the audit trail then depended on whether a
    # conditional request happened to land on a rebuild, which is invisible to
    # the operator reading the report and not a distinction they asked for.
    #
    # The earlier argument for the old position was that a conversion really did
    # run and that is what the row records. That is true and it is the weaker
    # claim: `dataset.export` is read as "this data left the building", the two
    # paths have to agree on what it means, and none of the responses that exit
    # above this line carries a byte of the export.
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
