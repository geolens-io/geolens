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
    safe_gdal_stderr,
)
from app.platform.gdal_env import gdal_database_safe_env
from app.processing.ingest.ogr import (
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


async def copy_database_table(
    connection_name: str,
    *,
    schema_name: str,
    table_name: str,
    target_schema: str,
    target_table: str,
    srid: int,
) -> None:
    """Load ``schema_name.table_name`` into ``target_schema.target_table``.

    ``srid`` is stamped on every geometry: GDAL reports none for a table that
    ``geometry_columns`` doesn't list. The table's primary key stays an
    ordinary column, and ``gid`` is numbered by PostGIS.

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
            "PROMOTE_TO_MULTI",
            "-lco",
            "GEOMETRY_NAME=_geolens_geom",
            "-lco",
            "SPATIAL_INDEX=NONE",
            "-a_srs",
            f"EPSG:{int(srid)}",
            f"{schema_name}.{table_name}",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_tenant_writer_subprocess_env(target_schema, base_env=env),
        )
        _stdout, stderr = await _communicate_with_timeout(
            proc, OGR2OGR_FILE_TIMEOUT_SECONDS, tool_name="ogr2ogr"
        )

    if proc.returncode != 0:
        safe_stderr = safe_gdal_stderr(stderr, connection)
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
