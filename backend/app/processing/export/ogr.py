"""Async ogr2ogr export subprocess wrapper for PostGIS-to-file conversion."""

import asyncio
import os

from app.processing.ingest.ogr import (
    OGR2OGR_FILE_TIMEOUT_SECONDS,
    IngestionError,
    _communicate_with_timeout,
    build_pg_conn_str,
)


class ExportError(Exception):
    """Raised when an ogr2ogr export subprocess fails."""


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
}


async def run_ogr2ogr_export(
    table_name: str,
    output_path: str,
    driver: str,
    *,
    target_srs: str | None = None,
    bbox: list[float] | None = None,
    where: str | None = None,
    format_key: str = "",
) -> None:
    """Run ogr2ogr to export a PostGIS table to a file.

    Args:
        table_name: Source table name (without schema prefix).
        output_path: Destination file path.
        driver: OGR driver name (e.g. "GPKG", "GeoJSON").
        target_srs: Optional target CRS (e.g. "EPSG:3857").
        bbox: Optional bounding box [minx, miny, maxx, maxy] in WGS84.
        where: Optional SQL WHERE clause for attribute filtering.
        format_key: Format key from FORMAT_MAP for format-specific options.

    Raises:
        ExportError: If ogr2ogr exits with non-zero code.
    """
    pg_conn = build_pg_conn_str()

    cmd = [
        "ogr2ogr",
        "-f",
        driver,
        output_path,
        pg_conn,
        f"data.{table_name}",
    ]

    if target_srs:
        cmd.extend(["-t_srs", target_srs])

    if bbox:
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

    # fix(BA-06): bound the export subprocess wall-clock with a kill-on-timeout
    # (mirrors the ingest path) so a slow/large table can't hold an API worker or
    # orphan the ogr2ogr child on client disconnect; also cap the server-side query
    # via libpq statement_timeout so the DB stops working when the child is killed.
    env = {
        **os.environ,
        "PGOPTIONS": f"-c statement_timeout={OGR2OGR_FILE_TIMEOUT_SECONDS * 1000}",
    }
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
