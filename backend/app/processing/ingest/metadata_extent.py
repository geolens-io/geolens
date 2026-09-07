"""Reading metadata back off a landed PostGIS table.

Split out of ``metadata.py`` (#1042). ``extract_metadata``'s CTE consolidates
``get_feature_count``, ``get_table_srid``, ``get_geometry_type`` and the
extent query into a single scan, falling back to those same four helpers one
at a time when a deployment can't run it — the CTE and the helpers must
agree line for line, so they're kept where a reader can see both.

``get_extent`` and the CTE also share the two extent corrections: the
antimeridian override in ``_seam_crossing_extent_wkt`` (#934) and the
degenerate POINT/LINESTRING padding (#430 BA-18).
"""

import re

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import seam_extent_wkt_for_table
from app.processing.ingest.metadata_sql import (
    _qtable,
    _sql_quote_ident,
    _validate_table_name,
)

logger = structlog.stdlib.get_logger(__name__)


_BOX3D_RE = re.compile(
    r"^BOX3D\("
    r"[-+0-9.eE]+\s+[-+0-9.eE]+\s+([-+0-9.eE]+),"
    r"[-+0-9.eE]+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)"
    r"\)$"
)


def _parse_box3d_z_bounds(box3d_text: str | None) -> tuple[float | None, float | None]:
    """Extract z_min/z_max from a ``BOX3D(...)`` string.

    ``ST_3DExtent`` is widely available where ``ST_Is3D`` may not be;
    parsing its output keeps compatibility with older extensions.
    """
    if not box3d_text:
        return None, None

    match = _BOX3D_RE.match(box3d_text)
    if match is None:
        return None, None

    return float(match.group(1)), float(match.group(2))


