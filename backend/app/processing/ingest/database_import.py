"""Copy one table from an operator-configured SQL Server into PostGIS.

The connection is read from settings by name on every run, so a job or a
dataset row never holds a host or a login. The table reaches GDAL as a layer
argument after ``importable_identifier`` accepts both parts, and nothing from
a request reaches the connection string.
"""

from __future__ import annotations

import asyncio
import os

import structlog

from app.platform.database_sources import (
    DatabaseSourceError,
    DatabaseTableError,
    classify_gdal_failure,
    database_gdal_source,
    freetds_workdir,
    get_database_connection,
    importable_identifier,
    probe_table_geometry,
    safe_gdal_stderr,
)
from app.platform.gdal_env import gdal_database_safe_env
from app.processing.ingest.ogr import (
    _PG_DESTINATION_ECHO_RE,
    OGR2OGR_FILE_TIMEOUT_SECONDS,
    IngestionError,
    _communicate_with_timeout,
    _tenant_writer_subprocess_env,
)

logger = structlog.stdlib.get_logger(__name__)

# GDAL's line for a table that is missing or that the login can't read.
_MISSING_LAYER = "Couldn't fetch requested layer"


class DatabaseImportError(IngestionError):
    """A database read failed; the message names the connection only."""


def require_importable_table(
    connection: str, schema_name: str, table_name: str
) -> None:
    """Refuse a stored identifier GDAL could read as another layer."""
    if not all(
        isinstance(part, str) and importable_identifier(part)
        for part in (schema_name, table_name)
    ):
        raise DatabaseImportError(
            f"The table recorded for the database connection {connection!r} "
            "has a name GeoLens can't import."
        )


async def _still_probes_as(
    connection_name: str, schema_name: str, table_name: str, point_type: str
) -> bool:
    """Whether the table still holds only points of ``point_type``.

    A point column accepts a point of other dimensions by padding or dropping
    Z and M, so a copy that exits 0 says nothing about them.
    """
    try:
        probed = await probe_table_geometry(connection_name, schema_name, table_name)
    except DatabaseSourceError:
        return False
    return probed.point_type == point_type


async def copy_database_table(
    connection_name: str,
    *,
    schema_name: str,
    table_name: str,
    target_schema: str,
    target_table: str,
    srid: int,
    point_type: str | None = None,
) -> None:
    """Load ``schema_name.table_name`` into ``target_schema.target_table``.

    ``srid`` is stamped on every geometry: GDAL reports none for a table that
    ``geometry_columns`` doesn't list. The table's primary key stays an
    ordinary column, and ``gid`` is numbered by PostGIS. A table holding only
    points is stored as ``point_type`` so clients can cluster it; every other
    table, and one that fails the point copy or no longer probes as
    ``point_type`` after it, is copied in its multi form.

    Raises ``DatabaseImportError`` with a message safe to show.
    """
    from app.processing.ingest.metadata import _validate_table_name
    from app.processing.ingest.ogr import build_pg_conn_str

    _validate_table_name(target_table)
    _validate_table_name(target_schema)
    require_importable_table(connection_name, schema_name, table_name)
    try:
        connection = get_database_connection(connection_name)
    except DatabaseSourceError as exc:
        raise DatabaseImportError(str(exc)) from None

    with freetds_workdir(connection) as workdir:
        env = gdal_database_safe_env(
            os.path.join(workdir, "freetds.conf"),
            connection.username,
            connection.password.get_secret_value(),
        )
        cmd = [
            "ogr2ogr",
            "-if",
            "MSSQLSpatial",
            "-f",
            "PostgreSQL",
            build_pg_conn_str(),
            database_gdal_source(connection),
            "-overwrite",
            "-nln",
            f"{target_schema}.{target_table}",
            "-lco",
            "FID=gid",
            # The same column typing and write path as a file import.
            "-lco",
            "PRECISION=NO",
            "--config",
            "PG_USE_COPY",
            "YES",
            "--config",
            "OGR_PG_ENABLE_METADATA",
            "NO",
            # Otherwise an integer primary key becomes the feature id and is
            # dropped from the attributes.
            "--config",
            "MSSQLSPATIAL_SHOW_FID_COLUMN",
            "YES",
            # SQL Server stores curves, which the linear column type refuses.
            "-nlt",
            "CONVERT_TO_LINEAR",
            "-nlt",
            point_type or "PROMOTE_TO_MULTI",
            "-lco",
            "GEOMETRY_NAME=_geolens_geom",
            "-lco",
            "SPATIAL_INDEX=NONE",
            "-a_srs",
            f"EPSG:{int(srid)}",
            f"{schema_name}.{table_name}",
        ]
        nlt = cmd.index("CONVERT_TO_LINEAR") + 2
        while True:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_tenant_writer_subprocess_env(target_schema, base_env=env),
            )
            _, stderr = await _communicate_with_timeout(
                proc, OGR2OGR_FILE_TIMEOUT_SECONDS, tool_name="ogr2ogr"
            )
            if cmd[nlt] == "PROMOTE_TO_MULTI":
                break
            if proc.returncode == 0 and await _still_probes_as(
                connection_name, schema_name, table_name, cmd[nlt]
            ):
                break
            # The table changed after the probe; -overwrite replaces whatever
            # this try created.
            logger.info(
                "point table copy not kept; retrying as multi",
                connection=connection_name,
                returncode=proc.returncode,
            )
            cmd[nlt] = "PROMOTE_TO_MULTI"

    if proc.returncode != 0:
        # GDAL masks only the first word of a quoted PostGIS password when it
        # echoes a destination it can't open.
        safe_stderr = _PG_DESTINATION_ECHO_RE.sub(
            "PG:***", safe_gdal_stderr(stderr, connection)
        )
        logger.warning(
            "database import failed",
            connection=connection_name,
            returncode=proc.returncode,
            stderr=safe_stderr,
        )
        error = classify_gdal_failure(connection_name, safe_stderr)
        if isinstance(error, DatabaseTableError) and _MISSING_LAYER not in safe_stderr:
            raise DatabaseImportError(
                "Copying the table from the database connection "
                f"{connection_name!r} failed."
            )
        raise DatabaseImportError(str(error))
