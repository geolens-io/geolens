"""The Web Mercator clip, the 0..360 longitude convention, and their CRS gates.

Split out of ``metadata.py`` (#1042); #888/#899/#906/#961 all landed on
these three functions, which is why they share a file. The #934 seam-aware
extent work in ``metadata_extent`` is the downstream consequence: shifting
instead of clipping is what lets an ingest produce a table that honestly
crosses ±180.

The ``srtext`` regexes and the inline ``GEOG(CS|CRS)`` test in
``_mercator_envelope_degenerates`` live with their callers rather than in
``core.geo`` because they're SQL predicates over ``spatial_ref_sys`` with no
Python-side CRS object, and because #961 made them a standing sync
obligation: the two DELIBERATELY disagree on wrapped CRSs, and keeping both
halves in one file is what makes that checkable by reading.
``tests/test_crs_degree_agreement.py`` is the gate.
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


# Web Mercator (EPSG:3857) can't represent latitudes beyond ±85.06°;
# geometries past this (e.g. Antarctica at -90°) cause a ST_Transform
# tolerance error.
#
# fix(#899): this is a box, not a latitude cutoff — it bounds X at
# ±180 too, so a point at lon 400 is dropped by the X bound at an ordinary
# latitude; the warning built from these counts must not blame latitude.
_MERCATOR_SAFE_ENVELOPE = "ST_MakeEnvelope(-180, -85.06, 180, 85.06, 4326)"

# fix(#888): matches WKT1 (GEOGCS) and WKT2 (GEOGCRS) spellings PostGIS
# ships for lon/lat CRSs (4326/4979/4269 match; projected 2263/3857 don't).
#
# fix(#961): the ANCHOR is load-bearing. Un-anchored, it would match
# `BOUNDCRS[SOURCECRS[GEOGCS[... UNIT["grad"...` as geographic, and
# `_shift_zero_to_360_longitudes` would subtract 360 from a CRS whose full
# turn is 400 grads — silent coordinate corruption (pinned by
# tests/test_wkt_is_geographic.py). This predicate therefore deliberately
# disagrees with `core.geo.wkt_is_geographic` on wrapped CRSs (BOUNDCRS,
# COMPD_CS): declining to shift here is safe (clipped + reported instead),
# shifting wrongly is not. tests/test_crs_degree_agreement.py enforces
# soundness — never firing where PROJ says axes aren't degrees.
_GEOGRAPHIC_SRTEXT_RE = "^GEOG(CS|CRS)"

# fix(#899): geographic != degree-based. 14 stock PostGIS SRIDs are
# GEOGCS with grads (Paris-meridian family, e.g. 4807 NTF) where a full
# circle is 400, not 360 — translating by -360 would move a feature wrong,
# so unit must be degrees before anything shifts. Matches WKT1
# (`UNIT["degree"`) and WKT2 (`ANGLEUNIT["degree"`, containing the WKT1
# substring) in one pattern; the prefix test above keeps projected CRSs out
# despite their nested GEOGCS also carrying `UNIT["degree"`.
_DEGREE_UNIT_SRTEXT_RE = 'UNIT\\["degree'


async def _shift_zero_to_360_longitudes(
    session: AsyncSession, table_name: str, schema: str, src_srid: int
) -> bool:
    """Shift a 0..360-convention source into -180..180. True when it shifted.

    fix(#888): a 0..360-convention source (common in ocean/climate data) is
    not out-of-range data — clipping to the Mercator envelope would silently
    delete everything east of lon 180. #883 showed a single-condition guard
    on this class of problem is a coin flip, so *all four* must hold before
    anything moves:

    1. Geometry CRS is lon/lat AND angular unit is degrees. A projected CRS
       has no meaningful "longitude"; a grads-based CRS has a 400-unit full
       circle, so -360 is not a whole turn (fix(#899)).
    2. Table-wide min X >= 0 — any negative longitude means the source is
       already -180..180, and mixing both conventions is ambiguous.
    3. Table-wide max X > 180 — separates a real 0..360 source from one
       legitimately confined to 0..180 (Africa/Europe/Asia).
    4. Table-wide max X <= 360 — past 360 is wrong units or corrupt
       coordinates, not this convention; leave those to the clamp.

    Only rows whose own min X is >= 180 are translated. A feature straddling
    lon 180 needs an antimeridian split (#884/#886), not a translate; it
    stays put and is reported by ``clip_to_mercator_bounds``'s accounting.
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

    fix(#906): a CRS with a narrow area of validity can collapse the global
    Mercator safe envelope under transform (EPSG:4807 NTF Paris grads: every
    X becomes 197.396), silently emptying the table via the clip's
    intersection. Enumerated against a stock ``spatial_ref_sys``: 4415 of
    8500 SRIDs collapse or zero-area, another 108 error outright — a class,
    not a corner case.

    Degenerate means any of:

    - zero/negative area or a collapsed X/Y range (EPSG:4807, every UTM
      zone, France's 2154, most national grids);
    - a sliver: area under 1e-6 of its own bbox (EPSG:2263 leaves a
      19-sq-ft bowtie in a 3e16 sq ft bbox; EPSG:5070 a 0.04 m² one) —
      positive area, still data-destroying;
    - for a projected CRS, an envelope under 1000 linear units in either
      dimension (EPSG:27700 collapses to a 0.005 m² square, ratio 1 so the
      sliver test misses it; polar stereographic 3031 to ~4 m). Absolute,
      not relative to the table's extent, because a 3857 table genuinely
      beyond ±20 037 508 m is WIDER than its transformed envelope and is
      exactly what the clip trims (fix(#906)). Guarded to
      projected CRSs since geographic units are degrees and can't collapse
      this way; sees through COMPD_CS (fix(#906)) so a compound
      geographic CRS like stock 5498 (NAD83+NAVD88) still counts as degrees;
    - the transform raising — the clip's own UPDATE would raise identically.
      Probed inside a SAVEPOINT so the surrounding transaction stays usable.
    """
    probe = text(
        f"WITH env AS (SELECT ST_Transform({_MERCATOR_SAFE_ENVELOPE}, :srid) AS e) "
        f"SELECT "
        f"  e IS NULL OR ST_IsEmpty(e) OR ST_Area(e) <= 0 "
        f"  OR ST_XMin(e) >= ST_XMax(e) OR ST_YMin(e) >= ST_YMax(e) "
        f"  OR ST_Area(e) < 1e-6 * ((ST_XMax(e) - ST_XMin(e)) "
        f"                        * (ST_YMax(e) - ST_YMin(e))) "
        f"  OR ( "
        # fix(#906): sees through COMPD_CS — a compound geographic
        # CRS (e.g. stock 5498, NAD83+NAVD88) starts with COMPD_CS but its
        # horizontal axes are degrees, so it must not trip the 1000-unit
        # floor. Geographic here means a GEOG keyword present and no PROJ
        # keyword anywhere (every projected WKT1 nests a GEOGCS) — same
        # logic as core.geo.wkt_is_geographic, in srtext form.
        # fix(#961): this predicate and the 0..360 gate's
        # `_GEOGRAPHIC_SRTEXT_RE` deliberately DISAGREE on wrapped CRSs
        # (unifying them was tried and reverted) — seeing through a wrapper
        # is right here (a size floor) and unsafe there (translating by 360
        # in a CRS whose turn may be 400 grads). Both halves are pinned by
        # tests/test_crs_degree_agreement.py.
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

    Only updates rows whose geometry actually extends beyond the bounds, a
    no-op for most datasets. ``schema`` defaults to ``"data"`` (single_tenant);
    multi_tenant callers pass ``_current_tenant_schema()``.

    Two CRS quirks the SQL handles: (1) the envelope is SRID 4326 and gets
    transformed to match the column's SRID, else PostGIS raises `coveredby:
    Operation on mixed SRID geometries`; (2) the envelope is always 2D, so a
    3D column (e.g. `MultiPointZ`) needs `ST_Force3D` after
    `ST_Intersection` or the UPDATE fails with `Column has Z dimension but
    geometry does not` (clipped vertices land at z=0).

    fix(#888): returns the clip accounting (``dropped_features``,
    ``clipped_features``) so the caller can surface loss at the point it
    happens. Returns None when the table has no registered ``geom`` metadata.
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
