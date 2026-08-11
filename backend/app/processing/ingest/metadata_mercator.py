"""The Web Mercator clip, the 0..360 longitude convention, and their CRS gates.

Split out of ``metadata.py`` (#1042). The cluster that kept growing: #888
(shift a 0..360 source instead of clipping it), #899 (angular units), #906
(degenerate envelopes) and #961 (the predicate disagreement) all landed on
these three functions. The #934 seam-aware extent work is their downstream
consequence and lives in ``metadata_extent``: shifting instead of clipping is
what lets an ordinary ingest produce a table that honestly crosses ±180.

The two ``srtext`` regexes and the inline ``GEOG(CS|CRS)`` test inside
``_mercator_envelope_degenerates`` live with their callers rather than beside
``core.geo``'s helpers for two reasons. They are SQL predicates evaluated
inside a query against ``spatial_ref_sys``, where there is no Python-side CRS
object to hand to PROJ; and #961 recorded them as a standing sync obligation
whose whole content is that the two DELIBERATELY disagree on wrapped CRSs.
Keeping both halves of that disagreement in one file is what makes it
checkable by reading. ``tests/test_crs_degree_agreement.py`` is the gate.
"""

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ingest.metadata_sql import _qtable, _validate_table_name

if TYPE_CHECKING:
    from app.processing.ingest.warnings import MercatorClipCounts

logger = structlog.stdlib.get_logger(__name__)


# Web Mercator (EPSG:3857) cannot represent latitudes beyond ±85.06°.
# Geometries extending past this (e.g. Antarctica at -90°) cause
# "transform: tolerance condition error" in ST_Transform.
#
# fix(#899 codex r1): this is a box, not a latitude cutoff — it bounds X at
# ±180 as well. A point at lon 400 is dropped by the X bound with a perfectly
# ordinary latitude, so the warning built from these counts must not tell the
# user that latitude was the problem.
_MERCATOR_SAFE_ENVELOPE = "ST_MakeEnvelope(-180, -85.06, 180, 85.06, 4326)"

# fix(#888): matches the WKT1 (GEOGCS) and WKT2 (GEOGCRS) spellings PostGIS
# ships in spatial_ref_sys.srtext for lon/lat CRSs. 4326/4979/4269 match;
# 2263/3857 (projected, X in feet/metres) do not.
#
# fix(#961 review): the ANCHOR is load-bearing and must stay, even though it
# makes this predicate disagree with `core.geo.wkt_is_geographic` and with the
# degenerate-envelope floor below on wrapped CRSs (BOUNDCRS, COMPD_CS). Those
# two can afford to see through a wrapper; this one cannot, and the reason is
# the same one `core.geo._parse_crs` documents at length: a flat scan cannot
# decide which subtree a token belongs to.
#
# Concretely. Un-anchoring lets `BOUNDCRS[SOURCECRS[GEOGCS[... UNIT["grad"...`
# match as geographic, and `_DEGREE_UNIT_SRTEXT_RE` below is a flat substring
# scan that would then find an unrelated `degree` on the TARGET CRS or a
# PRIMEM and report degrees. `_shift_zero_to_360_longitudes` would subtract
# 360 from coordinates whose full turn is 400 grads — silent corruption, and
# the shape is real enough that `tests/test_wkt_is_geographic.py::
# test_boundcrs_reports_the_source_crs_units_not_the_targets` already pins it
# on the Python side.
#
# Declining to shift is safe: the source is then clipped and REPORTED by
# `clip_to_mercator_bounds`'s accounting, which is a visible outcome. Shifting
# wrongly is not. So this gate stays deliberately incomplete, and the property
# tests/test_crs_degree_agreement.py enforces is soundness — it never fires
# where PROJ says the axes are not degrees — rather than agreement.
_GEOGRAPHIC_SRTEXT_RE = "^GEOG(CS|CRS)"

# fix(#899 codex r1): geographic is not the same as degree-based. 14 SRIDs in a
# stock PostGIS spatial_ref_sys are GEOGCS with an angular unit of grads — the
# Paris-meridian family, 4807 NTF (Paris) and relatives — where a full circle
# is 400, not 360. Translating one of those by -360 would move a valid feature
# to a wrong place, so the unit has to be degrees before anything shifts. The
# pattern covers WKT1 (`UNIT["degree"`) and WKT2 (`ANGLEUNIT["degree"`) in one
# go, since the WKT2 spelling contains the WKT1 substring. The prefix test
# above is what keeps a projected CRS out: 3857's srtext also carries
# `UNIT["degree"` inside its nested GEOGCS.
_DEGREE_UNIT_SRTEXT_RE = 'UNIT\\["degree'