async def get_table_srid(
    session: AsyncSession, table_name: str, schema: str = "data"
) -> int | None:
    """Get the SRID of the geom column for a table in the given schema.

    ``schema`` defaults to ``"data"``; multi_tenant callers pass
    ``_current_tenant_schema()``.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)
    result = await session.execute(
        text("SELECT Find_SRID(:schema, :table_name, 'geom')").bindparams(
            schema=schema, table_name=table_name
        )
    )
    row = result.scalar_one_or_none()
    return int(row) if row is not None else None


# fix(#1057): map abstract OGC GML 3 geometry types (returned by
# PostGIS GeometryType() when the source WFS stores them, e.g. GeoServer's
# opengeo:countries) to the closest concrete subtype, since
# chk_datasets_geometry_type only allows the 7 concrete types (POINT,
# LINESTRING, POLYGON, MULTIPOINT, MULTILINESTRING, MULTIPOLYGON,
# GEOMETRYCOLLECTION). ``-nlt GEOMETRY`` (also #1057) relaxed the column
# type so ogr2ogr can load these, but leaves the stored subtype
# (MULTISURFACE / MULTICURVE / ...) as GeometryType(geom)'s answer.
_ABSTRACT_TO_CONCRETE_GEOMETRY_TYPE: dict[str, str] = {
    "MULTISURFACE": "MULTIPOLYGON",
    "MULTICURVE": "MULTILINESTRING",
    "COMPOUNDCURVE": "MULTILINESTRING",
    "COMPOUNDSURFACE": "MULTIPOLYGON",
    "SURFACE": "POLYGON",
    "CURVE": "LINESTRING",
    "POLYHEDRALSURFACE": "MULTIPOLYGON",
    "TIN": "MULTIPOLYGON",
    "TRIANGLE": "POLYGON",
}


def _normalize_geometry_type(value: str | None) -> str | None:
    """Normalize abstract OGC geometry type names to concrete subtypes.

    Returns the uppercased input unchanged when it is already a concrete
    type, ``None`` when the input is ``None`` or empty.
    """
    if not value:
        return None
    upper = value.upper()
    return _ABSTRACT_TO_CONCRETE_GEOMETRY_TYPE.get(upper, upper)


async def get_geometry_type(
    session: AsyncSession, table_name: str, *, schema: str = "data"
) -> str | None:
    """Get the geometry type of the first feature in the table.

    Returns the type in uppercase for consistent casing across all sources.
    Abstract GML 3 types (MultiSurface/MultiCurve/etc.) are normalized to the
    closest concrete equivalent so the value satisfies
    ``chk_datasets_geometry_type``.
    """
    result = await session.execute(
        text(
            # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
            f"SELECT GeometryType(geom) FROM "
            f"{_qtable(table_name, schema=schema)} LIMIT 1"
        )
    )
    value = result.scalar_one_or_none()
    return _normalize_geometry_type(value)


async def get_feature_count(
    session: AsyncSession, table_name: str, *, schema: str = "data"
) -> int:
    """Count the number of features (rows) in the table."""
    result = await session.execute(
        # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
        text(f"SELECT COUNT(*) FROM {_qtable(table_name, schema=schema)}")
    )
    return result.scalar_one()


async def _seam_crossing_extent_wkt(
    session: AsyncSession,
    table_name: str,
    *,
    schema: str,
    xmin: float | None,
    xmax: float | None,
) -> str | None:
    """Two-ring extent WKT when the table honestly crosses ±180, else None.

    fix(#934): ``xmin``/``xmax`` are the naive ``ST_Extent`` bounds already
    computed by the caller's query. A crossing dataset folded naively always
    spans more than 180 degrees (shifted-domain span is ``360 - width``, so
    the shifted domain only wins when ``width > 180``), letting the common
    non-crossing case skip the second aggregate scan entirely.
    """
    if xmin is None or xmax is None:
        return None
    if float(xmax) - float(xmin) <= 180.0:
        return None
    return await seam_extent_wkt_for_table(session, table_name, schema=schema)


async def get_extent(
    session: AsyncSession, table_name: str, *, schema: str = "data"
) -> str | None:
    """Get the 4326 extent WKT (or None for empty tables).

    fix(#934): a Pacific-crossing table (reachable since #888 shifts 0..360
    sources instead of clipping) must not store the naive fold (a
    near-global POLYGON); when the honest extent crosses the seam this
    returns the two-ring MULTIPOLYGON instead. Non-crossing extents stay
    byte-identical to the original query.

    fix(#430): spatial_extent admits POLYGON/MULTIPOLYGON only
    (chk_records_spatial_extent_type). ST_Extent of a single point or
    axis-collinear points casts to a rejected POINT/LINESTRING, crashing
    the reupload swap. Pad ONLY the degenerate cases into a valid sub-mm
    polygon; genuine extents stay byte-identical.
    """
    _validate_table_name(table_name)
    result = await session.execute(
        text(
            # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
            f"SELECT CASE "
            f"  WHEN ext IS NULL THEN NULL "
            f"  WHEN GeometryType(ext::geometry) = 'POLYGON' "
            f"    THEN ST_AsText(ST_SetSRID(ext::geometry, 4326)) "
            f"  ELSE ST_AsText(ST_Expand(ST_SetSRID(ext::geometry, 4326), 1e-9)) "
            f"END, "
            f"ST_XMin(ext::geometry), ST_XMax(ext::geometry) "
            f"FROM (SELECT ST_Extent(geom_4326) AS ext FROM "
            f"{_qtable(table_name, schema=schema)}) s"
        )
    )
    row = result.one_or_none()
    if row is None or row[0] is None:
        return None
    crossing = await _seam_crossing_extent_wkt(
        session, table_name, schema=schema, xmin=row[1], xmax=row[2]
    )
    return crossing if crossing is not None else row[0]


async def detect_3d_metadata(
    session: AsyncSession, table_name: str, *, schema: str = "data"
) -> dict:
    """Detect 3D geometry properties from a PostGIS table.

    Uses ``ST_NDims`` to determine whether any geometry is 3D and
    ``ST_3DExtent`` to derive z-range metadata.
    Returns dict with keys: is_3d, n_dims, z_min, z_max.
    All values are None if the table has no geometry or no rows.
    """
    _validate_table_name(table_name)

    _NO_3D = {"is_3d": None, "n_dims": None, "z_min": None, "z_max": None}

    has_geom = await _table_has_geometry(session, table_name, schema=schema)
    if not has_geom:
        return _NO_3D

    try:
        result = await session.execute(
            text(
                # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
                f"SELECT "
                f"  MAX(ST_NDims(geom)) AS n_dims, "
                f"  CASE "
                f"    WHEN MAX(ST_NDims(geom)) > 2 THEN ST_3DExtent(geom)::text "
                f"    ELSE NULL "
                f"  END AS extent_3d "
                f"FROM {_qtable(table_name, schema=schema)} "
                f"WHERE geom IS NOT NULL"
            )
        )
    except (
        Exception
    ):  # broad: ST_NDims/ST_3DExtent may not exist in older PostGIS; degrade gracefully
        logger.warning(
            "3d_metadata_detection_failed",
            table=table_name,
            hint="ST_NDims or ST_3DExtent may not be available in this PostGIS version",
        )
        return _NO_3D

    row = result.one_or_none()
    if row is None:
        return {"is_3d": False, "n_dims": 2, "z_min": None, "z_max": None}

    n_dims = row.n_dims if row.n_dims is not None else 2
    is_3d = bool(n_dims and n_dims > 2)
    z_min, z_max = _parse_box3d_z_bounds(row.extent_3d if is_3d else None)

    return {
        "is_3d": is_3d,
        "n_dims": int(n_dims) if n_dims is not None else None,
        "z_min": z_min,
        "z_max": z_max,
    }


async def promote_z_to_elev(
    session: AsyncSession,
    table_name: str,
    geometry_type: str | None,
    schema: str = "data",
) -> bool:
    """For 3D point geometries, extract ST_Z(geom) into an 'elev' numeric column.

    Only runs when: the geometry is 3D (caller must verify with
    detect_3d_metadata first), the geometry type is point-like (Point or
    MultiPoint), and an 'elev' column doesn't already exist. Returns True
    if the column was created.

    ``schema`` defaults to ``"data"``; multi_tenant callers pass
    ``_current_tenant_schema()``.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)

    if geometry_type is None:
        return False

    geom_upper = geometry_type.upper()
    if geom_upper not in ("POINT", "MULTIPOINT"):
        return False

    col_check = await session.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :t "
            "AND column_name = 'elev'"
        ).bindparams(schema=schema, t=table_name)
    )
    if col_check.scalar_one_or_none() is not None:
        return False

    try:
        await session.execute(
            text(
                # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
                f"ALTER TABLE {_qtable(table_name, schema=schema)} ADD COLUMN elev double precision"
            )
        )

        if geom_upper == "POINT":
            await session.execute(
                text(
                    # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
                    f"UPDATE {_qtable(table_name, schema=schema)} "
                    f"SET elev = ST_Z(geom) "
                    f"WHERE geom IS NOT NULL AND ST_NDims(geom) > 2"
                )
            )
        else:
            # MultiPoint: extract Z from first point in the multi
            await session.execute(
                text(
                    # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
                    f"UPDATE {_qtable(table_name, schema=schema)} "
                    f"SET elev = ST_Z(ST_GeometryN(geom, 1)) "
                    f"WHERE geom IS NOT NULL AND ST_NDims(geom) > 2"
                )
            )
    except Exception:  # broad: ST_Z/ST_NDims/ST_GeometryN may not be available in older PostGIS; degrade gracefully
        logger.warning(
            "promote_z_to_elev_failed",
            table=table_name,
            hint="ST_Z, ST_NDims, or ST_GeometryN may not be available",
        )
        return False

    return True


