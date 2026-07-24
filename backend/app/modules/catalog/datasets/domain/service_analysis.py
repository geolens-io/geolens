"""Parameterized PostGIS analysis operations (M4) — preview path.

Server-built SQL only: every statement is rendered from a fixed template plus
Pydantic-validated parameters, then executed through the read-only sandbox
rails (``execute_safe``): READ ONLY transaction, statement timeout,
reader-role downgrade, row cap, tenant schema rewrite, and a per-user
concurrency lock. No user- or LLM-authored SQL ever reaches this path, so the
LLM-oriented AST validator (``validate_and_execute``) is deliberately not
used — widening its PostGIS function allowlist (e.g. ``ST_Intersection`` for
clip) would expand the *chat* attack surface for no benefit here.

Parameter rendering rules (the injection boundary):
- numbers: bounds-validated floats, rendered via ``float()`` formatting;
- clip masks: parsed and re-serialized by shapely, so the embedded JSON is
  strictly ``{"type": ..., "coordinates": [numbers]}``;
- identifiers: ``_safe_table_ref`` over the DB-sourced table name.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import shapely
from shapely.errors import GEOSException
from shapely.geometry import shape
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.schemas import (
    AnalysisPreviewRequest,
    AnalysisPreviewResponse,
)
from app.platform.sandbox.executor import execute_safe

PREVIEW_FEATURE_CAP = 500
MAX_MASK_VERTICES = 5_000
_GEOJSON_PRECISION = 6

_CLIP_MASK_TYPES = ("Polygon", "MultiPolygon")


def _mask_expr(mask: dict[str, Any]) -> str:
    """Render a validated clip mask as a PostGIS geometry expression.

    The mask is parsed and re-serialized by shapely, so the embedded JSON
    contains only a type tag and numeric coordinate arrays — never caller
    text. Single-quote escaping is belt-and-braces on top of that.
    """
    try:
        geom = shape(mask)
    except (GEOSException, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "mask must be a GeoJSON Polygon or MultiPolygon geometry"
        ) from exc
    if geom.geom_type not in _CLIP_MASK_TYPES:
        raise ValueError("mask must be a GeoJSON Polygon or MultiPolygon geometry")
    if shapely.count_coordinates(geom) > MAX_MASK_VERTICES:
        raise ValueError(f"mask exceeds {MAX_MASK_VERTICES} vertices")
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
        if geom.geom_type not in _CLIP_MASK_TYPES:
            raise ValueError("mask geometry is invalid")
    rendered = shapely.to_geojson(geom)
    escaped = rendered.replace("'", "''")
    return f"ST_SetSRID(ST_GeomFromGeoJSON('{escaped}'), 4326)"


def build_preview_sql(table_ref: str, request: AnalysisPreviewRequest) -> str:
    """Render the preview SELECT for one operation. Pure; unit-testable.

    ``table_ref`` must come from ``_safe_table_ref`` (logical ``data`` schema;
    the sandbox executor rewrites it to the tenant schema in multi-tenant).
    """
    where = ""
    if request.operation == "buffer":
        distance = float(request.distance_meters)
        expr = f"ST_Buffer(geom_4326::geography, {distance})::geometry"
    elif request.operation == "centroid":
        expr = "ST_Centroid(geom_4326)"
    else:  # clip — mask requiredness enforced by the request model
        mask = _mask_expr(request.mask)
        expr = f"ST_CollectionExtract(ST_Intersection(geom_4326, {mask}))"
        where = f" WHERE ST_Intersects(geom_4326, {mask})"
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
