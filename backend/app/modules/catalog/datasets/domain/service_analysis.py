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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.schemas import (
    AnalysisPreviewRequest,
    AnalysisPreviewResponse,
)
from app.platform.analysis_sql import render_geometry_expr
from app.platform.sandbox.executor import execute_safe

PREVIEW_FEATURE_CAP = 500
_GEOJSON_PRECISION = 6


def build_preview_sql(table_ref: str, request: AnalysisPreviewRequest) -> str:
    """Render the preview SELECT for one operation. Pure; unit-testable.

    ``table_ref`` must come from ``_safe_table_ref`` (logical ``data`` schema;
    the sandbox executor rewrites it to the tenant schema in multi-tenant).
    """
    expr, where = render_geometry_expr(
        request.operation,
        distance_meters=request.distance_meters,
        mask=request.mask,
    )
    return (
        f"SELECT gid, ST_AsGeoJSON({expr}, {_GEOJSON_PRECISION}) AS geometry_json"
        f" FROM {table_ref}{where} ORDER BY gid"
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
) -> AnalysisPreviewResponse:
    """Execute a preview operation and assemble a GeoJSON FeatureCollection.

    Results are capped at ``PREVIEW_FEATURE_CAP`` features (``truncated`` set
    when the cap was hit). Shares the sandbox's per-user advisory lock
    namespace with AI data queries: one expensive read per user at a time.
    """
    table_ref = _safe_table_ref(dataset.table_name)
    sql = build_preview_sql(table_ref, request)
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
    )