async def _shift_zero_to_360_longitudes(
    session: AsyncSession, table_name: str, schema: str, src_srid: int
) -> bool:
    """Shift a 0..360-convention source into -180..180. True when it shifted.

    fix(#888): a source written in the 0..360 Pacific convention (common in
    ocean and climate data) is not out-of-range data — it is the same world
    with a different origin. Clipping it to the Mercator envelope silently
    deletes everything east of lon 180; translating it preserves every
    feature. #883 showed that a single-condition guard on this class of
    problem is a coin flip, so *all four* of these must hold before anything
    moves:

    1. The geometry column's CRS is lon/lat AND its angular unit is degrees.
       "Longitude" is meaningless in a projected CRS, where X is metres or feet
       and 300 is not out of range; and in a grads-based geographic CRS a full
       circle is 400, so -360 is not a whole turn (fix(#899 codex r1)).
    2. Table-wide min X >= 0. Any negative longitude means the source is
       already -180..180; a source mixing both conventions is ambiguous, so
       refuse to guess.
    3. Table-wide max X > 180. This is the condition that separates a real
       0..360 source from a dataset legitimately confined to the eastern
       hemisphere (0..180 — Africa/Europe/Asia), which must not be flung
       into -360..-180.
    4. Table-wide max X <= 360. Past 360 is not the 0..360 convention at all
       (wrong units, corrupt coordinates); leave those to the clamp.

    Only rows whose *own* min X is >= 180 are translated, so a feature that
    is already inside -180..180 keeps its exact coordinates. A feature that
    straddles lon 180 in such a source needs an antimeridian split (#884 /
    #886) rather than a translate: it stays put and is then reported by the
    clip accounting in ``clip_to_mercator_bounds``.
    """
    tref = _qtable(table_name, schema=schema)

    is_degree_lonlat = await session.scalar(
        text(
            "SELECT srtext ~* :geographic AND srtext ~* :degree_unit "
            "FROM spatial_ref_sys WHERE srid = :srid"
        ).bindparams(
            geographic=_GEOGRAPHIC_SRTEXT_RE,
            degree_unit=_DEGREE_UNIT_SRTEXT_RE,
            srid=src_srid,
        )
    )
    if not is_degree_lonlat:
        return False

    # The raw (unfolded) coordinate range is exactly what is wanted here —
    # this is a convention probe, not a geographic extent, so it is not the
    # antimeridian-naive extent fold tracked by #886.
    bounds = (
        await session.execute(
            text(
                f"SELECT ST_XMin(bb), ST_XMax(bb) FROM (SELECT ST_Extent(geom) AS bb FROM {tref}) s"
            )
        )
    ).first()
    if bounds is None or bounds[0] is None or bounds[1] is None:
        return False
    min_x, max_x = float(bounds[0]), float(bounds[1])
    if min_x < 0 or max_x <= 180 or max_x > 360:
        return False

    result = await session.execute(
        text(
            f"UPDATE {tref} SET geom = ST_Translate(geom, -360, 0) "
            f"WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) AND ST_XMin(geom) >= 180"
        )
    )
    logger.info(
        "Shifted 0..360 longitudes into -180..180 before the Mercator clip",
        table=table_name,
        schema=schema,
        srid=src_srid,
        min_x=min_x,
        max_x=max_x,
        rows_shifted=result.rowcount,
    )
    return True


