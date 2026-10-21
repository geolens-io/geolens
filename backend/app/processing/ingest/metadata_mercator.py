"""The Web Mercator clip, the 0..360 longitude convention, and their CRS gates.

Shifting a 0..360 source instead of clipping it is what lets an ingest
produce a table that honestly crosses ±180, which the seam-aware extent in
``metadata_extent`` then reports.

The ``srtext`` regexes and the inline ``GEOG(CS|CRS)`` test in
``_mercator_envelope_degenerates`` live with their callers rather than in
``core.geo`` because they're SQL predicates over ``spatial_ref_sys`` with no
Python-side CRS object. The two deliberately disagree on wrapped CRSs, and
keeping both in one file makes that checkable by reading;
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
# This is a box, not a latitude cutoff: it bounds X at ±180 too, so a point
# at lon 400 is dropped by the X bound at an ordinary latitude, and the
# warning built from these counts must not blame latitude.
_MERCATOR_SAFE_ENVELOPE = "ST_MakeEnvelope(-180, -85.06, 180, 85.06, 4326)"

# Matches the WKT1 (GEOGCS) and WKT2 (GEOGCRS) spellings PostGIS ships for
# lon/lat CRSs (4326/4979/4269 match; projected 2263/3857 don't).
#
# The anchor is load-bearing. Unanchored, it would match
# `BOUNDCRS[SOURCECRS[GEOGCS[... UNIT["grad"...` as geographic, and
# `_shift_zero_to_360_longitudes` would subtract 360 from a CRS whose full
# turn is 400 grads, silently corrupting coordinates
# (tests/test_wkt_is_geographic.py). So this predicate deliberately
# disagrees with `core.geo.wkt_is_geographic` on wrapped CRSs (BOUNDCRS,
# COMPD_CS): declining to shift is safe (the data is clipped and reported
# instead), shifting wrongly is not. tests/test_crs_degree_agreement.py
# checks it never fires where PROJ says the axes aren't degrees.
_GEOGRAPHIC_SRTEXT_RE = "^GEOG(CS|CRS)"

# Geographic is not degree-based: 14 stock PostGIS SRIDs are GEOGCS in grads
# (the Paris-meridian family, e.g. 4807 NTF), where a full circle is 400, so
# translating by -360 would move a feature wrong. One pattern matches WKT1
# (`UNIT["degree"`) and WKT2 (`ANGLEUNIT["degree"`, which contains the WKT1
# substring); the prefix test above keeps projected CRSs out despite their
# nested GEOGCS also carrying `UNIT["degree"`.
_DEGREE_UNIT_SRTEXT_RE = 'UNIT\\["degree'


async def _shift_zero_to_360_longitudes(
    session: AsyncSession, table_name: str, schema: str, src_srid: int
) -> bool:
    """Shift a 0..360-convention source into -180..180. True when it shifted.

    A 0..360-convention source (common in ocean and climate data) is not
    out-of-range data: clipping it to the Mercator envelope would silently
    delete everything east of lon 180. A single-condition guard misfires on
    this class of problem, so *all four* must hold before anything moves:

    1. Geometry CRS is lon/lat AND angular unit is degrees. A projected CRS
       has no meaningful "longitude"; a grads-based CRS has a 400-unit full
       circle, so -360 is not a whole turn.
    2. Table-wide min X >= 0. Any negative longitude means the source is
       already -180..180, and mixing both conventions is ambiguous.
    3. Table-wide max X > 180. Separates a real 0..360 source from one
       legitimately confined to 0..180 (Africa/Europe/Asia).
    4. Table-wide max X <= 360. Past 360 is wrong units or corrupt
       coordinates, not this convention; those are left to the clamp.

    Only rows whose own min X is >= 180 are translated. A feature straddling
    lon 180 needs an antimeridian split, not a translate; it stays put and
    is reported by ``clip_to_mercator_bounds``'s accounting.
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

    # The raw (unfolded) coordinate range is what this convention probe
    # needs; it is not a geographic extent.
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

    A CRS with a narrow area of validity can collapse the global Mercator
    safe envelope under transform (EPSG:4807 NTF Paris grads: every X
    becomes 197.396), silently emptying the table via the clip's
    intersection. Against a stock ``spatial_ref_sys``, 4415 of 8500 SRIDs
    collapse or go zero-area and another 108 error outright: a class, not a
    corner case.

    Degenerate means any of:

    - zero/negative area or a collapsed X/Y range (EPSG:4807, every UTM
      zone, France's 2154, most national grids);
    - a sliver: area under 1e-6 of its own bbox (EPSG:2263 leaves a
      19-sq-ft bowtie in a 3e16 sq ft bbox; EPSG:5070 a 0.04 m² one):
      positive area, still data-destroying;
    - for a projected CRS, an envelope under 1000 linear units in either
      dimension (EPSG:27700 collapses to a 0.005 m² square, ratio 1 so the
      sliver test misses it; polar stereographic 3031 to ~4 m). Absolute,
      not relative to the table's extent, because a 3857 table genuinely
      beyond ±20 037 508 m is wider than its transformed envelope and is
      exactly what the clip trims. Only projected CRSs are tested, since
      geographic units are degrees and can't collapse this way; the test
      sees through COMPD_CS, so a compound geographic CRS like stock 5498
      (NAD83+NAVD88) still counts as degrees;
    - the transform raising, as the clip's own UPDATE would. Probed inside a
      SAVEPOINT so the surrounding transaction stays usable.
    """
    probe = text(
        f"WITH env AS (SELECT ST_Transform({_MERCATOR_SAFE_ENVELOPE}, :srid) AS e) "
        f"SELECT "
        f"  e IS NULL OR ST_IsEmpty(e) OR ST_Area(e) <= 0 "
        f"  OR ST_XMin(e) >= ST_XMax(e) OR ST_YMin(e) >= ST_YMax(e) "
        f"  OR ST_Area(e) < 1e-6 * ((ST_XMax(e) - ST_XMin(e)) "
        f"                        * (ST_YMax(e) - ST_YMin(e))) "
        f"  OR ( "
        # Geographic here means a GEOG keyword and no PROJ keyword anywhere
        # (every projected WKT1 nests a GEOGCS), as in
        # core.geo.wkt_is_geographic. That sees through COMPD_CS, so a
        # compound geographic CRS (stock 5498, NAD83+NAVD88) doesn't trip the
        # 1000-unit floor. Seeing through a wrapper is right for a size floor
        # and unsafe for the 0..360 shift (a CRS whose turn may be 400
        # grads), so `_GEOGRAPHIC_SRTEXT_RE` deliberately disagrees on
        # wrapped CRSs; tests/test_crs_degree_agreement.py pins both.
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
    Z or M column needs that dimension forced back after `ST_Intersection`
    or the UPDATE fails with `Column has Z/M dimension but geometry does
    not`. For Z this lands the clipped vertices at 0; GEOS cannot
    interpolate a measure the same way, so a measured feature that actually
    crosses the envelope raises instead of silently zeroing its M values. A
    feature entirely outside the envelope still drops, since it has no
    measure left to lose.

    Returns the clip accounting (``dropped_features``,
    ``clipped_features``, ``polar_only``) so the caller can surface loss at
    the point it happens. Returns None when the table has no registered ``geom``
    metadata. Raises ``ValueError`` when a measured feature crosses the
    envelope; the ingest task's failure handling turns this into a job
    failure naming the count.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)

    geom_meta = await session.execute(
        text(
            "SELECT gc.srid, postgis_typmod_type(a.atttypmod) AS typmod_type "
            "FROM geometry_columns gc "
            "JOIN pg_class c ON c.relname = gc.f_table_name "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "  AND n.nspname = gc.f_table_schema "
            "JOIN pg_attribute a ON a.attrelid = c.oid "
            "  AND a.attname = gc.f_geometry_column AND NOT a.attisdropped "
            "WHERE gc.f_table_schema = :schema "
            "  AND gc.f_table_name = :table_name "
            "  AND gc.f_geometry_column = 'geom'"
        ).bindparams(schema=schema, table_name=table_name)
    )
    row = geom_meta.first()
    if row is None:
        return None  # column has no registered metadata — nothing safe to clip
    src_srid = int(row[0])
    # Restore the dimensions the column declares; ST_Force3D on an XYM column
    # would invent a Z instead of keeping the M.
    typmod = (row[1] or "").upper()
    if typmod.endswith("ZM"):
        force_dims = "ST_Force4D"
    elif typmod.endswith("Z"):
        force_dims = "ST_Force3D"
    elif typmod.endswith("M"):
        force_dims = "ST_Force3DM"
    else:
        force_dims = None

    shifted = await _shift_zero_to_360_longitudes(session, table_name, schema, src_srid)

    if src_srid == 4326:
        envelope = _MERCATOR_SAFE_ENVELOPE
    else:
        envelope = f"ST_Transform({_MERCATOR_SAFE_ENVELOPE}, {src_srid})"
        # The guard runs after the 0..360 shift above, so skipping the clip
        # for a narrow-validity CRS still leaves the shift applied.
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

    if typmod.endswith("M"):  # PointM and PointZM both end in M
        # See the docstring: a measured feature that crosses the envelope
        # cannot be clipped without losing its M values.
        crossing = await session.scalar(
            text(
                f"SELECT count(*) FROM {_qtable(table_name, schema=schema)} "
                f"WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) "
                f"  AND ST_Intersects(geom, {envelope}) "
                f"  AND NOT ST_CoveredBy(geom, {envelope})"
            )
        )
        if crossing:
            noun, verb = (
                ("feature", "extends") if crossing == 1 else ("features", "extend")
            )
            raise ValueError(
                f"{crossing} {noun} in this measured (M) layer {verb} past Web "
                "Mercator's latitude limit (±85.06°), and clipping would lose the "
                "measure values. Trim the data to that limit, then import again."
            )

    clipped = f"ST_CollectionExtract(ST_Intersection(geom, {envelope}), ST_Dimension(geom) + 1)"
    if force_dims is not None:
        clipped = f"{force_dims}({clipped})"

    # Count what the clip destroyed in the same statement that destroys it.
    # Rows that were already empty are excluded so they cannot inflate the
    # counts. `oob` is read from the geometry before the update: coordinates past
    # longitude ±180° or latitude ±90° are not polar data. Other CRSs are not
    # classified, so they never claim polar-only.
    out_of_range = (
        "ST_XMin(geom) < -180 OR ST_XMax(geom) > 180 "
        "OR ST_YMin(geom) < -90 OR ST_YMax(geom) > 90"
        if src_srid == 4326
        else "true"
    )
    tref = _qtable(table_name, schema=schema)
    counts = (
        await session.execute(
            text(
                f"WITH cand AS ("
                f"  SELECT ctid AS row_id, ({out_of_range}) AS oob FROM {tref} "
                f"  WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) "
                f"    AND NOT ST_CoveredBy(geom, {envelope})"
                f"), clip AS ("
                f"  UPDATE {tref} AS t SET geom = {clipped} FROM cand "
                f"  WHERE t.ctid = cand.row_id "
                f"  RETURNING t.geom AS new_geom, cand.oob"
                f") SELECT "
                f"count(*) FILTER (WHERE new_geom IS NULL OR ST_IsEmpty(new_geom)), "
                f"count(*) FILTER (WHERE new_geom IS NOT NULL AND NOT ST_IsEmpty(new_geom)), "
                f"count(*) > 0 AND NOT COALESCE(bool_or(oob), false) "
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
    # No internal commit: the caller (_finalize_ingest) owns the phase-2
    # commit boundary, so a downstream failure rolls back this clip atomically.
    counts_out: "MercatorClipCounts" = {
        "shifted_longitudes": shifted,
        "dropped_features": dropped_features,
        "clipped_features": clipped_features,
    }
    if counts is not None and counts[2]:
        counts_out["polar_only"] = True
    return counts_out
