"""Read an operator-configured SQL Server through GDAL's MSSQLSpatial driver.

Host, port and TLS reach FreeTDS through a generated freetds.conf section,
since FreeTDS 1.3 verifies a certificate only from a section selected with
``Servername=``. The connection string GDAL echoes into its errors then names
that section and the database, never the host. The login travels in the child
environment (see ``gdal_database_safe_env``). Every SQL statement here is built
by GeoLens; identifiers come from SQL Server's own catalog and are
bracket-quoted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, NamedTuple

import structlog

from app.core.async_io import await_draining
from app.core.config import settings
from app.core.config_database_sources import DatabaseConnection
from app.core.url_redaction import redact_odbc_credentials, scrub_secret_value
from app.platform.gdal_env import gdal_database_safe_env

logger = structlog.stdlib.get_logger(__name__)

FREETDS_SECTION = "geolens"
# GDAL sets a 30 s ODBC login timeout that nothing configurable shortens, so a
# subprocess deadline below it would turn an unreachable server into a kill.
SUBPROCESS_TIMEOUT_SECONDS = 45.0
_REAP_WAIT_SECONDS = 5.0
_STDERR_LOG_CHARS = 2000
# Rows (one per spatial column) a listing returns before it says it stopped.
LISTING_LIMIT = 500

# GDAL prints this for every connect failure: host, port, login, database and
# TLS look the same. Anything else is a table or query it couldn't read.
_CONNECT_FAILURE = "Unable to initialize connection"


class DatabaseSourceError(Exception):
    """A read failed. The message names the connection and nothing else."""

    def __init__(self, connection: str, message: str) -> None:
        super().__init__(message)
        self.connection = connection


class UnknownDatabaseConnectionError(DatabaseSourceError):
    def __init__(self, connection: str) -> None:
        super().__init__(
            connection, f"No database connection named {connection!r} is configured."
        )


class DatabaseConnectError(DatabaseSourceError):
    def __init__(self, connection: str) -> None:
        super().__init__(
            connection,
            f"Couldn't connect or sign in to the database connection {connection!r}.",
        )


class DatabaseTableError(DatabaseSourceError):
    def __init__(self, connection: str) -> None:
        super().__init__(
            connection,
            f"A table in the database connection {connection!r} was not found "
            "or is not readable.",
        )


@dataclass(frozen=True)
class SpatialTable:
    schema_name: str
    table_name: str
    object_type: Literal["table", "view"]
    geometry_column: str
    column_type: Literal["geometry", "geography"]
    srid: int | None


@dataclass(frozen=True)
class SpatialTableListing:
    tables: list[SpatialTable]
    truncated: bool


def get_database_connection(name: str) -> DatabaseConnection:
    connection = settings.database_sources.get(name)
    if connection is None:
        raise UnknownDatabaseConnectionError(name)
    return connection


def render_freetds_conf(connection: DatabaseConnection) -> str:
    """The one freetds.conf section the GDAL subprocess may use.

    FreeTDS skips certificate verification unless ``ca file`` is set, so an
    encrypted connection without a CA bundle verifies against the system store;
    only ``trust_server_certificate`` leaves the line out.
    """
    lines = [
        f"[{FREETDS_SECTION}]",
        f"host = {connection.host}",
        f"port = {connection.port}",
        "tds version = 7.4",
        "client charset = UTF-8",
        f"encryption = {'require' if connection.encrypt else 'request'}",
    ]
    if not connection.trust_server_certificate:
        lines.append(f"ca file = {connection.ca_file or 'system'}")
    return "\n".join(lines) + "\n"


def database_gdal_source(connection: DatabaseConnection) -> str:
    return (
        f"MSSQL:Driver=FreeTDS;Servername={FREETDS_SECTION};"
        f"Database={connection.database}"
    )


def _write_private(path: str, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


@contextlib.contextmanager
def freetds_workdir(connection: DatabaseConnection) -> Iterator[str]:
    """A private temp directory holding ``freetds.conf``, removed on exit."""
    with tempfile.TemporaryDirectory(prefix="geolens-tds-") as workdir:
        _write_private(
            os.path.join(workdir, "freetds.conf"), render_freetds_conf(connection)
        )
        yield workdir


def quote_identifier(name: str) -> str:
    """A SQL Server bracket-quoted identifier."""
    return "[" + name.replace("]", "]]") + "]"


def classify_gdal_failure(connection: str, stderr: str) -> DatabaseSourceError:
    if _CONNECT_FAILURE in stderr:
        return DatabaseConnectError(connection)
    return DatabaseTableError(connection)


def safe_gdal_stderr(stderr: bytes, connection: DatabaseConnection) -> str:
    """GDAL's stderr with the connection string, ODBC keys and password masked."""
    text = stderr.decode("utf-8", "replace")[:_STDERR_LOG_CHARS]
    return scrub_secret_value(
        redact_odbc_credentials(text), connection.password.get_secret_value()
    )


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
        await await_draining(asyncio.wait_for(proc.wait(), timeout=_REAP_WAIT_SECONDS))