async def _mercator_envelope_degenerates(
    session: AsyncSession, table_name: str, schema: str, src_srid: int
) -> bool:
    """True when the safe envelope collapses under ST_Transform into ``src_srid``.

    fix(#906): for a CRS with a narrow area of validity, transforming the
    global Mercator safe envelope collapses it — in EPSG:4807 (NTF Paris,
    grads) every X of the envelope becomes 197.396 — and the clip's
    intersection would then silently empty the entire table. Enumerated
    against a stock ``spatial_ref_sys``: 4415 of 8500 SRIDs produce a
    zero-area or collapsed envelope and another 108 error outright, so this
    is a class, not an exotic corner.

    Degenerate means any of:

    - zero (or negative) area, or a collapsed X/Y range — the hard collapse
      (EPSG:4807, every UTM zone, France's 2154, most national grids);
    - a sliver: area under 1e-6 of its own bbox area — EPSG:2263 leaves a
      19-square-foot bowtie stretched across a 3e16 sq ft bbox, and EPSG:5070
      a 0.04 m² one; positive area, still data-destroying;
    - for a projected CRS, an envelope bbox under 1000 linear units in either
      dimension — EPSG:27700 collapses to a 0.005 m² *square* (ratio 1, so
      the sliver test misses it) and polar stereographic 3031 to ~4 m across.
      The floor is absolute, not relative to the table's extent, because a
      3857 table with features genuinely beyond ±20 037 508 m is WIDER than
      its correctly transformed envelope and is exactly what the clip exists
      to trim (fix(#906 codex r1)). 1000 is orders of magnitude under any
      sane world envelope in any projected linear unit (metres, feet, even
      kilometres give ~40 075) and orders over every measured collapse.
      Guarded to projected CRSs (see the four-mechanism table on #939)
      because geographic units are degrees (the world is 360 wide) and a
      geographic transform cannot collapse. The geographic test sees
      through COMPD_CS (fix(#906 codex r2)): a compound geographic CRS like
      stock 5498 (NAD83 + NAVD88) is degrees despite its prefix;
    - the transform raising — the clip's own UPDATE would raise identically,
      turning a bounds check into a failed ingest. Probed inside a SAVEPOINT
      so the surrounding phase-2 transaction stays usable.
    """
    probe = text(
        f"WITH env AS (SELECT ST_Transform({_MERCATOR_SAFE_ENVELOPE}, :srid) AS e) "
        f"SELECT "
        f"  e IS NULL OR ST_IsEmpty(e) OR ST_Area(e) <= 0 "
        f"  OR ST_XMin(e) >= ST_XMax(e) OR ST_YMin(e) >= ST_YMax(e) "
        f"  OR ST_Area(e) < 1e-6 * ((ST_XMax(e) - ST_XMin(e)) "
        f"                        * (ST_YMax(e) - ST_YMin(e))) "
        f"  OR ( "
        # fix(#906 codex r2): the floor's geographic test must see through
        # COMPD_CS — a compound geographic CRS (e.g. stock 5498, NAD83 +
        # NAVD88) starts with COMPD_CS but its horizontal axes are degrees,
        # and its valid 360x170-degree envelope would trip the 1000-unit
        # floor. Geographic-horizontal here means: a GEOG keyword present and
        # no PROJ keyword anywhere (every projected WKT1 nests a GEOGCS, so
        # the PROJ test must win) — the same keyword logic as
        # core.geo.wkt_is_geographic, in srtext form.
        # fix(#961 review): this predicate and the 0..360 gate's
        # `_GEOGRAPHIC_SRTEXT_RE` deliberately DISAGREE on wrapped CRSs, and
        # unifying them was tried and reverted. Seeing through a wrapper is
        # right here (the consequence is a size floor) and unsafe there (the
        # consequence is translating geometry by 360 in a CRS whose turn may
        # be 400 grads). The asymmetry is the decision, not an oversight; both
        # halves are pinned by tests/test_crs_degree_agreement.py.
        f"    NOT COALESCE((SELECT srtext ~* 'GEOG(CS|CRS)' "
        f"                     AND srtext !~* 'PROJ(CS|CRS)' "
        f"                  FROM spatial_ref_sys "
        f"                  WHERE srid = :srid), false) "
        f"    AND LEAST(ST_XMax(e) - ST_XMin(e), ST_YMax(e) - ST_YMin(e)) < 1000) "
        f"FROM env"
    ).bindparams(srid=src_srid)
    try:
        async with session.begin_nested():
            result = await session.execute(probe)
            return bool(result.scalar_one())
    except DBAPIError:
        logger.warning(
            "Mercator envelope transform failed while probing for degeneracy; "
            "treating the envelope as unusable in this CRS",
            table=table_name,
            schema=schema,
            srid=src_srid,
            exc_info=True,
        )
        return True


