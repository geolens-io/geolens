"""Shared SQL rendering for parameterized PostGIS analysis (M4).

Lives in platform so both the catalog preview path
(``datasets/domain/service_analysis.py``) and the processing materialize
worker (``processing/analysis/tasks.py``) can import it (CATPORT guards in
test_layering.py forbid catalog importing processing).

Pure string rendering. Injection boundary: numbers are bounds-validated
floats re-checked here against ``MAX_BUFFER_METERS``; clip masks are parsed
and re-serialized by shapely so the embedded JSON is strictly
``{"type": ..., "coordinates": [numbers]}``; table identifiers are the
caller's responsibility (``_safe_table_ref`` / regex-validated names).

Source geometries are wrapped in ``ST_MakeValid``: one invalid ring anywhere
in a dataset would otherwise abort the whole statement with a GEOS
TopologyException.

``geom_4326`` is always LINEAR (ingest applies ``ST_CurveToLine``; migration
0034 backfilled existing rows, #1104), so nothing here needs to guard
against curved input.

fix(#1089): split from a single 1255-line file by operation family —
``shared`` (fences/ceilings/antimeridian/mask parsing), ``overlay``
(clip/intersect/select-by-location), ``measure`` (area/length),
``spatial_join``, ``transform`` (buffer/centroid). Split by family, never by
caller: a per-caller copy is what let preview and materialize drift before
this module existed. This module is the whole import surface;
``test_layering.py`` fails the build if something imports a family module
directly.
"""

from __future__ import annotations

from typing import Any

from .measure import (
    MEASURE_AREA_COLUMN,
    MEASURE_LENGTH_COLUMN,
    MEASURE_OUTPUT_COLUMNS,
    render_measure_columns,
)

# fix(#1089): per-family `render_*_expr` helpers stay private
# (`_`-prefixed) — exporting them would expand the facade past the
# pre-split module's 35 names; the facade-surface test enforces it.
from .measure import render_measure_expr as _render_measure_expr
from .overlay import (
    INTERSECT_OUTPUT_COLUMNS,
    INTERSECT_SOURCE_GID_COLUMN,
    MASK_SUBDIVIDE_MAX_VERTICES,
    render_clip_layer_join,
    render_intersect_pairs,
    render_intersect_preview,
    render_select_by_location_count,
    render_select_by_location_where,
)
from .overlay import render_clip_expr as _render_clip_expr
from .overlay import (
    render_select_by_location_expr as _render_select_by_location_expr,
)
from .shared import (
    BUFFER_LOCAL_SRID_SPAN_DEG,
    BUFFER_SLICE_SEGMENTIZE_M,
    BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG,
    DATELINE_WRAP_SPAN_DEG,
    INTERNAL_ALIAS_PREFIX,
    LATERAL_ALIAS,
    MAX_BUFFER_METERS,
    MAX_MASK_LAYER_FEATURES,
    MAX_MASK_VERTICES,
    MAX_SOURCE_FEATURES,
    NON_GROUPABLE_COLUMN_TYPES,
    NOT_EMPTY_PREDICATE,
    render_bbox_predicate,
    render_dateline_safe,
    render_mask_expr,
)
from .spatial_join import (
    MAX_IDENTIFIER_LENGTH,
    MAX_SPATIAL_JOIN_FIELDS,
    SPATIAL_JOIN_COUNT_COLUMN,
    SPATIAL_JOIN_FIELD_PREFIX,
    render_spatial_join,
    render_spatial_join_match_count,
    spatial_join_output_columns,
)
from .spatial_join import render_spatial_join_expr as _render_spatial_join_expr
from .transform import render_buffer_expr as _render_buffer_expr
from .transform import render_centroid_expr as _render_centroid_expr
from .transform import render_geodesic_buffer


def render_geometry_expr(
    operation: str,
    *,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(geometry expression, WHERE clause)`` for a per-row operation
    on ``geom_4326``. The aggregate ``dissolve`` operation has a different
    query shape and is rendered by the materialize worker, not here.

    ``clip`` here is the INLINE drawn-mask shape; clipping against a mask
    LAYER is a join (``render_clip_layer_join``), not an expression.
    """
    if operation == "buffer":
        return _render_buffer_expr(distance_meters)
    if operation == "centroid":
        return _render_centroid_expr()
    if operation == "measure":
        return _render_measure_expr()
    if operation == "spatial_join":
        return _render_spatial_join_expr()
    if operation == "select_by_location":
        return _render_select_by_location_expr(mask)
    if operation == "clip":
        return _render_clip_expr(mask)
    raise ValueError(f"Unsupported operation: {operation}")


# Explicit rather than implicit: `ruff check --fix` sees every re-export here
# as an unused import (F401) and will strip it without `__all__` marking these
# as the point of the module — this repo has had façade re-exports stripped
# that way before.
#
# This is the pre-split module's 35-name API verbatim; the six private
# `render_*_expr` helpers `render_geometry_expr` composes are not part of it.
# `test_analysis_sql_facade_surface_matches_its_declared_api` diffs this list
# so a symbol silently going missing (breaking `service_analysis.py`,
# `tasks.py`, `router_analysis.py`, `schemas.py`, the sandbox validator or the
# NL->SQL prompt) doesn't slip through unnoticed. A later PR growing this
# list on purpose is fine — #1089 guarded against an UNSTATED change, not
# growth.
__all__ = [
    "BUFFER_LOCAL_SRID_SPAN_DEG",
    "BUFFER_SLICE_SEGMENTIZE_M",
    "BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG",
    "DATELINE_WRAP_SPAN_DEG",
    "INTERNAL_ALIAS_PREFIX",
    "INTERSECT_OUTPUT_COLUMNS",
    "INTERSECT_SOURCE_GID_COLUMN",
    "LATERAL_ALIAS",
    "MASK_SUBDIVIDE_MAX_VERTICES",
    "MAX_BUFFER_METERS",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_MASK_LAYER_FEATURES",
    "MAX_MASK_VERTICES",
    "MAX_SOURCE_FEATURES",
    "MAX_SPATIAL_JOIN_FIELDS",
    "MEASURE_AREA_COLUMN",
    "MEASURE_LENGTH_COLUMN",
    "MEASURE_OUTPUT_COLUMNS",
    "NON_GROUPABLE_COLUMN_TYPES",
    "NOT_EMPTY_PREDICATE",
    "SPATIAL_JOIN_COUNT_COLUMN",
    "SPATIAL_JOIN_FIELD_PREFIX",
    "render_bbox_predicate",
    "render_clip_layer_join",
    "render_dateline_safe",
    "render_geodesic_buffer",
    "render_geometry_expr",
    "render_intersect_pairs",
    "render_intersect_preview",
    "render_mask_expr",
    "render_measure_columns",
    "render_select_by_location_count",
    "render_select_by_location_where",
    "render_spatial_join",
    "render_spatial_join_match_count",
    "spatial_join_output_columns",
]
