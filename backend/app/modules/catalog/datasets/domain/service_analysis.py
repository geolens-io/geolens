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
    NOT_EMPTY_PREDICATE,
    render_clip_layer_join,
    render_geometry_expr,
)
from app.platform.sandbox.executor import execute_safe

PREVIEW_FEATURE_CAP = 500
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
) -> str:
    """Render the preview SELECT for one operation. Pure; unit-testable.

    ``table_ref`` (and ``mask_table_ref`` for layer-sourced clip masks) must
    come from ``_safe_table_ref`` (logical ``data`` schema; the sandbox
    executor rewrites it to the tenant schema in multi-tenant).
    """
    if mask_table_ref is not None:
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
        f" FROM {table_ref} AS _src"
        f" CROSS JOIN LATERAL {lateral} AS _op"
        f"{filters}"
        f" ORDER BY gid"
    )


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
    release_session: bool = False,
) -> AnalysisPreviewResponse:
    """Execute a preview operation and assemble a GeoJSON FeatureCollection.

    Results are capped at ``PREVIEW_FEATURE_CAP`` features (``truncated`` set
    when the cap was hit). Shares the sandbox's per-user advisory lock
    namespace with AI data queries: one expensive read per user at a time.

    ``mask_dataset`` (clip only) sources the mask from another dataset's
    unioned geometries; the CALLER owns its visibility check, exactly as it
    owns the source dataset's.

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
    sql = build_preview_sql(table_ref, request, mask_table_ref)
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
    result = await execute_safe(
        db,
        sql,
        row_limit=PREVIEW_FEATURE_CAP,
        concurrency_key=str(user_id),
    )
    features: list[dict[str, Any]] = []
    bbox: list[float] | None = None
    for gid, geometry_json in result.rows:
        if geometry_json is None:
            continue
        geometry = json.loads(geometry_json)
        if not geometry.get("coordinates"):
            # Empty results (e.g. a clip that only grazes a boundary).
            continue
        bbox = _extend_bbox(bbox, geometry.get("coordinates"))
        features.append(
            {"type": "Feature", "geometry": geometry, "properties": {"gid": gid}}
        )
    return AnalysisPreviewResponse(
        geojson={"type": "FeatureCollection", "features": features},
        feature_count=len(features),
        truncated=result.truncated,
        bbox=bbox,
        # buffer/centroid are 1:1 per feature, so the source count IS the
        # output total and lets clients render "500 of N" on truncation.
        # clip filters rows, so its total is unknowable without a second scan.
        source_feature_count=(
            source_feature_count if request.operation != "clip" else None
        ),
    )