async def clip_to_mercator_bounds(
    session: AsyncSession, table_name: str, schema: str = "data"
) -> "MercatorClipCounts | None":
    """Clip geometries to the Web Mercator safe envelope (±85.06° lat).

    Only updates rows whose geometry actually extends beyond the bounds,
    so this is a no-op for most datasets.

    ``schema`` defaults to ``"data"`` for single_tenant backward compatibility.
    In multi_tenant callers pass ``_current_tenant_schema()`` (CR-03, Phase 1209).

    Two CRS-related quirks the SQL has to handle:

    1. Envelope is in SRID 4326. If the column's SRID differs (4979 / any
       projected CRS), transform the envelope to match — otherwise PostGIS
       raises `coveredby: Operation on mixed SRID geometries`.
    2. The envelope is always 2D. If the column is declared 3D (e.g.
       `MultiPointZ` for a 4979 source with elevation), `ST_Intersection`
       drops Z and the UPDATE then fails with `Column has Z dimension but
       geometry does not`. Wrap the result in `ST_Force3D` to put Z back
       (clipped vertices land at z=0, which is acceptable for the few rows
       that get clipped past ±85° lat).

    fix(#888): returns the clip accounting — how many rows lost geometry
    entirely (``dropped_features``) and how many survived in reduced form
    (``clipped_features``) — so the caller can tell the user at the point of
    loss instead of leaving them to hit "Analysis produced no features to
    save" three steps later. Returns None when the table has no registered
    ``geom`` metadata (nothing was inspected, let alone clipped).
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)

    geom_meta = await session.execute(
        text(
            "SELECT srid, coord_dimension FROM geometry_columns "
            "WHERE f_table_schema = :schema "
            "  AND f_table_name = :table_name "
            "  AND f_geometry_column = 'geom'"
        ).bindparams(schema=schema, table_name=table_name)
    )
    row = geom_meta.first()
    if row is None:
        return None  # column has no registered metadata — nothing safe to clip
    src_srid = int(row[0])
    column_is_3d = int(row[1]) >= 3

    shifted = await _shift_zero_to_360_longitudes(session, table_name, schema, src_srid)

    if src_srid == 4326:
        envelope = _MERCATOR_SAFE_ENVELOPE
    else:
        envelope = f"ST_Transform({_MERCATOR_SAFE_ENVELOPE}, {src_srid})"
        # fix(#906): the guard runs AFTER the 0..360 shift above — that
        # ordering is load-bearing (#888/#899): skipping the clip for a
        # narrow-validity CRS must still leave the shift applied.
        if await _mercator_envelope_degenerates(session, table_name, schema, src_srid):
            logger.warning(
                "Skipping the Web Mercator clip: the safe envelope degenerates "
                "in the source CRS and the intersection would destroy data",
                table=table_name,
                schema=schema,
                srid=src_srid,
            )
            return {
                "shifted_longitudes": shifted,
                "dropped_features": 0,
                "clipped_features": 0,
                "clip_skipped": True,
            }

    clipped = f"ST_CollectionExtract(ST_Intersection(geom, {envelope}), ST_Dimension(geom) + 1)"
    if column_is_3d:
        clipped = f"ST_Force3D({clipped})"

    # fix(#888): count what the clip destroyed in the same statement that
    # destroys it. Rows that were already empty are excluded from the WHERE so
    # they cannot inflate the counts (the clip was a no-op for them anyway).
    counts = (
        await session.execute(
            text(
                f"WITH clip AS ("
                f"  UPDATE {_qtable(table_name, schema=schema)} SET geom = {clipped} "
                f"  WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) "
                f"    AND NOT ST_CoveredBy(geom, {envelope}) "
                f"  RETURNING geom AS new_geom"
                f") SELECT "
                f"count(*) FILTER (WHERE new_geom IS NULL OR ST_IsEmpty(new_geom)), "
                f"count(*) FILTER (WHERE new_geom IS NOT NULL AND NOT ST_IsEmpty(new_geom)) "
                f"FROM clip"
            )
        )
    ).first()
    dropped_features = int(counts[0]) if counts is not None else 0
    clipped_features = int(counts[1]) if counts is not None else 0
    if dropped_features or clipped_features:
        logger.warning(
            "Geometry clipped to the Web Mercator safe envelope",
            table=table_name,
            schema=schema,
            dropped_features=dropped_features,
            clipped_features=clipped_features,
            shifted_longitudes=shifted,
        )
    # ING-02 / P2-02 (Phase 1076): no internal commit. The caller
    # (_finalize_ingest at tasks_common.py:821) owns the phase-2 commit
    # boundary so a downstream failure rolls back this clip atomically.
    return {
        "shifted_longitudes": shifted,
        "dropped_features": dropped_features,
        "clipped_features": clipped_features,
    }
