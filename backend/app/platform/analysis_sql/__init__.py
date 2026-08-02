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

``geom_4326`` is always LINEAR — ingest applies ``ST_CurveToLine`` when it
builds the column and migration 0034 backfilled existing rows (#1104) — so
nothing rendered here needs to guard against curved input. The per-read
``linearized()`` wrapper the #1097 review added predated that invariant and
is gone.

fix(#1089): one file until it reached 1255 lines, now a package split by
OPERATION FAMILY:

- ``shared`` — the fences, ceilings, antimeridian helper and mask parser more
  than one family needs, and the half of the injection boundary above that
  runs (``render_mask_expr``).
- ``overlay`` — clip, intersect, select by location: a second layer or a drawn
  mask cuts or filters the source. They share the mask handling, the
  ``ST_Dimension = 2`` polygonal guard and the subdivide path.
- ``measure`` — area and length: columns added, geometry untouched.
- ``spatial_join`` — the same "add columns, leave the geometry alone" contract,
  against a join LAYER rather than a measurement.
- ``transform`` — buffer and centroid: the geometry is replaced in place.

Never by CALLER. Before this module existed the preview path and the worker
each carried their own copy of every statement, and they drifted — an approved
preview and the dataset it saved could disagree about what the operation meant.
Giving those two paths their own rendering modules recreates exactly that, so
the proposal is rejected on sight however it is dressed up.

This module is the whole import surface. Nothing outside ``platform/`` imports
a family module directly, and ``test_layering.py`` fails the build if it does.
"""

from __future__ import annotations

from typing import Any

from .measure import (
    MEASURE_AREA_COLUMN,
    MEASURE_LENGTH_COLUMN,
    MEASURE_OUTPUT_COLUMNS,
    render_measure_columns,
    render_measure_expr,
)
from .overlay import (
    INTERSECT_OUTPUT_COLUMNS,
    INTERSECT_SOURCE_GID_COLUMN,
    MASK_SUBDIVIDE_MAX_VERTICES,
    render_clip_expr,
    render_clip_layer_join,
    render_intersect_pairs,
    render_intersect_preview,
    render_select_by_location_count,
    render_select_by_location_expr,
    render_select_by_location_where,
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
    render_dateline_safe,
    render_mask_expr,
)
from .spatial_join import (
    MAX_IDENTIFIER_LENGTH,
    MAX_SPATIAL_JOIN_FIELDS,
    SPATIAL_JOIN_COUNT_COLUMN,
    SPATIAL_JOIN_FIELD_PREFIX,
    render_spatial_join,
    render_spatial_join_expr,
    render_spatial_join_match_count,
    spatial_join_output_columns,
)
from .transform import (
    render_buffer_expr,
    render_centroid_expr,
    render_geodesic_buffer,
)


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
        return render_buffer_expr(distance_meters)
    if operation == "centroid":
        return render_centroid_expr()
    if operation == "measure":
        return render_measure_expr()
    if operation == "spatial_join":
        return render_spatial_join_expr()
    if operation == "select_by_location":
        return render_select_by_location_expr(mask)
    if operation == "clip":
        return render_clip_expr(mask)
    raise ValueError(f"Unsupported operation: {operation}")


# The façade's contract, spelled out rather than left to whatever the imports
# above happen to bind. Two reasons it is explicit:
#
# - `ruff check --fix` deletes an unused import, and every re-export here IS an
#   unused import as far as F401 can tell. `__all__` is what marks them as the
#   point of the module. This repo has had façade re-exports stripped that way
#   before; the fix is not "remember not to run --fix".
# - It is the list a reviewer diffs against the pre-split module. A symbol that
#   silently stopped being importable would break `service_analysis.py`,
#   `tasks.py`, `router_analysis.py`, `schemas.py`, the sandbox validator or
#   the NL->SQL prompt at import time — and #1089 leaves all of them untouched
#   on purpose, so nothing else in this PR would catch it.
#
# So this is the pre-split API verbatim, 35 names, neither added to nor taken
# from. The six per-family `render_*_expr` helpers `render_geometry_expr`
# composes are #1089's own and are deliberately NOT here: they exist so each
# family owns the branch that renders it, and promoting them would make the
# diff against the old module read as an API change when nothing about the
# caller-facing surface moved.
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
