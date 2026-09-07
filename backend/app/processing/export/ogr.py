"""Async ogr2ogr export subprocess wrapper for PostGIS-to-file conversion."""

import asyncio
import contextlib
import csv
import math
import os
import time

import structlog

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.processing.raster.vrt import gdal_vector_safe_env
from app.core.csv_safety import escape_csv_formula

# fix(#909): build_pg_conn_str is NOT imported at module scope — a
# module-scope import snapshots it past the test fixture's patch, which once
# sent a test export at the dev database (#898). Late-bind at call scope.
from app.processing.ingest.ogr import (
    IngestionError,
    _communicate_with_timeout,
    _tenant_reader_subprocess_env,
)
from app.processing.ingest.url_fetch import EDGE_PROXY_READ_TIMEOUT_SECONDS

logger = structlog.get_logger(__name__)


class ExportError(Exception):
    """Raised when an ogr2ogr export subprocess fails."""


# fix(#1778): this conversion runs inside the request, so its deadline is the
# edge proxy's read timeout, not the offline worker's. Measured against the
# request's own monotonic clock (deadline minus elapsed), not a fixed
# allowance, so a slow pre-conversion step can't overrun the edge; a fast one
# hands its unused time to the conversion. EDGE_PROXY_READ_TIMEOUT_SECONDS is
# imported rather than restated — one edge read timeout, one source of truth
# (frontend/nginx.conf's `proxy_read_timeout` on `location /api/`).

# Reserved for post-subprocess work: format finish (zip/gpkg normalize),
# hash+publish, audit commit. A reservation, not a measurement, sized for a
# multi-GB artifact on same-network storage — a slow step can still overrun.
EXPORT_POST_WORK_MARGIN_SECONDS = 120


def export_post_work_reserve_seconds() -> int:
    """Everything the request still owes after the subprocess exits.

    The margin above plus one ``db_pool_timeout`` (the audit row's checkout
    hasn't happened yet, and an exhausted pool can block the full timeout).
    Reads the live setting since a hardcoded value would silently break the
    arithmetic once raised.
    """
    return EXPORT_POST_WORK_MARGIN_SECONDS + settings.db_pool_timeout


# A conversion can't be given zero or negative time — that's a crash, not a
# deadline. When pre-conversion work already ate the window, the request
# fails through the ordinary timeout path instead of an arithmetic edge case.
EXPORT_BUDGET_FLOOR_SECONDS = 1

_export_reserve_warned = False


def export_subprocess_timeout_seconds(deadline: float | None) -> float:
    """Seconds this conversion may run, measured from the request's clock.

        deadline - time.monotonic() - export_post_work_reserve_seconds()

    floored at ``EXPORT_BUDGET_FLOOR_SECONDS``. ``deadline`` is a
    ``time.monotonic()`` stamp from ``RequestLoggingMiddleware``, offset by
    ``EDGE_PROXY_READ_TIMEOUT_SECONDS``; None means no request context.

    Anchored at the middleware, not the route body, so a slow
    ``Depends(get_optional_user)`` pool checkout is inside the clock.
    """
    global _export_reserve_warned

    reserve = export_post_work_reserve_seconds()
    if reserve >= EDGE_PROXY_READ_TIMEOUT_SECONDS and not _export_reserve_warned:
        # Configuration problem, not a slow request — no export can ever get
        # time on this deployment. Logged once, with the cause.
        _export_reserve_warned = True
        logger.warning(
            "export_post_work_reserve_exceeds_edge_timeout",
            db_pool_timeout=settings.db_pool_timeout,
            edge_proxy_read_timeout=EDGE_PROXY_READ_TIMEOUT_SECONDS,
            reserve=reserve,
            detail=(
                "DB_POOL_TIMEOUT leaves no room for a synchronous export "
                "inside the edge proxy's read timeout; exports will time "
                "out. Lower DB_POOL_TIMEOUT or raise the proxy's "
                "proxy_read_timeout."
            ),
        )

    if deadline is None:
        deadline = time.monotonic() + EDGE_PROXY_READ_TIMEOUT_SECONDS
    remaining = deadline - time.monotonic() - reserve
    return max(remaining, float(EXPORT_BUDGET_FLOOR_SECONDS))


