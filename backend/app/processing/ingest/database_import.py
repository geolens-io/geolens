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
    TableDimensions,
    classify_gdal_failure,
    database_gdal_source,
    freetds_workdir,
    get_database_connection,
    importable_identifier,
    probe_table_dimensions,
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

# Indexed by ST_Zmflag: 0 2D, 1 M, 2 Z, 3 ZM.
_POINT_TYPES = ("Point", "PointM", "PointZ", "PointZM")

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
    column: str,
    target_schema: str,
    target_table: str,
    srid: int,
) -> int:
    """Load ``schema_name.table_name`` into ``target_schema.target_table``.

    ``srid`` is stamped on every geometry: GDAL reports none for a table that
    ``geometry_columns`` doesn't list. The table's primary key stays an
    ordinary column, and ``gid`` is numbered by PostGIS. A copy whose
    geometries are all single points is stored as ``Point``.

    GDAL writes every value in the dimensions the copy is told, filling a
    missing Z or M with 0, so the values of ``column`` are counted before and
    after it. Z and M are kept only when every value had them both times and
    GDAL carries them through; otherwise the copy is stored 2D. M is also
    dropped, keeping any Z, when the staging pipeline would refuse it at the
    Web Mercator limit. Returns how many values lost a Z or M: the larger of
    the two counts, since the copy read the table between them, or the values
    that lost their M.

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
    before = await _dimensions(connection_name, schema_name, table_name, column)
    dim = before.shared_dimension()

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
            *(("-dim", dim) if dim else ()),
            f"{schema_name}.{table_name}",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_tenant_writer_subprocess_env(target_schema, base_env=env),
        )
        _, stderr = await _communicate_with_timeout(
            proc, OGR2OGR_FILE_TIMEOUT_SECONDS, tool_name="ogr2ogr"
        )

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
    after = await _dimensions(connection_name, schema_name, table_name, column)
    kept = dim is not None and after.shared_dimension() == dim
    lost = 0 if kept else max(before.with_z_or_m, after.with_z_or_m)
    if dim is not None and not kept:
        await _store_2d(target_schema, target_table, srid)
    elif dim in ("XYM", "XYZM") and await _mercator_refuses_m(
        target_schema, target_table
    ):
        lost = await _store_2d(target_schema, target_table, srid, keep_z=dim == "XYZM")
    await _store_single_points_as_point(target_schema, target_table)
    return lost


async def _dimensions(
    connection_name: str, schema_name: str, table_name: str, column: str
) -> TableDimensions:
    try:
        return await probe_table_dimensions(
            connection_name,
            schema_name,
            table_name,
            column,
            timeout=OGR2OGR_FILE_TIMEOUT_SECONDS,
        )
    except DatabaseSourceError as exc:
        raise DatabaseImportError(str(exc)) from None


async def _store_2d(
    target_schema: str, target_table: str, srid: int, *, keep_z: bool = False
) -> int:
    """Drop every M, and every Z unless ``keep_z``, filled-in zeros among them.

    Returns how many values the copy holds.
    """
    from sqlalchemy import text

    from app.core.db import async_session
    from app.processing.ingest.metadata import _qtable

    table = _qtable(target_table, schema=target_schema)
    column_type, force = (
        ("GeometryZ", "ST_Force3DZ") if keep_z else ("Geometry", "ST_Force2D")
    )
    async with async_session() as session:
        await session.execute(
            text(
                # codeql[py/sql-injection] table via _qtable (metadata_sql.py); type and function fixed literals, srid an int()
                f"ALTER TABLE {table} ALTER COLUMN _geolens_geom TYPE "
                f"geometry({column_type}, {int(srid)}) USING {force}(_geolens_geom)"
            )
        )
        values = await session.scalar(
            text(
                # codeql[py/sql-injection] table via _qtable (metadata_sql.py)
                f"SELECT count(_geolens_geom) FROM {table}"  # noqa: S608
            )
        )
        await session.commit()
    return int(values or 0)


async def _mercator_refuses_m(target_schema: str, target_table: str) -> bool:
    """Whether the staging pipeline would refuse the copy's M values.

    Runs the pipeline's own first steps and Mercator check on the copy, then
    rolls them back.
    """
    from app.core.db import async_session
    from app.processing.ingest.metadata import (
        clip_to_mercator_bounds,
        ensure_geom_column,
        rename_reserved_columns,
    )
    from app.processing.ingest.metadata_mercator import MeasuredLayerCrossesMercator

    async with async_session() as session:
        try:
            await rename_reserved_columns(session, target_table, schema=target_schema)
            await ensure_geom_column(session, target_table, schema=target_schema)
            await clip_to_mercator_bounds(session, target_table, schema=target_schema)
        except MeasuredLayerCrossesMercator:
            return True
        finally:
            await session.rollback()
    return False


async def _store_single_points_as_point(target_schema: str, target_table: str) -> None:
    """Narrow the copy's column to a point type when every geometry is one point.

    The copy promotes each point to a one-part MultiPoint, because SQL Server
    declares no geometry type, and clients such as ArcGIS Online cluster only
    a Point layer. Any other content, or no geometry at all, stays as copied.
    """
    from sqlalchemy import text

    from app.core.db import async_session
    from app.processing.ingest.metadata import _qtable, grant_reader_access
    from app.processing.ingest.tasks_common import _current_tenant_role

    table = _qtable(target_table, schema=target_schema)
    async with async_session() as session:
        # In multi_tenant mode the read runs as the tenant reader.
        await grant_reader_access(
            session, target_table, schema=target_schema, role=_current_tenant_role()
        )
        row = (
            await session.execute(
                text(
                    # codeql[py/sql-injection] identifiers validated by _qtable (metadata_sql.py)
                    "SELECT bool_and(ST_GeometryType(_geolens_geom) = 'ST_MultiPoint' "
                    "AND ST_NumGeometries(_geolens_geom) = 1) AS single, "
                    "min(ST_Zmflag(_geolens_geom)) AS zm, "
                    "max(ST_Zmflag(_geolens_geom)) AS max_zm, "
                    "max(ST_SRID(_geolens_geom)) AS srid "
                    f"FROM {table} WHERE _geolens_geom IS NOT NULL"  # noqa: S608
                )
            )
        ).one()
        if row.single and row.zm == row.max_zm:
            await session.execute(
                text(
                    # codeql[py/sql-injection] table via _qtable (metadata_sql.py); the type is a fixed literal, srid an int()
                    f"ALTER TABLE {table} ALTER COLUMN _geolens_geom TYPE "
                    f"geometry({_POINT_TYPES[row.zm]}, {int(row.srid)}) "
                    "USING ST_GeometryN(_geolens_geom, 1)"
                )
            )
        await session.commit()
