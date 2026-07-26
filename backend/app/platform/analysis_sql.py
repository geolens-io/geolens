"""Shared SQL rendering for parameterized PostGIS analysis (M4).

Lives in platform so both the catalog preview path
(``datasets/domain/service_analysis.py``) and the processing materialize
worker (``processing/analysis/tasks.py``) can import it — catalog must not
import processing and vice versa (CATPORT guards in test_layering.py).

Pure string rendering. The injection boundary:
- numbers are bounds-validated floats rendered via ``float()`` formatting
  (re-validated here against ``MAX_BUFFER_METERS`` so worker payloads don't
  rely solely on the API schema's bounds);
- clip masks are parsed and re-serialized by shapely, so the embedded JSON
  is strictly ``{"type": ..., "coordinates": [numbers]}``;
- table identifiers are the callers' responsibility (``_safe_table_ref`` /
  regex-validated names).

Source geometries are wrapped in ``ST_MakeValid``: one invalid ring anywhere
in a dataset would otherwise abort the whole statement with a GEOS
TopologyException, with no user-side workaround.
"""

from __future__ import annotations

import math
from typing import Any

import shapely
from shapely.errors import GEOSException
from shapely.geometry import shape

MAX_BUFFER_METERS = 100_000.0
MAX_MASK_VERTICES = 5_000

# fix(#693): the materialize path unions the mask layer WHOLE, and the
# preview pays a per-request subdivide pass over every mask row — both scale
# with the layer, and neither is bounded by any row limit.
MAX_MASK_LAYER_FEATURES = 1_000

# fix(#694): per-operation source-size ceilings.
# dissolve: ST_Union memory grows with input; ~1M polygons OOM-kills a 2 GB
# db container, taking every connection with it — 250k keeps 4x headroom.
# buffer: the only output-amplifying operation, and vector datasets carry no
# byte quota, so bound the amplification source instead.
# Enforced twice with LIMIT-bounded live counts: at enqueue (router, fast
# 422) and again in the worker right before the CTAS — the queue wait can be
# long enough for a dataset to be re-uploaded past its cap (fix(#701
# review)).
MAX_SOURCE_FEATURES = {
    "dissolve": 250_000,
    "buffer": 500_000,
}

_CLIP_MASK_TYPES = ("Polygon", "MultiPolygon")

# Rows an analysis produced nothing for. Both consumers of the lateral shape
# must filter on this: the preview because the sandbox row cap counts raw rows
# (fix(#680 review)), the materialize worker because the output-size ceiling is
# checked against the CTAS before the NULL/EMPTY cleanup runs (fix(#719
# review)). Naming it once keeps the saved dataset and the approved preview
# from drifting apart.
NOT_EMPTY_PREDICATE = "geom_out IS NOT NULL AND NOT ST_IsEmpty(geom_out)"


# Vertex ceiling per mask piece in the preview shape below. 256 is the
# PostGIS-documented sweet spot where per-piece index rebuild overhead and
# per-pair intersection cost balance.
MASK_SUBDIVIDE_MAX_VERTICES = 256


def render_clip_layer_join(mask_table_ref: str, *, src: str) -> tuple[str, str, str]:
    """Clip against a mask LAYER (fix(#693)); used by preview AND materialize.

    Returns ``(cte, lateral_subquery, where_clause)`` for a source table
    aliased ``src``.

    fix(#719): materialize used to keep a single whole-layer ``ST_Union``
    instead, on the theory that one union amortizes over every row in a batch
    job. Measured, that is backwards — per-row ``ST_Intersection`` against one
    giant union geometry is superlinear in mask complexity, so the union shape
    loses at every size. Against 22,324 Manhattan building polygons with a
    972-polygon / 249,804-vertex mask (just under ``MAX_MASK_LAYER_FEATURES``):
    union 33.2s, this shape 3.4s, both yielding the same 12,291 rows. At the
    union shape's rate a ~250k-row source exceeds the 300s CTAS budget, which
    is how a clip whose preview renders in under a second could fail on
    "Create dataset".

    Three cooperating parts (each choice benchmarked on those same masks):

    - ``_mask_pieces`` subdivides the mask's polygonal parts into bounded
      chunks ONCE per statement (MATERIALIZED), so per-row intersection cost
      scales with the local overlap instead of the whole mask — the single
      100k-vertex mask drops 87.9s -> 0.36s. Intersection distributes over
      union, so unioning the per-piece intersections equals clipping against
      the unioned mask.
      Only POLYGONAL components enter it (fix(#682): the catalog's
      geometry_type is classified from the first feature, so a "POLYGON" mask
      layer can still hold point/line rows, and ST_MakeValid can shed line
      remnants from degenerate polygons — either would let point/line source
      features outside every polygon survive the clip). A mask layer with no
      usable polygonal geometry yields no pieces, so nothing intersects and
      callers surface an empty result.
    - The lateral aggregates those piece intersections per source row: one
      output row per gid however many mask rows touch it, evaluated once per
      row (aggregate subqueries cannot be pulled up, so the fix(#700)
      property needs no OFFSET 0 fence here; the inner OFFSET 0 only pins
      the extract/makevalid pass to once per mask row).
      ``ST_LineMerge`` on single-part LineString sources ONLY (fix(#719
      review)): ``ST_Union`` dissolves adjacent polygons back into one, but it
      does not sew line segments, so a LineString crossing a piece or
      mask-row seam came back as an artificially fragmented MultiLineString
      where the whole-mask intersection returned one continuous LineString —
      changing the registered geometry type.

      The test is ``GeometryType(...) = 'LINESTRING'``, NOT
      ``ST_Dimension(...) = 1``. Measured against the whole-mask shape over
      two touching mask polygons (so their union has an interior seam):

        source                      whole-mask   dimension=1   GeometryType
        LineString across seam      LINESTRING/1  LINESTRING/1  LINESTRING/1
        MultiLineString, parts      MULTILINE/2   LINESTRING/1  MULTILINE/2
          touching at a point                     ^^ wrong
        MultiLineString, disjoint   MULTILINE/2   MULTILINE/2   MULTILINE/2
        Polygon across seam         POLYGON/1     POLYGON/1     POLYGON/1
        Point                       POINT/1       POINT/1       POINT/1

      A dimension test merges a multi-part source whose components merely
      touch at an endpoint into one line — a change the mask never asked for,
      and one the whole-mask intersection does not make. Polygons and points
      cannot fragment this way and are left alone either way.
    - The EXISTS row filter probes the RAW mask table, not the CTE: it stays
      index-drivable with real join statistics in either direction (the
      union CTE reached the outer query as an InitPlan Param, blinding the
      selectivity estimator; filtering on the un-indexed piece CTE instead
      costs a linear piece scan per source row — 2.4s vs 0.25s when the mask
      sits at the high end of the gid order).
    """
    cte = (
        f"WITH _mask_pieces AS MATERIALIZED ("
        f"SELECT ST_Subdivide(geom, {MASK_SUBDIVIDE_MAX_VERTICES}) AS geom"
        f" FROM (SELECT ST_CollectionExtract(ST_MakeValid(geom_4326), 3) AS geom"
        f" FROM {mask_table_ref} WHERE geom_4326 IS NOT NULL OFFSET 0) AS _p"
        f" WHERE NOT ST_IsEmpty(geom))"
    )
    lateral = (
        f"(SELECT CASE WHEN GeometryType({src}.geom_4326) = 'LINESTRING'"
        f" THEN ST_LineMerge(_agg.geom) ELSE _agg.geom END AS geom_out"
        f" FROM (SELECT ST_Union(ST_CollectionExtract("
        f"ST_Intersection(ST_MakeValid({src}.geom_4326), _m.geom),"
        f" ST_Dimension({src}.geom_4326) + 1)) AS geom"
        f" FROM _mask_pieces AS _m"
        f" WHERE _m.geom && {src}.geom_4326"
        f" AND ST_Intersects(_m.geom, ST_MakeValid({src}.geom_4326))) AS _agg)"
    )
    where = (
        f" WHERE EXISTS (SELECT 1 FROM {mask_table_ref}"
        f" WHERE geom_4326 && {src}.geom_4326)"
    )
    return cte, lateral, where