# fix(#1532): lives HERE, not in `parquet.py` (which imports
# pyarrow at module scope), so the format table can be read without pulling
# pyarrow into the importer's graph. `parquet.py` re-exports it.
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
    # FlatGeobuf has no IANA registration; `application/vnd.flatgeobuf` is the
    # vendor-prefixed type its maintainers proposed after an OGC
    # standardization attempt stalled (flatgeobuf/flatgeobuf#112), matching
    # the PARQUET_MEDIA_TYPE pattern below. Single-file like GeoJSON/GPKG/CSV
    # — must NOT be added to service.py's `format_key == "shp"` zip case.
    "fgb": {
        "driver": "FlatGeobuf",
        "ext": ".fgb",
        "media": "application/vnd.flatgeobuf",
    },
    # PMTiles has no IANA registration either; `application/vnd.pmtiles` is
    # the vendor type protomaps tooling uses. Single file — no zip case.
    "pmtiles": {
        "driver": "PMTiles",
        "ext": ".pmtiles",
        "media": "application/vnd.pmtiles",
    },
}

# PMTiles' MAXZOOM defaults to 5, too coarse for anything but a world
# overview; MINZOOM is fixed at 0, MAXZOOM capped per export by extent (see
# pmtiles_maxzoom_for_extent). Ceiling of 14 matches the vector-tile
# pyramid's own top zoom (catalog/records/service.py, map builder default).
_PMTILES_MINZOOM = "0"
_PMTILES_MAXZOOM_CEILING = 14
# fix(#1686): unlike the live tile endpoint (renders on demand), the
# PMTiles writer materializes EVERY tile in MINZOOM..MAXZOOM intersecting the
# data — a wide-extent polygon at fixed z14 could demand up to 4**14 tiles,
# staging-disk exhaustion the feature-count cap can't see. Budget the
# deepest zoom's tile count instead: 4**8 caps a world layer at z8, a city
# layer still reaches z14.
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

    fix(#885): a west>east bbox crosses the antimeridian and is emitted as
    ``[minx..180] OR [-180..maxx]`` — one predicate, so a seam-straddling
    feature matches once. Shared with the GeoParquet writer so the two
    export paths can't drift.

    ``literal=True`` renders float literals for the ogr2ogr ``-where`` argv
    element, which can't carry binds.
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


# fix(#1778): ogr2ogr writes CSV cells verbatim with no escaping; the
# anonymous-reachable export route lets an editor's cell execute for any
# visitor who opens it. Post-pass, since ogr2ogr has no layer-creation option.
_CSV_FIELD_SIZE_LIMIT = 2**31 - 1

# fix(#1778): how often the pass checks the clock. A row at a time
# would monotonic()-read every batch; 512 rows honors a deadline within
# milliseconds while staying noise next to the csv parse.
_CSV_DEADLINE_CHECK_ROWS = 512


def _harden_csv_formulas(
    output_path: str,
    hard_deadline: float,
    numeric_columns: frozenset[str] = frozenset(),
) -> None:
    """Rewrite a just-written CSV with every formula-triggering cell escaped.

    Blocking — call via ``run_in_thread_draining``. Row at a time, so
    memory is bounded by the widest row. ``hard_deadline`` shares the
    request's budget: an export past the edge proxy's window raises
    ``ExportError`` instead of spending the bytes. ``numeric_columns``
    exempts only columns whose declared SQL type is numeric, so a text
    column's digits stay escaped; an unmatched name (WKT, a rename) fails
    toward escaping. Field-size limit is raised and never lowered
    (process-global state).
    """
    if csv.field_size_limit() < _CSV_FIELD_SIZE_LIMIT:
        csv.field_size_limit(_CSV_FIELD_SIZE_LIMIT)

    # Preserve GDAL's line ending rather than csv's CRLF default — a client
    # may diff or checksum this file.
    with open(output_path, "rb") as probe:
        head = probe.read(8192)
    terminator = "\r\n" if b"\r\n" in head else "\n"

    hardened_path = output_path + ".hardened"
    try:
        with (
            open(output_path, newline="", encoding="utf-8") as src,
            open(hardened_path, "w", newline="", encoding="utf-8") as dst,
        ):
            writer = csv.writer(dst, lineterminator=terminator)
            numeric_at: frozenset[int] = frozenset()
            for index, row in enumerate(csv.reader(src)):
                if (
                    index % _CSV_DEADLINE_CHECK_ROWS == 0
                    and time.monotonic() >= hard_deadline
                ):
                    raise ExportError(
                        "CSV export exceeded the request budget while applying "
                        "spreadsheet-formula hardening"
                    )
                if index == 0:
                    # Header names the columns; escape strictly and place the
                    # exemption by position for every row after.
                    numeric_at = frozenset(
                        position
                        for position, name in enumerate(row)
                        if name in numeric_columns
                    )
                    writer.writerow([escape_csv_formula(cell) for cell in row])
                    continue
                writer.writerow(
                    [
                        escape_csv_formula(cell, allow_numeric=position in numeric_at)
                        for position, cell in enumerate(row)
                    ]
                )
    except BaseException:
        # Never leave a half-rewritten sibling: the temp dir sweeps by age,
        # so a partial file here would outlive the request.
        with contextlib.suppress(OSError):
            os.unlink(hardened_path)
        raise
    os.replace(hardened_path, output_path)


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
    deadline: float | None = None,
    numeric_columns: frozenset[str] = frozenset(),
) -> None:
    """Run ogr2ogr to export a PostGIS table to a file.

    Args:
        table_name: Source table name (without schema prefix).
        output_path: Destination file path.
        driver: OGR driver name (e.g. "GPKG", "GeoJSON").
        schema: Source PostgreSQL schema; required so exports can't
            silently read a same-named table from the shared ``data`` schema.
        target_srs: Optional target CRS (e.g. "EPSG:3857").
        bbox: [minx, miny, maxx, maxy] in WGS84; a west>east box crosses
            the antimeridian and only applies to spatial layers.
        where: Optional SQL WHERE clause for attribute filtering.
        format_key: Format key from FORMAT_MAP for format-specific options.
        deadline: ``time.monotonic()`` stamp for the whole request; None
            outside a request (see ``export_subprocess_timeout_seconds``).
        numeric_columns: Numeric-type columns; CSV only, decides which
            cells keep a leading sign unescaped.

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
        # fix(#885): -spat takes ONE rectangle; an antimeridian-crossing box
        # became the complement band and dropped every feature. Split into
        # the server-side WHERE instead, in one pass (not two -spat runs).
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
        # Driver defaults MAXZOOM to 5; every column and the default layer
        # name pass through. No computed cap falls back to world-extent,
        # the conservative direction (fix(#1686)).
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

    # fix(#430): kill-on-timeout bounds the subprocess wall-clock
    # (mirrors ingest); libpq statement_timeout caps the query so it stops
    # when the child is killed.
    #
    # fix(#1778): the bound is the request's, read once as late as possible.
    # `_communicate_with_timeout` kills on cancellation, but nothing cancels
    # a GET handler on client disconnect — this deadline bounds an orphan.
    export_timeout = export_subprocess_timeout_seconds(deadline)
    # fix(#1846, GHSA-hrf5-v3cq-frx5): input here is a PG connection, not a
    # caller document, so this wasn't the finding — clamped anyway so the
    # structural gate has no exception site.
    export_env = gdal_vector_safe_env()
    # Milliseconds, and libpq wants an integer.
    export_env["PGOPTIONS"] = f"-c statement_timeout={int(export_timeout * 1000)}"
    env = _tenant_reader_subprocess_env(schema, base_env=export_env)
    assert env is not None  # base_env is always returned in single-tenant mode
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await _communicate_with_timeout(
            proc, export_timeout, tool_name="ogr2ogr export"
        )
    except IngestionError as exc:
        raise ExportError(str(exc)) from exc

    if proc.returncode != 0:
        raise ExportError(
            f"ogr2ogr export failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )

    # fix(#1778): see _harden_csv_formulas — only after a clean exit, off
    # the event loop, under the request's clock; the budget is re-read here
    # (not reused) so it gets what the subprocess left.
    if format_key == "csv":
        await run_in_thread_draining(
            _harden_csv_formulas,
            output_path,
            time.monotonic() + export_subprocess_timeout_seconds(deadline),
            numeric_columns,
        )