async def get_column_info(
    session: AsyncSession, table_name: str, schema: str = "data"
) -> list[dict]:
    """Get column names, types, ordinal position, and nullability.

    Excludes internal columns (gid, geom, geom_4326).
    Returns list of dicts with keys: name, type, ordinal_position, is_nullable.

    ``schema`` defaults to ``"data"``; multi_tenant callers pass
    ``_current_tenant_schema()``.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)
    result = await session.execute(
        text(
            "SELECT column_name, data_type, ordinal_position, "
            "       (is_nullable = 'YES') AS is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table_name "
            "ORDER BY ordinal_position"
        ).bindparams(schema=schema, table_name=table_name)
    )
    excluded = {"gid", "geom", "geom_4326"}
    return [
        {
            "name": row[0],
            "type": row[1],
            "ordinal_position": row[2],
            "is_nullable": row[3],
        }
        for row in result.all()
        if row[0] not in excluded
    ]


async def get_sample_values(
    session: AsyncSession,
    table_name: str,
    column_info: list[dict],
    sample_size: int = 10000,
    schema: str = "data",
) -> dict:
    """Extract distinct sample values per column from a data table.

    Returns a dict mapping column name to up to 10 distinct string values.
    Skips geometry-type columns and columns with no non-null values.

    A single CTE pulls ``sample_size`` rows, then a UNION ALL of branches
    extracts up to 10 distinct non-null ``::text`` values per column — one
    query and one table scan regardless of column count.

    ``sample_size`` defaults to 10000 so columns up to ~99.9% NULL still
    yield sample values within the per-column ``LIMIT 10`` cap. The CTE
    materializes this many rows up-front, so peak query RAM grows linearly
    with it; weigh a larger value against cost on multi-million-row tables.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)

    # Intersect with live columns first: ArcGIS/service ingest can build
    # column_info from the upstream API schema, which may not match the
    # landed table name-for-name (e.g. case laundering), and a missing
    # column would error the whole batched query.
    live_result = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :t"
        ).bindparams(schema=schema, t=table_name)
    )
    live_columns = {row[0] for row in live_result.all()}
    if not live_columns:
        return {}

    candidates: list[tuple[str, str]] = []
    for col in column_info:
        col_name = col.get("name", "")
        col_type = col.get("type", "")
        if not col_name:
            continue
        if "geometry" in col_type.lower():
            continue
        if col_name not in live_columns:
            continue
        candidates.append((col_name, _sql_quote_ident(col_name)))

    if not candidates:
        return {}

    # Tag each row with its column index; names are looked up by index on
    # the Python side so the SQL never embeds arbitrary identifiers as
    # literals in SELECT aliases.
    select_cols = ", ".join(q for _, q in candidates)
    union_branches: list[str] = []
    for idx, (_, quoted) in enumerate(candidates):
        union_branches.append(
            f"(SELECT {idx} AS col_idx, val FROM "
            f"(SELECT DISTINCT {quoted}::text AS val FROM sampled "
            f"WHERE {quoted} IS NOT NULL LIMIT 10) s)"
        )
    union_sql = " UNION ALL ".join(union_branches)
    # BERNOULLI(10) for representative sampling on large tables; small
    # tables (<500 rows) may return 0 rows from it, so fall back to LIMIT.
    tbl = _qtable(table_name, schema=schema)
    query = (
        f"WITH sampled AS ("
        f"  SELECT {select_cols} FROM {tbl}"
        f"  TABLESAMPLE BERNOULLI ("
        f"    CASE WHEN (SELECT c.reltuples FROM pg_class c "
        f"      JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"      WHERE c.relname = :t AND n.nspname = :schema) > 500"
        f"         THEN 10 ELSE 100 END"
        f"  ) LIMIT :sample_size"
        f") "
        f"{union_sql}"
    )

    rows = await session.execute(
        # codeql[py/sql-injection] fix(#1615): table via _qtable, columns via _sql_quote_ident (metadata_sql.py)
        text(query).bindparams(sample_size=sample_size, t=table_name, schema=schema)
    )

    result: dict[str, list[str]] = {}
    for row in rows.all():
        idx, val = row[0], row[1]
        if val is None:
            continue
        col_name = candidates[idx][0]
        result.setdefault(col_name, []).append(val)

    return result