async def run_database_sql(name: str, sql: str) -> list[dict[str, object]]:
    """Run one GeoLens-built SELECT on connection ``name`` and return its rows.

    Raises a ``DatabaseSourceError`` subclass whose message is safe to show.
    """
    connection = get_database_connection(name)
    with freetds_workdir(connection) as workdir:
        sql_path = os.path.join(workdir, "query.sql")
        _write_private(sql_path, sql)
        env = gdal_database_safe_env(
            os.path.join(workdir, "freetds.conf"),
            connection.username,
            connection.password.get_secret_value(),
        )
        cmd = [
            "ogrinfo",
            "-ro",
            "-if",
            "MSSQLSpatial",
            "-json",
            "-features",
            "-sql",
            f"@{sql_path}",
            database_gdal_source(connection),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=SUBPROCESS_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning("database read timed out", connection=name)
            raise DatabaseConnectError(name) from None
        finally:
            if proc.returncode is None:
                await _kill_and_reap(proc)

    if proc.returncode != 0:
        safe_stderr = safe_gdal_stderr(stderr, connection)
        logger.warning(
            "database read failed",
            connection=name,
            returncode=proc.returncode,
            stderr=safe_stderr,
        )
        raise classify_gdal_failure(name, safe_stderr)
    try:
        layers = json.loads(stdout.decode("utf-8")).get("layers") or []
    except (ValueError, UnicodeDecodeError, AttributeError):
        logger.warning("database read returned unreadable output", connection=name)
        raise DatabaseTableError(name) from None
    if not layers:
        return []
    return [
        feature.get("properties") or {} for feature in layers[0].get("features", [])
    ]


def _catalog_sql(limit: int) -> str:
    # Alias types can be named geometry too, hence the schema check. A table
    # the login can see but not read is left out, so the listing is what an
    # import can actually read.
    return (
        f"SELECT TOP ({limit + 1}) s.name AS schema_name, o.name AS object_name, "
        "o.type AS object_type, c.name AS column_name, t.name AS type_name "
        "FROM sys.columns c "
        "JOIN sys.objects o ON o.object_id = c.object_id "
        "JOIN sys.schemas s ON s.schema_id = o.schema_id "
        "JOIN sys.types t ON t.user_type_id = c.user_type_id "
        "WHERE t.name IN ('geometry', 'geography') "
        "AND t.schema_id = SCHEMA_ID('sys') "
        "AND o.type IN ('U', 'V') AND o.is_ms_shipped = 0 "
        "AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), "
        "'OBJECT', 'SELECT') = 1 "
        "ORDER BY s.name, o.name, c.name"
    )


def srid_probe_sql(columns: list[tuple[str, str, str]]) -> str:
    """One row per ``(schema, table, column)``: its index and the SRID of the
    first non-null value."""
    parts = []
    for index, (schema_name, table_name, column) in enumerate(columns):
        col = quote_identifier(column)
        parts.append(
            f"SELECT {index} AS i, (SELECT TOP 1 {col}.STSrid "
            f"FROM {quote_identifier(schema_name)}.{quote_identifier(table_name)} "
            f"WHERE {col} IS NOT NULL) AS srid"
        )
    return " UNION ALL ".join(parts)


class _CatalogRow(NamedTuple):
    schema_name: str
    object_name: str
    object_type: str
    column_name: str
    type_name: str


def _catalog_rows(rows: list[dict[str, object]]) -> list[_CatalogRow]:
    parsed = []
    for row in rows:
        values = [row.get(field) for field in _CatalogRow._fields]
        if all(isinstance(value, str) for value in values):
            parsed.append(_CatalogRow(*(str(value) for value in values)))
    return parsed


async def _probe_srids(
    name: str, columns: list[tuple[str, str, str]]
) -> dict[int, int]:
    try:
        rows = await run_database_sql(name, srid_probe_sql(columns))
    except DatabaseTableError:
        # One unreadable object (a view over a dropped table) fails the whole
        # statement; the tables are still listed, with no SRID.
        logger.warning("database SRID probe failed", connection=name)
        return {}
    srids: dict[int, int] = {}
    for row in rows:
        index, srid = row.get("i"), row.get("srid")
        if isinstance(index, int) and isinstance(srid, int) and srid != 0:
            srids[index] = srid
    return srids


async def list_spatial_tables(
    name: str, *, limit: int = LISTING_LIMIT
) -> SpatialTableListing:
    """The spatial columns of the tables and views connection ``name`` can read."""
    rows = _catalog_rows(await run_database_sql(name, _catalog_sql(limit)))
    truncated = len(rows) > limit
    rows = rows[:limit]
    srids = (
        await _probe_srids(
            name, [(r.schema_name, r.object_name, r.column_name) for r in rows]
        )
        if rows
        else {}
    )
    tables = [
        SpatialTable(
            schema_name=row.schema_name,
            table_name=row.object_name,
            object_type="view" if row.object_type.strip() == "V" else "table",
            geometry_column=row.column_name,
            column_type="geography" if row.type_name == "geography" else "geometry",
            srid=srids.get(index),
        )
        for index, row in enumerate(rows)
    ]
    return SpatialTableListing(tables=tables, truncated=truncated)
