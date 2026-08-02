"""Measure: the area and length columns, and the cast that feeds them.

The family that leaves the geometry ALONE and adds columns to the row. The
statement is not a per-row expression but a ``(select_columns, join_clause)``
pair the preview and the CTAS compose identically — the same contract
``spatial_join`` renders, which is why the two modules read alike and why
neither one touches ``render_geometry_expr``'s geometry.

#1089 kept this its own module rather than folding it in with spatial_join:
they share a composition shape, not a subject. Geodesic work that joins measure
later — perimeter, geodesic distance — lands here.

Import via the ``app.platform.analysis_sql`` façade, never from here.
"""

from __future__ import annotations

# fix(#954): the columns a measure adds to the source row. Metres on the wire,
# matching the buffer distance convention the panel's unit picker converts for
# (AnalysisPanel's BUFFER_UNIT_METERS). ST_Area(geography) returns square
# metres and ST_Length(geography) metres, so the SQL converts nothing.
MEASURE_AREA_COLUMN = "area_sqm"
MEASURE_LENGTH_COLUMN = "length_m"
MEASURE_OUTPUT_COLUMNS = (MEASURE_AREA_COLUMN, MEASURE_LENGTH_COLUMN)


def render_measure_columns(*, src: str = "") -> tuple[str, str]:
    """Render the measured columns and the cast that feeds them (fix(#954)).

    Returns ``(select_columns, join_clause)`` in the same shape
    ``render_spatial_join`` uses, so the preview and the CTAS compose them
    identically.

    BOTH columns are emitted for every geometry type, rather than picking one
    from the catalog's ``geometry_type``. That column is classified from the
    dataset's FIRST feature (the same trap fix(#682) documents for clip masks),
    so a table typed POLYGON can legitimately hold line rows, and branching on
    it would silently measure the wrong thing for the rest of the table.
    Emitting both is honest instead: ``ST_Length`` of a polygon is 0 and
    ``ST_Area`` of a line is 0, so each row carries its meaningful measure and a
    zero, and a mixed table measures correctly throughout.

    The ``::geography`` cast is hoisted into its own lateral behind an
    ``OFFSET 0`` fence so it runs ONCE per row and feeds both accessors —
    inlined, the two references cast the geometry twice. Same fix(#700) shape
    the preview's geometry expression and the #953 join predicate use; the cast
    is the expensive part on large inputs, which the issue flags directly.

    geography, not planar: it measures on the spheroid, so an unprojected
    dataset gets a correct answer with none of the projection juggling the
    buffer path needs, and an antimeridian-crossing polygon measures correctly
    where planar area does not.
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

    Like spatial_join, measure adds columns and leaves the geometry alone, and
    for the same reason it is deliberately NOT ST_MakeValid'd: the output IS
    the input, so returning a repaired copy would hand back a geometry the user
    never asked to change. See ``spatial_join.render_spatial_join_expr``.

    The measured columns come from ``render_measure_columns``.
    """
    return "geom_4326", ""
