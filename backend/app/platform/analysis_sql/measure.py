"""Measure: the area and length columns, and the cast that feeds them.

The family that leaves the geometry ALONE and adds columns to the row: a
``(select_columns, join_clause)`` pair, the same contract ``spatial_join``
renders — kept as its own module because the two share a composition shape,
not a subject.

Import via the ``app.platform.analysis_sql`` façade, never from here.
"""

from __future__ import annotations

# fix(#954): metres on the wire, matching the buffer distance convention
# (AnalysisPanel's BUFFER_UNIT_METERS). ST_Area(geography)/ST_Length(geography)
# already return square metres/metres, so nothing here converts.
MEASURE_AREA_COLUMN = "area_sqm"
MEASURE_LENGTH_COLUMN = "length_m"
MEASURE_OUTPUT_COLUMNS = (MEASURE_AREA_COLUMN, MEASURE_LENGTH_COLUMN)


def render_measure_columns(*, src: str = "") -> tuple[str, str]:
    """Render the measured columns and the cast that feeds them (fix(#954)).

    Returns ``(select_columns, join_clause)`` in the same shape
    ``render_spatial_join`` uses, so preview and CTAS compose identically.

    BOTH columns are always emitted, never picked by the catalog's
    ``geometry_type`` — that type is classified from the dataset's first
    feature (same trap as fix(#682)), so a table typed POLYGON can hold line
    rows. ``ST_Length`` of a polygon and ``ST_Area`` of a line are both 0, so
    emitting both measures a mixed table correctly throughout.

    The ``::geography`` cast is hoisted into a lateral behind ``OFFSET 0`` so
    it runs ONCE per row and feeds both accessors (fix(#700) shape); inlined,
    each reference casts the geometry again, which is expensive on large
    inputs.

    geography, not planar: correct on the spheroid without buffer's
    projection juggling, and correct across the antimeridian where planar
    area is not.
    """
    prefix = f"{src}." if src else ""
    join = (
        f" CROSS JOIN LATERAL"
        f" (SELECT {prefix}geom_4326::geography AS g"
        f" OFFSET 0) AS _mg"
    )
    columns = (
        f"ST_Area(_mg.g)::double precision AS {MEASURE_AREA_COLUMN},"
        f" ST_Length(_mg.g)::double precision AS {MEASURE_LENGTH_COLUMN}"
    )
    return columns, join


def render_measure_expr() -> tuple[str, str]:
    """Measure's per-row geometry: the source feature, unchanged (fix(#954)).

    Deliberately NOT ST_MakeValid'd, unlike other operations: output IS
    input, so returning a repaired copy would change data the user never
    asked to touch (see ``spatial_join.render_spatial_join_expr``).
    """
    return "geom_4326", ""
