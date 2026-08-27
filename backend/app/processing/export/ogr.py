"""Async ogr2ogr export subprocess wrapper for PostGIS-to-file conversion."""

import asyncio
import math
import os

# fix(#909): build_pg_conn_str is deliberately NOT imported at module scope.
# The test fixture redirects app.processing.ingest.ogr.build_pg_conn_str at
# the origin; a module-scope `from ... import` here snapshots the dev-DB
# helper past that patch, which once sent a test's ogr2ogr export at the dev
# database (#898). Late-bind at call scope (test_layering.py enforces this).
from app.processing.ingest.ogr import (
    OGR2OGR_FILE_TIMEOUT_SECONDS,
    IngestionError,
    _communicate_with_timeout,
    _tenant_reader_subprocess_env,
)


class ExportError(Exception):
    """Raised when an ogr2ogr export subprocess fails."""


# fix(#1532 review r9): the parquet media type lives HERE rather than in
# `parquet.py`, which imports pyarrow at module scope, so the format table can
# be read without pulling pyarrow into the importer's graph for a string.
# `parquet.py` re-exports it, so its own callers are unchanged. (r9 also
# derived the full media-type set here for a GZipMiddleware exclusion; r11
# scoped that opt-out to the export PATH instead, and the set went with it.)
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"

FORMAT_MAP: dict[str, dict[str, str]] = {
    "gpkg": {
        "driver": "GPKG",
        "ext": ".gpkg",
        "media": "application/geopackage+sqlite3",
    },
    "geojson": {
        "driver": "GeoJSON",
        "ext": ".geojson",
        "media": "application/geo+json",
    },
    "shp": {
        "driver": "ESRI Shapefile",
        "ext": ".shp",
        "media": "application/zip",
    },
    "csv": {
        "driver": "CSV",
        "ext": ".csv",
        "media": "text/csv",
    },
    # FlatGeobuf has no IANA registration. `application/vnd.flatgeobuf` is the
    # vendor-prefixed type the format's own maintainers proposed
    # (flatgeobuf/flatgeobuf#112) after an OGC standardization attempt stalled,
    # and it is the same vendor-prefix pattern this table already uses for
    # GeoParquet (PARQUET_MEDIA_TYPE below) for the identical reason. It is a
    # single file like GeoJSON/GPKG/CSV, not multi-file like Shapefile, so it
    # must NOT be added to the `format_key == "shp"` zip special-casing in
    # service.py.
    "fgb": {
        "driver": "FlatGeobuf",
        "ext": ".fgb",
        "media": "application/vnd.flatgeobuf",
    },
    # PMTiles has no IANA registration either; `application/vnd.pmtiles` is
    # the vendor-prefixed type the protomaps tooling itself uses. Single
    # file, like fgb/gpkg/geojson/csv — no zip special-casing.
    "pmtiles": {
        "driver": "PMTiles",
        "ext": ".pmtiles",
        "media": "application/vnd.pmtiles",
    },
}

# The PMTiles driver's dataset creation options default to
# MAXZOOM=5, far too coarse for anything but a world overview. MINZOOM is
# fixed at 0; MAXZOOM is capped per export by extent — see
# pmtiles_maxzoom_for_extent. The ceiling of 14 matches the vector-tile
# pyramid's own top zoom (catalog/records/service.py's vector_tiles
# distribution and the map builder's default source config).
_PMTILES_MINZOOM = "0"
_PMTILES_MAXZOOM_CEILING = 14
# fix(#1686 codex r1): unlike the live tile endpoint, which renders tiles on
# demand, the PMTiles writer materializes EVERY tile in MINZOOM..MAXZOOM that
# intersects the data, so tile count is extent-driven and a wide-extent
# polygon layer at a fixed z14 could demand up to 4**14 tiles — staging-disk
# exhaustion the feature-count cap cannot see. Budget the deepest zoom's
# tile count instead: 4**8 caps a world-extent layer at z8 while a
# city-extent layer still reaches z14.
_PMTILES_TILE_BUDGET = 65_536


