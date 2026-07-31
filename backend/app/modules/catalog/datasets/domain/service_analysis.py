"""Parameterized PostGIS analysis operations (M4) — preview path.

Server-built SQL only: every statement is rendered from a fixed template plus
Pydantic-validated parameters, then executed through the read-only sandbox
rails (``execute_safe``): READ ONLY transaction, statement timeout,
reader-role downgrade, row cap, tenant schema rewrite, and a per-user
concurrency lock. No user- or LLM-authored SQL ever reaches this path, so the
LLM-oriented AST validator (``validate_and_execute``) is deliberately not
used — widening its PostGIS function allowlist (e.g. ``ST_Intersection`` for
clip) would expand the *chat* attack surface for no benefit here.

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
    MEASURE_OUTPUT_COLUMNS,
    NOT_EMPTY_PREDICATE,
    render_clip_layer_join,
    render_geometry_expr,
    render_measure_columns,
    render_select_by_location_count,
    render_select_by_location_where,
    render_spatial_join,
    render_spatial_join_match_count,
    spatial_join_output_columns,
)
from app.platform.sandbox.schemas import SandboxError
from app.platform.sandbox.executor import execute_safe
from app.platform.sandbox.schemas import SandboxError

PREVIEW_FEATURE_CAP = 500


# fix(#1014): total concurrent previews, on top of the per-user lock.
#
# The per-user `pg_try_advisory_xact_lock` in execute_safe stops ONE user from
# stacking previews. It does nothing about N different users, and each preview
# holds a dedicated connection from the engine pool for up to the sandbox
# timeout. The pool is db_pool_size 10 + db_max_overflow 3 = 13 slots, and the
# numbers in the #716 note above were measured, not estimated: before that fix
# each preview held two slots and seven concurrent previews exhausted the pool,
# at which point EVERY endpoint on the worker blocked for the 30-second
# pool_timeout and the waiter's SQLAlchemy TimeoutError surfaced as an HTTP 500.
# #716 halved the cost to one slot, which doubles the headroom without changing
# the shape of the failure.
#
# Derived from the configured pool, not hardcoded: DB_POOL_SIZE and
# DB_MAX_OVERFLOW are operator knobs, and against the supported small-pool
# configuration (DB_POOL_SIZE=2, DB_MAX_OVERFLOW=0) a hardcoded ceiling would
# admit more previews than there are connections — the exact failure this bound
# exists to prevent, at a different scale.
#
# A QUARTER, not a third, because not every preview costs one slot. The REST
# endpoint passes release_session=True and costs one, but the AI chat path
# reaches this through defaults_processing_port.run_analysis_preview, which
# cannot release the session (both chat paths read user.id again after the tool
# returns) and therefore holds the request connection alongside the sandbox
# one. Sizing against the worst case of two slots each keeps previews under
# half the pool either way. On the default 13-slot pool that is 3.
#
# The floor of 1 keeps a one-slot pool working rather than deadlocking on a
# semaphore of zero.
#
# A GLOBAL bound, not a tenant-scoped one. Re-keying the per-user lock to the
# tenant is the smaller diff and the wrong behaviour: in the single-tenant
# common case every user is in one tenant, so colleagues would block each other
# for a resource that is not contended between them. What is contended is total
# concurrent connections, so that is what is bounded.
#
# PER WORKER PROCESS, deliberately. An asyncio.Semaphore cannot span processes,
# so with UVICORN_WORKERS=2 the deployment-wide ceiling is 8 — but each worker
# has its OWN pool of 13, so the ratio this protects (4 of 13) holds per pool,
# which is the thing that actually runs out. A cross-worker bound would need
# another advisory lock keyed on a slot index; that is more machinery than this
# warrants unless the per-process reading turns out to be wrong.
# With DB_USE_EXTERNAL_POOLER=true the engine switches to NullPool, so
# DB_POOL_SIZE and DB_MAX_OVERFLOW are ignored entirely and the real budget
# belongs to PgBouncer or RDS Proxy, which this process cannot see. Deriving
# from settings that no longer apply would be arithmetic on numbers that mean
# nothing. Fall back to the value the default pool produces: a throttle is
# still worth having (it is what stops previews saturating the pooler), it just
# cannot be sized from here.
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
    (fix(#701 review)) — so count the physical table instead, stopping at
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
    extra_cols = ""
    extra_joins = ""
    if join_table_ref is not None:
        # fix(#953): the join's whole result is columns, so unlike every other
        # operation the preview MUST carry properties — the geometry it returns
        # is the source layer unchanged, and without join_count on each feature
        # the preview would render pixel-identical to the layer already on the
        # map and show the user nothing.
        cols, extra_joins = render_spatial_join(
            join_table_ref, src="_src", join_fields=request.join_fields
        )
        extra_cols = f", {cols}"
    elif request.operation == "measure":
        # fix(#954): same reason — the measured value IS the result, and the
        # geometry comes back unchanged, so the preview has to carry it as a
        # property or show the user their own layer back.
        cols, extra_joins = render_measure_columns(src="_src")
        extra_cols = f", {cols}"
    if mask_table_ref is not None and request.operation == "select_by_location":
        # fix(#955): a selection keeps whole geometries, so there is no
        # intersection to render and the row filter IS the operation. The
        # identity lateral keeps the query shape (and NOT_EMPTY_PREDICATE)
        # common with every other branch.
        cte = ""
        lateral = "(SELECT geom_4326 AS geom_out OFFSET 0)"
        where = render_select_by_location_where(mask_table_ref, src="_src")
    elif mask_table_ref is not None:
        # fix(#693): layer-sourced clip previews subdivide the mask once and
        # join it per row instead of unioning the whole layer per request;
        # the union CTE remains the materialize shape (see
        # render_clip_layer_join for the measured rationale).
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
    # fix(#680 review): drop NULL/EMPTY results in SQL, not in Python — the
    # sandbox applies its row cap to raw rows, so boundary-grazing clips
    # (which pass ST_Intersects but extract to EMPTY) could consume the whole
    # preview budget along a shared boundary and hide real intersections with
    # higher gids, even reporting a false "no features".
    #
    # fix(#700 review): evaluate the geometry expression exactly once per row
    # via a LATERAL subquery whose OFFSET 0 blocks pull-up — three outer
    # references to geom_out would otherwise be inlined and evaluated three
    # times per row. Unlike fencing the whole row source, the join shape
    # keeps ORDER BY gid able to ride the pkey index, so the sandbox row cap
    # can still stop the scan early instead of evaluating every mask match.
    filters = (
        f"{where} AND {NOT_EMPTY_PREDICATE}"
        if where
        else f" WHERE {NOT_EMPTY_PREDICATE}"
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
    return []


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

    Results are capped at ``PREVIEW_FEATURE_CAP`` features (``truncated`` set
    when the cap was hit). Shares the sandbox's per-user advisory lock
    namespace with AI data queries: one expensive read per user at a time.

    ``mask_dataset`` (clip only) sources the mask from another dataset's
    unioned geometries; the CALLER owns its visibility check, exactly as it
    owns the source dataset's. ``join_dataset`` (spatial_join only) is the same
    contract for the layer being joined against — Rule 1 applies to BOTH
    datasets of a two-layer operation.

    ``release_session`` returns the caller's pooled connection before the
    sandbox query (see below). OPT-IN, because the rollback that releases it
    expires EVERY ORM instance on the session, not just ``dataset`` — including
    the authenticated ``User``, whose next attribute read would then attempt a
    sync refresh and raise ``MissingGreenlet`` (verified: after a rollback even
    ``user.id`` raises). Only pass it from a caller that owns the session and
    reads nothing off it afterwards. The REST endpoint qualifies — it evaluates
    ``user.id`` before the call and touches no ORM state after, and no
    middleware reads the ORM user post-handler. The AI chat tool does NOT: both
    chat paths read ``user.id`` again after the tool returns.
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
        count_sql = render_spatial_join_match_count(table_ref, join_table_ref)
    elif request.operation == "select_by_location":
        count_sql = render_select_by_location_count(
            table_ref, mask_table_ref=mask_table_ref, mask=request.mask
        )
    # Names of the properties this operation adds, in the order the SELECT
    # emits them (immediately after gid and the geometry). Must stay in step
    # with build_preview_sql's extra_cols above — the rows come back positional.
    extra_columns = _preview_extra_columns(request, join_table_ref)
    # fix(#716): read everything off the ORM objects BEFORE releasing the
    # session, then release it. `execute_safe` opens its own connection from the
    # same engine (it needs READ ONLY + SET LOCAL ROLE, which it cannot get on
    # the caller's session), so without this the handler holds two of the
    # pool's 13 slots for the whole sandbox query — the request session, pinned
    # since `get_dataset`, plus the sandbox connection. At 7 concurrent previews
    # demand exceeds the pool and every endpoint on the worker, not just
    # analysis, blocks for the 30s `pool_timeout`; the waiter then raises
    # SQLAlchemy TimeoutError, which the sandbox classifies as `query_failed`
    # → HTTP 500. `rollback()` returns the connection (measured: checkedout
    # 1 → 0), so a preview costs one slot instead of two.
    source_feature_count = dataset.feature_count
    if release_session:
        await db.rollback()
    # fix(#1014): fail fast at the bound rather than queueing. The client is
    # holding a request open, so waiting turns a fast failure into a slow one;
    # the sandbox already has the query_busy path and the frontend already
    # handles it. The message must NOT be the per-user one — "you already have
    # one running" is a misleading explanation for a user whose first preview
    # is being refused because the server is busy.
    #
    # `.locked()` then `async with` is atomic here despite looking like a
    # check-then-act: there is no await between them, and acquiring a semaphore
    # with a free slot does not yield to the loop.
    if _preview_slots.locked():
        # Its own category, not query_busy: every consumer that maps a category
        # to wording — the REST 429 detail and the AI chat ERROR_MESSAGES table
        # — would otherwise relabel this as "your query is already running",
        # which is false for a user whose first preview is being refused.
        raise SandboxError(
            "query_at_capacity",
            "The server is running its maximum number of analysis previews. "
            "Try again in a moment.",
        )
    async with _preview_slots:
        result = await execute_safe(
            db,
            sql,
            row_limit=PREVIEW_FEATURE_CAP,
            concurrency_key=str(user_id),
        )
    features: list[dict[str, Any]] = []
    bbox: list[float] | None = None
    for row in result.rows:
        gid, geometry_json = row[0], row[1]
        if geometry_json is None:
            continue
        geometry = json.loads(geometry_json)
        if not geometry.get("coordinates"):
            # Empty results (e.g. a clip that only grazes a boundary).
            continue
        bbox = _extend_bbox(bbox, geometry.get("coordinates"))
        properties: dict[str, Any] = {"gid": gid}
        properties.update(zip(extra_columns, row[2:]))
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
            await _resolve_match_count(db, count_sql, user_id)
            if count_sql is not None
            else None
        ),
    )


# Operations that drop source rows, so the source's own feature count says
# nothing about how many features the result has.
_ROW_FILTERING_OPERATIONS = ("clip", "select_by_location")


async def _resolve_match_count(
    db: AsyncSession, count_sql: str, user_id: uuid.UUID
) -> int | None:
    """Exact total for an operation whose result the preview cap would mislead
    about, or None when it could not be computed.

    Its own statement, because the preview's row cap would otherwise make the
    number a lie: summing per-row counts across 500 of 12,000 polygons answers
    a question nobody asked, and nothing on the map says so (fix(#953)).
    fix(#955) reuses it for the selected-record total, which has the same
    shape — one uncapped aggregate beside a capped geometry preview.

    Degrades to None rather than failing the preview. It runs second, so it can
    lose the sandbox's per-user lock to another request that arrived in between,
    and it scans both layers so it can outrun the statement timeout on inputs
    the capped geometry preview handles fine. Neither is a reason to throw away
    a preview that already succeeded — and None is a value this response
    already uses to mean "not computable", as source_feature_count does for
    clip.
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
