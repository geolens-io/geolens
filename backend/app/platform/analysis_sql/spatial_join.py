"""Spatial join: count and transfer fields from a second LAYER.

Neither of the other two-input families. It reads a join layer like
``overlay`` does, but nothing is cut or filtered — the output geometry is
the source feature verbatim — so it has no mask, no ``ST_Dimension = 2``
guard and nothing to subdivide. It renders the ``(select_columns,
join_clause)`` pair ``measure`` renders, but it is not a measurement, and
the machinery it needs is its own: identifier-length truncation, the
join-field name rule and cap, and the two-lateral count/pick shape with its
stated tie-break.

Import via the ``app.platform.analysis_sql`` façade, never from here.
"""

from __future__ import annotations

import re

from .shared import render_bbox_predicate

# fix(#953): the columns a spatial join adds to the source row.
SPATIAL_JOIN_COUNT_COLUMN = "join_count"
SPATIAL_JOIN_FIELD_PREFIX = "join_"

# PostgreSQL's NAMEDATALEN - 1. An identifier longer than this is truncated
# with a NOTICE rather than refused, so a guard comparing untruncated names
# compares strings the database will never see. Confirmed on the server
# (SELECT current_setting('max_identifier_length')), not taken on faith.
# Bytes, strictly — but every name this bounds is ASCII, since
# _SAFE_COLUMN_RE gates the join fields a request can name.
MAX_IDENTIFIER_LENGTH = 63

# Transferred fields are capped because each one widens every output row and
# the CTAS has a fixed time budget. Ten is well past the "which district is
# this in" case the operation exists for.
MAX_SPATIAL_JOIN_FIELDS = 10

# Same rule dissolve applies to by_field (_validate_dissolve_by_field): a
# user-selected column name must be identifier-shaped, so the rendering
# below can quote with plain double quotes — nothing for SQLAlchemy's
# text() bind-parameter parser or an identifier escape to get wrong. Cost:
# a column named "Área" can't be transferred (nor dissolved, today). Source
# columns are unaffected — they ride the carry-column path, which quotes
# properly and carries every name (fix(#763)).
_SPATIAL_JOIN_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def spatial_join_output_columns(join_fields: list[str] | None) -> list[str]:
    """Names of the columns a spatial join generates, in output order.

    Callers use this to reject a source dataset that already has a column of
    the same name: the CTAS would otherwise fail with "column specified more
    than once" after the queue wait, the same trap ``by_field`` hits on
    dissolve's generated ``source_count``.

    fix(#1097): TRUNCATED to PostgreSQL's identifier limit, since
    that's the name the CTAS will actually create — verified against the
    server (max_identifier_length is 63; a longer alias is silently
    truncated to it, a NOTICE not an error, quoted or not).

    Two join fields sharing their first 58 characters prefix to strings
    that differ here but are the SAME column in the output, so an
    untruncated uniqueness check would pass and the CTAS would fail after
    the queue wait. An overlong alias can also truncate ONTO an existing
    source column without the collision check noticing.

    Truncating here rather than rejecting long names keeps every consumer —
    the router's two checks, the worker's recheck, this list's own
    uniqueness rule — reading names the database will actually compare.
    Source columns need no such treatment: the server already truncated
    them when the table was created.
    """
    return [SPATIAL_JOIN_COUNT_COLUMN] + [
        f"{SPATIAL_JOIN_FIELD_PREFIX}{name}"[:MAX_IDENTIFIER_LENGTH]
        for name in (join_fields or [])
    ]


def render_spatial_join(
    join_table_ref: str,
    *,
    src: str,
    join_fields: list[str] | None = None,
) -> tuple[str, str]:
    """Spatial join against another LAYER (fix(#953)); preview AND materialize.

    Returns ``(select_columns, join_clauses)`` for a source table aliased
    ``src``. The geometry is NOT touched — a spatial join adds columns, so
    the output geometry is the source feature verbatim (see
    ``render_geometry_expr`` for why it is not even ST_MakeValid'd).

    Strictly 1:1. Two laterals, because the two halves want opposite things:

    - The count lateral aggregates EVERY match, so it needs no tie-break and
      always returns exactly one row (``CROSS JOIN``).
    - The field lateral takes exactly one match under a stated tie-break —
      **lowest join-layer gid** — via ``ORDER BY _j.gid LIMIT 1``. Without
      it a point inside two overlapping polygons emits two rows for one
      source feature, and materialize dies on ``ADD PRIMARY KEY (gid)``
      with a constraint error rather than anything a user could act on.
      ``LEFT JOIN`` so a source row matching nothing keeps its row with
      NULL fields instead of vanishing, which would break the 1:1 property
      that lets ``source_feature_count`` mean anything.

    Deterministic beats cartographically ideal: smallest-containing-polygon
    would pick the city over the county for nested boundaries, but costs an
    ST_Area per matched pair and nothing in the issue asks for it.

    The match predicate keeps the raw ``&&`` term on the bare columns so the
    GIST index stays usable, then re-tests with ST_Intersects over
    made-valid geometries — the same split ``render_geometry_expr`` uses
    for clip. Both sides are made valid: one invalid ring in EITHER layer
    would otherwise abort the whole statement with a GEOS TopologyException.

    The explicit ``IS NOT NULL`` term is redundant and deliberate: ``&&``
    against a NULL yields NULL, so an ungeometried join row already fails
    the WHERE (verified by mutation that removing it changes no result). It
    stays because an arbitrary join layer IS partly ungeometried — #700
    made analysis OUTPUTS NULL-free, not arbitrary uploads — and the next
    editor shouldn't have to re-derive three-valued logic to confirm those
    rows are handled.
    """
    fields = list(join_fields or [])
    if len(fields) != len(set(fields)):
        raise ValueError("join_fields contains duplicates")
    if len(fields) > MAX_SPATIAL_JOIN_FIELDS:
        raise ValueError(
            f"At most {MAX_SPATIAL_JOIN_FIELDS} join fields may be transferred"
        )
    for name in fields:
        if not _SPATIAL_JOIN_IDENT.match(name):
            raise ValueError(f"Invalid join field name: {name!r}")

    # fix(#953): the JOIN side is tested RAW, deliberately. PostGIS 3.6
    # raises from ST_Intersection over a self-intersecting bowtie but
    # ST_Intersects over the same geometry returns the same answer the
    # repaired geometry gives, in either argument position. Wrapping it
    # costs a repair per CANDIDATE ROW that the source-side hoist below
    # can't amortise, since _j differs every row: 32,186 meteorite points
    # against 242 Natural Earth country polygons measured 33.68s wrapped
    # vs 1.98s raw (both 30,712 pairs). Prevalidating the join layer in a
    # MATERIALIZED CTE was tried and is worse — no win in that direction
    # (5.22s) and loses the GIST index in the other (0.21s to 12.88s).
    match = (
        f"_j.geom_4326 IS NOT NULL"
        f" AND _j.geom_4326 && {src}.geom_4326"
        f" AND ST_Intersects(_j.geom_4326, _sv.g)"
    )
    columns = f"_jc.{SPATIAL_JOIN_COUNT_COLUMN}"
    joins = (
        # fix(#953): the source geometry is made valid ONCE PER SOURCE ROW
        # here, not inside the predicate below — inlined it is re-evaluated
        # per CANDIDATE PAIR, the same trap fix(#700) documents for the
        # preview's geometry expression, fixed the same way (OFFSET 0 fence
        # against subquery pull-up). Measured (242 Natural Earth country
        # polygons x 32,186 meteorite points, both 30,712 matches): inlined
        # 28.36s, hoisted 0.20s. The inlined form blew the sandbox's 10s
        # statement timeout, so the preview 422'd on an obvious pairing.
        f" CROSS JOIN LATERAL"
        f" (SELECT ST_MakeValid({src}.geom_4326) AS g"
        f" OFFSET 0) AS _sv"
        f" CROSS JOIN LATERAL ("
        f"SELECT count(*)::integer AS {SPATIAL_JOIN_COUNT_COLUMN}"
        f" FROM {join_table_ref} AS _j WHERE {match}) AS _jc"
    )
    if fields:
        picked = ", ".join(f'_j."{name}"' for name in fields)
        joins += (
            f" LEFT JOIN LATERAL (SELECT {picked}"
            f" FROM {join_table_ref} AS _j WHERE {match}"
            f" ORDER BY _j.gid LIMIT 1) AS _jf ON TRUE"
        )
        for name in fields:
            columns += f', _jf."{name}" AS "{SPATIAL_JOIN_FIELD_PREFIX}{name}"'
    return columns, joins


def render_spatial_join_match_count(
    src_table_ref: str, join_table_ref: str, *, bbox: list[float] | None = None
) -> str:
    """Count matched PAIRS across the WHOLE source (fix(#953)).

    The geometry preview is capped at ``PREVIEW_FEATURE_CAP`` rows, so
    summing its per-row counts would answer "how many points are in these
    500 polygons" while the map says nothing about the cap — worse than no
    number, since it looks like the answer. This runs as its own statement,
    bounded by the sandbox statement timeout rather than a row cap, since it
    returns one row however large the inputs are.

    Built from ``render_spatial_join`` rather than a second hand-written
    predicate: a total that disagrees with the per-feature counts on the
    map is the one failure mode this field cannot afford, and one renderer
    is what makes disagreement impossible. It also inherits the
    per-source-row ST_MakeValid hoist, without which this statement has the
    same 100x+ blow-up the per-row counts did.

    ``bbox`` (fix(#727)) scopes ``_src`` the same way the
    intersect count does — WHOLE means the request's bbox when one was
    sent. Unlike intersect's, this is a genuinely SEPARATE statement from
    the geometry preview: spatial_join is 1:1 and never returns early out
    of ``build_preview_sql``'s shared WHERE composition, so its geometry
    rows are already bbox-scoped there — this uncapped statement needs its
    own copy of the same filter to describe the same extent the map does.
    """
    _, joins = render_spatial_join(join_table_ref, src="_src")
    bbox_predicate = f" AND {render_bbox_predicate(bbox, src='_src')}" if bbox else ""
    return (
        f"SELECT COALESCE(sum(_jc.{SPATIAL_JOIN_COUNT_COLUMN}), 0)::bigint"
        f" AS match_count"
        f" FROM {src_table_ref} AS _src{joins}"
        f" WHERE _src.geom_4326 IS NOT NULL{bbox_predicate}"
    )


def render_spatial_join_expr() -> tuple[str, str]:
    """A spatial join's per-row geometry: the source feature, as stored (#953).

    Deliberately NOT ST_MakeValid'd, unlike operations that transform the
    geometry anyway: those repair the input for free, but here the output
    IS the input, so a silently repaired copy would change data the user
    never asked to touch. Validity is still handled where it matters,
    inside the join predicate (``render_spatial_join``).
    """
    return "geom_4326", ""
