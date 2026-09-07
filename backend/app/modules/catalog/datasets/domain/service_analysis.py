"""Parameterized PostGIS analysis operations (M4) — preview path.

Server-built SQL only: every statement renders from a fixed template plus
Pydantic-validated parameters, executed through the read-only sandbox rails
(``execute_safe``): READ ONLY transaction, statement timeout, reader-role
downgrade, row cap, tenant schema rewrite, per-user concurrency lock. No
user- or LLM-authored SQL reaches this path, so the LLM-oriented AST
validator (``validate_and_execute``) is deliberately not used -- widening
its allowlist for this path would expand the *chat* attack surface for no
benefit here.

Expression rendering (and its injection rules) is shared with the async
materialize worker via ``app.platform.analysis_sql``.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import text
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.schemas import (
    AnalysisPreviewRequest,
    AnalysisPreviewResponse,
)
from app.platform.analysis_sql import (
    INTERSECT_SOURCE_GID_COLUMN,
    MEASURE_OUTPUT_COLUMNS,
    NOT_EMPTY_PREDICATE,
    render_bbox_predicate,
    render_clip_layer_join,
    render_geometry_expr,
    render_intersect_preview,
    render_measure_columns,
    render_select_by_location_count,
    render_select_by_location_where,
    render_spatial_join,
    render_spatial_join_match_count,
    spatial_join_output_columns,
)
from app.platform.sandbox.executor import execute_safe
from app.platform.sandbox.schemas import SandboxError

PREVIEW_FEATURE_CAP = 500


# fix(#1014): global cap on concurrent previews, on top of the per-user
# pg_try_advisory_xact_lock in execute_safe (which only stops ONE user
# stacking previews). fix(#716) measured the need: at two pool slots per
# preview, 7 concurrent previews exhausted the 13-slot pool
# (db_pool_size 10 + db_max_overflow 3), blocking every worker endpoint
# for the 30s pool_timeout until an HTTP 500. #716 halved the cost to
# one slot; derived from the configured pool, not hardcoded, since a
# fixed ceiling could exceed a small-pool deployment's real connections.
#
# A QUARTER, not a third: the REST endpoint costs one slot
# (release_session), but the AI chat path holds two (can't release its
# session). Sizing against that worst case keeps previews under half
# the pool -- 3 on the default 13-slot pool, floored at 1.
#
# GLOBAL, not tenant-scoped, since total connections are what's
# contended, not a per-tenant resource. PER WORKER PROCESS, since a
# semaphore can't span processes -- each worker has its own pool, so the
# ratio holds per pool even though UVICORN_WORKERS=2 doubles the
# deployment-wide ceiling.
#
# With DB_USE_EXTERNAL_POOLER=true the engine uses NullPool, so the real
# budget belongs to PgBouncer/RDS Proxy, invisible here -- fall back to
# the value the default pool produces instead.
_EXTERNAL_POOLER_PREVIEW_BOUND = 3


def _preview_bound() -> int:
    from app.core.config import settings

    if settings.db_use_external_pooler:
        return _EXTERNAL_POOLER_PREVIEW_BOUND
    # db_max_overflow uses -1 for "unlimited"; treat that as no extra headroom
    # rather than letting a negative shrink the budget.
    overflow = max(0, settings.db_max_overflow)
    return max(1, (settings.db_pool_size + overflow) // 4)


_MAX_CONCURRENT_PREVIEWS = _preview_bound()
_preview_slots = asyncio.Semaphore(_MAX_CONCURRENT_PREVIEWS)
_GEOJSON_PRECISION = 6


async def resolve_source_feature_count(
    db: AsyncSession, dataset: Dataset, *, cap: int
) -> int:
    """Feature count for enqueue gating, bounded by ``cap``.

    Uses the cached catalog snapshot when present. When it is NULL (legacy
    imports, ``register_existing_table`` paths), a NULL-as-zero default
    would admit exactly the unknown-size datasets the OOM gates exist for
    (fix(#701)) -- so count the physical table instead, stopping at
    ``cap + 1`` rows so the probe itself stays bounded.
    """
    if dataset.feature_count is not None:
        return dataset.feature_count
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    schema = tenant_data_schema(current_tenant_var.get() if is_multi_tenant() else None)
    ref = _safe_table_ref(dataset.table_name, schema=schema)
    result = await db.execute(
        text(
            f"SELECT count(*) FROM (SELECT 1 FROM {ref} LIMIT :lim) AS _n"  # noqa: S608
        ).bindparams(lim=cap + 1)
    )
    return int(result.scalar_one())


async def _resolve_bbox_source_count(
    db: AsyncSession, table_ref: str, bbox: list[float], user_id: uuid.UUID
) -> int | None:
    """Exact 1:1-operation denominator scoped to a preview's viewport bbox, or
    ``None`` if it could not be computed within the query budget.

    Bypasses the cached ``dataset.feature_count`` deliberately: that's a
    WHOLE-table total, and pairing "500 of 22,324" with a viewport-scoped
    result would assert something the result doesn't support.

    fix(#727): runs through ``execute_safe`` inside
    ``run_analysis_preview``'s ``_preview_slots`` block, not a bare
    ``db.execute`` on the caller's session (which reintroduced the
    pool-exhaustion class fix(#716)/fix(#1014) prevent). Returns a real
    count or ``None`` on timeout/failure, never a capped number dressed
    up as exact.

    Takes ``table_ref`` (LOGICAL ``data`` schema), not ``dataset``:
    ``execute_safe`` does the tenant-schema rewrite itself.
    """
    predicate = render_bbox_predicate(bbox, src="_t")
    count_sql = f"SELECT count(*)::bigint AS source_count FROM {table_ref} AS _t WHERE {predicate}"
    try:
        result = await execute_safe(
            db, count_sql, row_limit=1, concurrency_key=str(user_id)
        )
    except SandboxError:
        return None
    return int(result.rows[0][0]) if result.rows else None


def build_preview_sql(
    table_ref: str,
    request: AnalysisPreviewRequest,
    mask_table_ref: str | None = None,
    join_table_ref: str | None = None,
) -> str:
    """Render the preview SELECT for one operation. Pure; unit-testable.

    ``table_ref`` (and ``mask_table_ref`` for layer-sourced clip masks,
    ``join_table_ref`` for spatial joins) must come from ``_safe_table_ref``
    (logical ``data`` schema; the sandbox executor rewrites it to the tenant
    schema in multi-tenant).
    """
    if request.operation == "intersect" and mask_table_ref is not None:
        # Rendered whole in analysis_sql: an overlay is a JOIN with a GROUP BY,
        # not a per-row expression, so it shares none of the lateral template
        # below. See render_intersect_preview for why match_count rides this
        # statement as a window rather than costing a second overlay.
        #
        # fix(#727): bbox passes straight through to
        # render_intersect_preview/render_intersect_pairs -- it does NOT
        # share the WHERE clause the other operations compose through below
        # (this branch returns first), so it needed its own plumbing.
        return render_intersect_preview(
            table_ref,
            mask_table_ref,
            geojson_precision=_GEOJSON_PRECISION,
            bbox=request.bbox,
        )
    extra_cols = ""
    extra_joins = ""
    if join_table_ref is not None:
        # fix(#953): unlike every other operation, the geometry comes back
        # unchanged, so the preview MUST carry join_count as a property or
        # it renders pixel-identical to the layer already on the map.
        cols, extra_joins = render_spatial_join(
            join_table_ref, src="_src", join_fields=request.join_fields
        )
        extra_cols = f", {cols}"
    elif request.operation == "measure":
        # fix(#954): same reason -- the measured value IS the result and the
        # geometry is unchanged, so it has to ride along as a property.
        cols, extra_joins = render_measure_columns(src="_src")
        extra_cols = f", {cols}"
    if mask_table_ref is not None and request.operation == "select_by_location":
        # fix(#955): a selection keeps whole geometries, so the row filter IS
        # the operation; the identity lateral keeps the query shape (and
        # NOT_EMPTY_PREDICATE) common with every other branch.
        cte = ""
        lateral = "(SELECT geom_4326 AS geom_out OFFSET 0)"
        where = render_select_by_location_where(mask_table_ref, src="_src")
    elif mask_table_ref is not None:
        # fix(#693): layer-sourced clip previews subdivide the mask once and
        # join it per row instead of unioning the whole layer per request;
        # see render_clip_layer_join for the measured rationale.
        cte, lateral, where = render_clip_layer_join(mask_table_ref, src="_src")
        cte = f"{cte} "
    else:
        cte = ""
        expr, where = render_geometry_expr(
            request.operation,
            distance_meters=request.distance_meters,
            mask=request.mask,
        )
        lateral = f"(SELECT {expr} AS geom_out OFFSET 0)"
    # fix(#680): drop NULL/EMPTY results in SQL, not Python -- the row cap
    # applies to raw rows, so boundary-grazing clips (ST_Intersects true,
    # EMPTY extract) could consume the whole budget and hide real matches.
    #
    # fix(#700): the LATERAL subquery's OFFSET 0 blocks pull-up (else
    # three outer references to geom_out evaluate three times per row);
    # the join shape keeps ORDER BY gid on the pkey index for early stop.
    #
    # fix(#727): the viewport bbox joins this predicate list, not the
    # whole FROM, so it stays index-drivable and ORDER BY gid still rides
    # the pkey index over the smaller on-screen source.
    extra_predicates = NOT_EMPTY_PREDICATE
    if request.bbox is not None:
        extra_predicates = (
            f"{extra_predicates} AND {render_bbox_predicate(request.bbox, src='_src')}"
        )
    filters = (
        f"{where} AND {extra_predicates}" if where else f" WHERE {extra_predicates}"
    )
    return (
        f"{cte}SELECT gid,"
        f" ST_AsGeoJSON(_op.geom_out, {_GEOJSON_PRECISION}) AS geometry_json"
        f"{extra_cols}"
        f" FROM {table_ref} AS _src"
        f" CROSS JOIN LATERAL {lateral} AS _op"
        f"{extra_joins}"
        f"{filters}"
        f" ORDER BY gid"
    )


def _preview_extra_columns(
    request: AnalysisPreviewRequest, join_table_ref: str | None
) -> list[str]:
    """Property names the preview carries beyond ``gid``, in SELECT order.

    Mirrors the ``extra_cols`` branches in ``build_preview_sql``: the rows come
    back positional, so the two must agree or properties land under the wrong
    names. One function per side rather than one shared renderer because the
    SQL side needs table aliases the caller owns.
    """
    if join_table_ref is not None:
        return spatial_join_output_columns(request.join_fields)
    if request.operation == "measure":
        return list(MEASURE_OUTPUT_COLUMNS)
    if request.operation == "intersect":
        return [INTERSECT_SOURCE_GID_COLUMN]
    return []


def _json_safe(value: Any) -> Any:
    """Make one transferred property value JSON-serializable.

    fix(#1097): a spatial join can transfer a ``bytea`` column back as raw
    ``bytes``, which Pydantic's JSON serializer 500s on; encode as
    PostgreSQL's ``\\x``-hex, matching ``to_jsonb(t.*)`` in the features API.

    Recursive: a ``bytea[]`` comes back as a list of ``bytes`` (a
    scalar-only check would miss it). Natively-serializable scalars
    (datetime, date, Decimal, UUID) pass through untouched.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _extend_bbox(bbox: list[float] | None, coords: Any) -> list[float] | None:
    """Fold a GeoJSON coordinate array into a [minx, miny, maxx, maxy] bbox."""
    if not isinstance(coords, (list, tuple)) or not coords:
        return bbox
    if isinstance(coords[0], (int, float)):
        x, y = float(coords[0]), float(coords[1])
        if bbox is None:
            return [x, y, x, y]
        bbox[0] = min(bbox[0], x)
        bbox[1] = min(bbox[1], y)
        bbox[2] = max(bbox[2], x)
        bbox[3] = max(bbox[3], y)
        return bbox
    for part in coords:
        bbox = _extend_bbox(bbox, part)
    return bbox


async def run_analysis_preview(
    db: AsyncSession,
    dataset: Dataset,
    request: AnalysisPreviewRequest,
    user_id: uuid.UUID,
    *,
    mask_dataset: Dataset | None = None,
    join_dataset: Dataset | None = None,
    release_session: bool = False,
) -> AnalysisPreviewResponse:
    """Execute a preview operation and assemble a GeoJSON FeatureCollection.

    Capped at ``PREVIEW_FEATURE_CAP`` features (``truncated`` set on hit).
    Shares the sandbox's per-user advisory lock namespace with AI data
    queries. ``mask_dataset``/``join_dataset``: the CALLER owns their
    visibility check, same as the source dataset's (Rule 1 on both).

    ``release_session`` OPT-IN only: the rollback that returns the pooled
    connection expires EVERY ORM instance, including ``User``, whose next
    attribute read raises ``MissingGreenlet``. Only pass it from a caller
    reading nothing off the session afterwards -- the REST endpoint
    qualifies; the AI chat tool does NOT (reads ``user.id`` again after).

    ``request.bbox`` (fix(#727)), when present, scopes the row cap to the
    viewport before ``ORDER BY gid`` applies; the AI chat tool never sets it.
    """
    table_ref = _safe_table_ref(dataset.table_name)
    mask_table_ref = (
        _safe_table_ref(mask_dataset.table_name) if mask_dataset is not None else None
    )
    join_table_ref = (
        _safe_table_ref(join_dataset.table_name) if join_dataset is not None else None
    )
    sql = build_preview_sql(table_ref, request, mask_table_ref, join_table_ref)
    # The uncapped total that goes beside the capped preview, or None when the
    # operation has no such number. Rendered here, with the table refs already
    # in hand, and run after the geometry query below.
    count_sql: str | None = None
    if join_table_ref is not None:
        count_sql = render_spatial_join_match_count(
            table_ref, join_table_ref, bbox=request.bbox
        )
    elif request.operation == "select_by_location":
        count_sql = render_select_by_location_count(
            table_ref, mask_table_ref=mask_table_ref, mask=request.mask
        )
    # Names of the properties this operation adds, in the order the SELECT
    # emits them (immediately after gid and the geometry). Must stay in step
    # with build_preview_sql's extra_cols above — the rows come back positional.
    extra_columns = _preview_extra_columns(request, join_table_ref)
    # fix(#716): read everything off the ORM objects BEFORE releasing the
    # session. `execute_safe` opens its own connection (needs READ ONLY +
    # SET LOCAL ROLE, unavailable on the caller's session), so without this
    # the handler holds two of the pool's 13 slots for the whole sandbox
    # query. `rollback()` returns the connection, so a preview costs one
    # slot instead of two -- at two slots, 7 concurrent previews exhaust
    # the pool and every endpoint on the worker 500s on pool_timeout.
    source_feature_count = dataset.feature_count
    # fix(#727): whether the cached snapshot above gets overridden by a live,
    # bbox-scoped count. Cheap check only; the count itself runs inside the
    # _preview_slots block below via execute_safe, which opens its own
    # connection and has no ordering dependency on the rollback below.
    bbox_scoped_count_needed = (
        request.bbox is not None and request.operation not in _ROW_FILTERING_OPERATIONS
    )
    if release_session:
        await db.rollback()
    # fix(#1014): fail fast at the bound rather than queueing -- the client
    # holds a request open, so waiting turns a fast failure into a slow one.
    # `.locked()` then `async with` is atomic here despite looking like
    # check-then-act: no await between them, and acquiring a free-slot
    # semaphore doesn't yield to the loop.
    if _preview_slots.locked():
        # Its own category, not query_busy: "you already have one running"
        # is a misleading explanation for a user whose first preview is
        # being refused because the server is busy.
        raise SandboxError(
            "query_at_capacity",
            "The server is running its maximum number of analysis previews. "
            "Try again in a moment.",
        )
    async with _preview_slots:
        # fix(#727): the bbox-scoped denominator lives in this slot too, not
        # before it. Read first, before the geometry query, so a preview
        # whose denominator loses the race for the sandbox's per-user
        # advisory lock still gets a geometry result even if the count
        # comes back None.
        source_feature_count = (
            await _resolve_bbox_source_count(db, table_ref, request.bbox, user_id)
            if bbox_scoped_count_needed and request.bbox is not None
            else source_feature_count
        )
        result = await execute_safe(
            db,
            sql,
            row_limit=PREVIEW_FEATURE_CAP,
            concurrency_key=str(user_id),
        )
        # fix(#1097): inside the same slot as the geometry query, not after
        # it -- both open their own sandbox connection, so releasing the
        # semaphore between them would let _MAX_CONCURRENT_PREVIEWS stop
        # bounding connections while the uncapped, both-layer count query
        # is still running (the geometry query stops at PREVIEW_FEATURE_CAP).
        resolved_match_count = (
            await _resolve_match_count(db, count_sql, user_id)
            if count_sql is not None
            else None
        )
    features: list[dict[str, Any]] = []
    bbox: list[float] | None = None
    # fix(#956): intersect's exact total rides its own preview statement as a
    # trailing window column (see build_preview_sql). Read off any row -- the
    # window is computed before the cap, so every row carries the true total.
    #
    # fix(#1097): seeded to 0, not None, for intersect: the window column
    # rides ON the rows, so zero overlapping pairs means no row to read it
    # off, which would wrongly report `match_count: null` (the contract's
    # "could not be computed" state) for a correct, ordinary empty answer.
    inline_match_count: int | None = 0 if request.operation == "intersect" else None
    for row in result.rows:
        if request.operation == "intersect":
            inline_match_count = int(row[-1])
        gid, geometry_json = row[0], row[1]
        if geometry_json is None:
            continue
        geometry = json.loads(geometry_json)
        if not geometry.get("coordinates"):
            # Empty results (e.g. a clip that only grazes a boundary).
            continue
        bbox = _extend_bbox(bbox, geometry.get("coordinates"))
        properties: dict[str, Any] = {"gid": gid}
        properties.update(
            (name, _json_safe(value)) for name, value in zip(extra_columns, row[2:])
        )
        features.append(
            {"type": "Feature", "geometry": geometry, "properties": properties}
        )
    return AnalysisPreviewResponse(
        geojson={"type": "FeatureCollection", "features": features},
        feature_count=len(features),
        truncated=result.truncated,
        bbox=bbox,
        # buffer/centroid are 1:1 per feature, so the source count IS the
        # output total and lets clients render "500 of N" on truncation.
        # spatial_join is 1:1 too — it adds columns and keeps every row.
        # clip and select_by_location filter rows, so their totals are
        # unknowable from the source count. select_by_location answers the same
        # question exactly, through match_count below.
        source_feature_count=(
            source_feature_count
            if request.operation not in _ROW_FILTERING_OPERATIONS
            else None
        ),
        match_count=(
            inline_match_count
            if request.operation == "intersect"
            else resolved_match_count
        ),
    )


# Operations that drop source rows, so the source's own feature count says
# nothing about how many features the result has.
_ROW_FILTERING_OPERATIONS = ("clip", "select_by_location", "intersect")


async def _resolve_match_count(
    db: AsyncSession, count_sql: str, user_id: uuid.UUID
) -> int | None:
    """Exact total for an operation whose result the preview cap would mislead
    about, or None when it could not be computed.

    Its own statement, since the row cap would otherwise lie: summing
    per-row counts across 500 of 12,000 polygons answers a question
    nobody asked (fix(#953); fix(#955) reuses it for selected-record totals).

    Degrades to None rather than failing the preview: it runs second, so
    it can lose the per-user lock to another request or outrun the
    statement timeout scanning both layers -- neither a reason to discard
    a preview that already succeeded.
    """
    try:
        result = await execute_safe(
            db,
            count_sql,
            row_limit=1,
            concurrency_key=str(user_id),
        )
    except SandboxError:
        return None
    return int(result.rows[0][0]) if result.rows else None