def render_mask_expr(mask: dict[str, Any]) -> str:
    """Render a validated clip mask as a PostGIS geometry expression.

    Raises ValueError on anything that is not a usable Polygon/MultiPolygon.
    """
    try:
        geom = shape(mask)
    except (GEOSException, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "mask must be a GeoJSON Polygon or MultiPolygon geometry"
        ) from exc
    if geom.geom_type not in _CLIP_MASK_TYPES:
        raise ValueError("mask must be a GeoJSON Polygon or MultiPolygon geometry")
    if geom.is_empty:
        raise ValueError("mask geometry is empty")
    if shapely.count_coordinates(geom) > MAX_MASK_VERTICES:
        raise ValueError(f"mask exceeds {MAX_MASK_VERTICES} vertices")
    if not all(math.isfinite(v) for v in geom.bounds):
        # NaN/Infinity parse fine as JSON and as shapely coords, then blow up
        # deep inside GEOS as an uncaught exception (a 500, not a 422).
        raise ValueError("mask coordinates must be finite numbers")
    if not geom.is_valid:
        try:
            geom = shapely.make_valid(geom)
        except GEOSException as exc:
            raise ValueError("mask geometry is invalid") from exc
        if geom.geom_type not in _CLIP_MASK_TYPES:
            raise ValueError("mask geometry is invalid")
    rendered = shapely.to_geojson(geom)
    escaped = rendered.replace("'", "''")
    return f"ST_SetSRID(ST_GeomFromGeoJSON('{escaped}'), 4326)"


def render_geometry_expr(
    operation: str,
    *,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(geometry expression, WHERE clause)`` for a per-row operation.

    Operates on the conventional ``geom_4326`` column. The aggregate
    ``dissolve`` operation has a different query shape and is rendered by the
    materialize worker, not here.

    ``clip`` here is the INLINE drawn-mask shape. Clipping against a mask
    LAYER is a join, not an expression — see ``render_clip_layer_join``, which
    both the preview and the materialize worker use.
    """
    if operation == "buffer":
        if distance_meters is None:
            raise ValueError("buffer requires distance_meters")
        distance = float(distance_meters)
        if not math.isfinite(distance) or not 0 < distance <= MAX_BUFFER_METERS:
            raise ValueError(
                f"buffer distance must be between 0 and {MAX_BUFFER_METERS:g} meters"
            )
        return (
            f"ST_Buffer(ST_MakeValid(geom_4326)::geography, {distance})::geometry",
            "",
        )
    if operation == "centroid":
        return "ST_Centroid(ST_MakeValid(geom_4326))", ""
    if operation == "clip":
        mask_expr = render_mask_expr(mask or {})
        # A clip that only grazes a boundary intersects at a lower dimension
        # (polygon ∩ polygon edge → LineString). Extract only components
        # matching the source geometry's dimension (type code = dimension + 1)
        # so the output stays homogeneous; grazing rows become EMPTY, which
        # the preview path skips and the materialize worker deletes.
        # The bare `geom_4326 &&` term keeps the GIST index usable — wrapping
        # the column in ST_MakeValid inside ST_Intersects would defeat it.
        return (
            "ST_CollectionExtract("
            f"ST_Intersection(ST_MakeValid(geom_4326), {mask_expr}),"
            " ST_Dimension(geom_4326) + 1)",
            f" WHERE geom_4326 && {mask_expr}"
            f" AND ST_Intersects(ST_MakeValid(geom_4326), {mask_expr})",
        )
    raise ValueError(f"Unsupported operation: {operation}")