async def _table_has_geometry(
    session: AsyncSession, table_name: str, schema: str = "data"
) -> bool:
    """Check whether a table has a 'geom' column in the given schema.

    ``schema`` defaults to ``"data"``; multi_tenant callers pass
    ``_current_tenant_schema()``.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)
    result = await session.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=:schema AND table_name=:table_name "
            "AND column_name='geom')"
        ).bindparams(schema=schema, table_name=table_name)
    )
    return result.scalar_one()


async def extract_metadata(
    session: AsyncSession, table_name: str, schema: str = "data"
) -> dict:
    """Extract all metadata from a PostGIS table.

    For spatial tables, the four data-table SELECTs (feature_count, srid,
    geometry_type, extent_wkt) are consolidated into a single CTE so the
    database does one shared scan and one round-trip. Non-spatial tables
    only query feature_count.

    Returns dict with keys: srid, geometry_type, feature_count, extent_wkt,
    column_info. For non-spatial tables, spatial fields are None.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)
    column_info = await get_column_info(session, table_name, schema=schema)
    has_geometry = await _table_has_geometry(session, table_name, schema=schema)

    if not has_geometry:
        feature_count = await get_feature_count(session, table_name, schema=schema)
        return {
            "srid": None,
            "geometry_type": None,
            "feature_count": feature_count,
            "extent_wkt": None,
            "column_info": column_info,
        }

    # Spatial-table fast path: single CTE pulls feature_count, srid,
    # geometry_type, and extent_wkt in one query, mirroring the semantics
    # of get_feature_count/get_table_srid/get_geometry_type/get_extent
    # (including returning None for geometry_type/extent_wkt on zero rows).
    tref = _qtable(table_name, schema=schema)
    try:
        result = await session.execute(
            text(
                # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
                f"""
                WITH meta AS (
                    SELECT
                        COUNT(*) AS feature_count,
                        (
                            SELECT GeometryType(geom)
                            FROM {tref}
                            WHERE geom IS NOT NULL
                            LIMIT 1
                        ) AS geometry_type,
                        -- fix(#430 BA-18): pad only degenerate (point/line) extents
                        -- into a POLYGON; spatial_extent rejects POINT/LINESTRING.
                        CASE
                            WHEN ST_Extent(geom_4326) IS NULL THEN NULL
                            WHEN GeometryType(ST_Extent(geom_4326)::geometry) = 'POLYGON'
                            THEN ST_AsText(
                                ST_SetSRID(ST_Extent(geom_4326)::geometry, 4326)
                            )
                            ELSE ST_AsText(
                                ST_Expand(
                                    ST_SetSRID(ST_Extent(geom_4326)::geometry, 4326),
                                    1e-9
                                )
                            )
                        END AS extent_wkt,
                        ST_XMin(ST_Extent(geom_4326)) AS ext_xmin,
                        ST_XMax(ST_Extent(geom_4326)) AS ext_xmax
                    FROM {tref}
                )
                SELECT
                    feature_count,
                    geometry_type,
                    extent_wkt,
                    ext_xmin,
                    ext_xmax,
                    Find_SRID(:schema, :t, 'geom') AS srid
                FROM meta
                """
            ).bindparams(schema=schema, t=table_name)
        )
        row = result.one()
        geometry_type = _normalize_geometry_type(row.geometry_type)
        # fix(#934): emit the two-ring MULTIPOLYGON for a Pacific-crossing
        # source instead of storing the naive fold; see get_extent above.
        extent_wkt = row.extent_wkt
        crossing = await _seam_crossing_extent_wkt(
            session, table_name, schema=schema, xmin=row.ext_xmin, xmax=row.ext_xmax
        )
        if crossing is not None:
            extent_wkt = crossing
        return {
            "srid": int(row.srid) if row.srid is not None else None,
            "geometry_type": geometry_type,
            "feature_count": row.feature_count,
            "extent_wkt": extent_wkt,
            "column_info": column_info,
        }
    except Exception:  # broad: degrade to the per-helper path on any DB-level error
        # Some PostGIS deployments lack Find_SRID, or ST_Extent may fail on
        # a malformed geometry.
        logger.warning(
            "extract_metadata_cte_failed_falling_back",
            table=table_name,
            exc_info=True,
        )
        srid = await get_table_srid(session, table_name, schema=schema)
        geometry_type = await get_geometry_type(session, table_name, schema=schema)
        extent_wkt = await get_extent(session, table_name, schema=schema)
        feature_count = await get_feature_count(session, table_name, schema=schema)
        return {
            "srid": srid,
            "geometry_type": geometry_type,
            "feature_count": feature_count,
            "extent_wkt": extent_wkt,
            "column_info": column_info,
        }