def _mercator_y(lat: float) -> float:
    """Normalized Web-Mercator y in [0, 1] (0 at the north clamp)."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return min(max(y, 0.0), 1.0)


def pmtiles_maxzoom_for_extent(
    extent: tuple[float, float, float, float] | None,
) -> int:
    """Deepest zoom whose materialized tile count stays within budget.

    ``extent`` is a WGS84 (minx, miny, maxx, maxy) bounds tuple. ``None`` —
    an unknown extent — assumes the whole world, the conservative direction.
    An antimeridian-crossing extent read via shapely ``bounds`` reports the
    long way around, which over-caps but never under-caps.
    """
    if extent is None:
        xspan, yspan = 1.0, 1.0
    else:
        minx, miny, maxx, maxy = extent
        xspan = min(max((maxx - minx) / 360.0, 0.0), 1.0)
        yspan = min(max(_mercator_y(miny) - _mercator_y(maxy), 0.0), 1.0)

    for z in range(_PMTILES_MAXZOOM_CEILING, 0, -1):
        cols = max(1, math.ceil(xspan * (1 << z)))
        rows = max(1, math.ceil(yspan * (1 << z)))
        if cols * rows <= _PMTILES_TILE_BUDGET:
            return z
    return 0


def bbox_where_sql(bbox: list[float], *, literal: bool = False) -> str:
    """Build the ``geom_4326`` bbox predicate for a raw-SQL WHERE fragment.

    Each envelope carries a ``&&`` index prefilter plus an exact
    ``ST_Intersects``, mirroring the features read path
    (``catalog/features/service.py``).

    fix(#885): a west>east bbox crosses the antimeridian — ``parse_bbox``
    documents it as valid input — and is emitted as ``[minx..180]`` OR
    ``[-180..maxx]``. It stays a single predicate, so a feature whose own
    geometry straddles the seam matches the OR once and is selected exactly
    once. Shared with the GeoParquet writer (``export/parquet.py``) so the two
    export paths cannot drift.

    ``literal=True`` renders float literals instead of ``:minx``-style bind
    parameters, for the ogr2ogr ``-where`` argument — a subprocess argv element
    that cannot carry binds. Every bound goes through ``float()``, so the
    rendered text is always a numeric literal (``parse_bbox`` has already
    rejected NaN/Inf).
    """
    if literal:
        minx, miny, maxx, maxy = (repr(float(v)) for v in bbox)
    else:
        minx, miny, maxx, maxy = ":minx", ":miny", ":maxx", ":maxy"

    def envelope(west: str, east: str) -> str:
        env = f"ST_MakeEnvelope({west}, {miny}, {east}, {maxy}, 4326)"
        return f"(geom_4326 && {env} AND ST_Intersects(geom_4326, {env}))"

    if bbox[0] > bbox[2]:
        return f"({envelope(minx, '180')} OR {envelope('-180', maxx)})"
    return envelope(minx, maxx)


async def run_ogr2ogr_export(
    table_name: str,
    output_path: str,
    driver: str,
    *,
    schema: str,
    target_srs: str | None = None,
    bbox: list[float] | None = None,
    where: str | None = None,
    format_key: str = "",
    pmtiles_maxzoom: int | None = None,
) -> None:
    """Run ogr2ogr to export a PostGIS table to a file.

    Args:
        table_name: Source table name (without schema prefix).
        output_path: Destination file path.
        driver: OGR driver name (e.g. "GPKG", "GeoJSON").
        schema: Source PostgreSQL schema. Required so exports cannot silently
            read a same-named table from the shared ``data`` schema.
        target_srs: Optional target CRS (e.g. "EPSG:3857").
        bbox: Optional bounding box [minx, miny, maxx, maxy] in WGS84. A
            west>east box crosses the antimeridian and is filtered server-side
            against ``geom_4326``, so callers must not pass a bbox for a layer
            without geometry (the router drops it for non-spatial datasets).
        where: Optional SQL WHERE clause for attribute filtering.
        format_key: Format key from FORMAT_MAP for format-specific options.

    Raises:
        ExportError: If ogr2ogr exits with non-zero code.
    """
    from app.processing.ingest.metadata import _validate_table_name
    from app.processing.ingest.ogr import build_pg_conn_str

    _validate_table_name(table_name)
    _validate_table_name(schema)
    pg_conn = build_pg_conn_str()

    cmd = [
        "ogr2ogr",
        "-f",
        driver,
        output_path,
        pg_conn,
        f"{schema}.{table_name}",
    ]

    if target_srs:
        cmd.extend(["-t_srs", target_srs])

    if bbox and bbox[0] > bbox[2]:
        # fix(#885): -spat takes ONE rectangle and GDAL reads its corners as an
        # envelope, so an antimeridian-crossing `-spat 170 -20 -170 -15` silently
        # became the complement band (lon -170..170) and dropped every feature the
        # caller asked for. Push the two-envelope split into the server-side WHERE
        # instead — one pass, so a seam-straddling feature is still emitted once
        # (two -spat runs would emit it twice). Still select-not-clip: whole
        # intersecting features with untouched geometry, unlike -clipsrc.
        spatial_where = bbox_where_sql(bbox, literal=True)
        where = f"{spatial_where} AND ({where})" if where else spatial_where
    elif bbox:
        cmd.extend(
            [
                "-spat",
                str(bbox[0]),
                str(bbox[1]),
                str(bbox[2]),
                str(bbox[3]),
                "-spat_srs",
                "EPSG:4326",
            ]
        )

    if where:
        cmd.extend(["-where", where])

    if format_key == "csv":
        cmd.extend(["-lco", "GEOMETRY=AS_WKT"])

    if format_key == "pmtiles":
        # The driver defaults MAXZOOM to 5; every attribute
        # column already comes through by default (no -select), and the
        # layer name is left to ogr2ogr's own default (the source table
        # name) rather than an explicit -nln, matching every other format
        # here. A caller that computed no extent-aware cap gets the
        # world-extent one — the conservative direction (fix(#1686 codex r1)).
        maxzoom = (
            pmtiles_maxzoom
            if pmtiles_maxzoom is not None
            else pmtiles_maxzoom_for_extent(None)
        )
        cmd.extend(
            [
                "-dsco",
                f"MINZOOM={_PMTILES_MINZOOM}",
                "-dsco",
                f"MAXZOOM={min(max(maxzoom, 0), _PMTILES_MAXZOOM_CEILING)}",
            ]
        )

    # fix(#430 BA-06): bound the export subprocess wall-clock with a kill-on-timeout
    # (mirrors the ingest path) so a slow/large table can't hold an API worker;
    # also cap the server-side query via libpq statement_timeout so the DB query
    # stops when the child is killed. `_communicate_with_timeout` below kills the
    # child on cancellation too (a client disconnect), not only on timeout — see
    # its docstring for why that branch has to exist.
    env = _tenant_reader_subprocess_env(
        schema,
        base_env={
            **os.environ,
            "PGOPTIONS": (
                f"-c statement_timeout={OGR2OGR_FILE_TIMEOUT_SECONDS * 1000}"
            ),
        },
    )
    assert env is not None  # base_env is always returned in single-tenant mode
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await _communicate_with_timeout(
            proc, OGR2OGR_FILE_TIMEOUT_SECONDS, tool_name="ogr2ogr export"
        )
    except IngestionError as exc:
        raise ExportError(str(exc)) from exc

    if proc.returncode != 0:
        raise ExportError(
            f"ogr2ogr export failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )
