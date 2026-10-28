"""Column types for ArcGIS fields GDAL's ESRIJSON driver loads as text.

The driver types only the long-standing Esri field types. BigInteger, DateOnly,
TimeOnly and TimestampOffset arrive as strings, so a layer imported from the
service would otherwise differ from the same data in a file geodatabase.
"""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.column_names import stored_column_names
from app.processing.ingest.metadata_sql import _qtable, _sql_quote_ident

logger = structlog.get_logger()

# Dates and timestamps are epoch milliseconds in the layer's JSON for some
# services and ISO strings for others.
_EPOCH_MS = r"'^-?[0-9]+$'"
_CASTS: dict[str, tuple[str, str]] = {
    "esriFieldTypeBigInteger": ("bigint", "{c}::bigint"),
    "esriFieldTypeDateOnly": (
        "date",
        "CASE WHEN {c} ~ " + _EPOCH_MS + " "
        "THEN (to_timestamp({c}::bigint / 1000.0) AT TIME ZONE 'UTC')::date "
        "ELSE {c}::date END",
    ),
    "esriFieldTypeTimeOnly": ("time", "{c}::time"),
    "esriFieldTypeTimestampOffset": (
        "timestamptz",
        "CASE WHEN {c} ~ " + _EPOCH_MS + " "
        "THEN to_timestamp({c}::bigint / 1000.0) ELSE {c}::timestamptz END",
    ),
}


def column_casts_from_meta(meta: dict) -> dict[str, str]:
    """Esri type by stored column name, for the fields that need a cast."""
    fields = [
        f
        for f in meta.get("fields") or []
        if isinstance(f, dict)
        and isinstance(f.get("name"), str)
        and f.get("type") != "esriFieldTypeGeometry"
    ]
    stored = stored_column_names([f["name"] for f in fields])
    return {
        column.encode()[:63].decode(errors="ignore"): f["type"]
        for f, column in zip(fields, stored, strict=True)
        if f.get("type") in _CASTS
    }


async def apply_arcgis_column_casts(
    session: AsyncSession,
    table_name: str,
    casts: dict[str, str] | None,
    *,
    schema: str,
) -> None:
    """Convert the loaded text columns to the types Esri declares for them.

    Runs after every page is loaded: a typed column would refuse the later
    pages' string values. A column whose values don't convert stays text.
    """
    if not casts:
        return
    qtable = _qtable(table_name, schema)
    present = {
        row[0]
        for row in await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :t "
                "AND data_type IN ('text', 'character varying')"
            ).bindparams(schema=schema, t=table_name)
        )
    }
    for column, esri_type in casts.items():
        if column not in present:
            continue
        pg_type, expr = _CASTS[esri_type]
        quoted = _sql_quote_ident(column)
        try:
            async with session.begin_nested():
                await session.execute(
                    text(
                        # codeql[py/sql-injection] identifiers quoted; type and expression are constants
                        f"ALTER TABLE {qtable} ALTER COLUMN {quoted} "
                        f"TYPE {pg_type} USING {expr.format(c=quoted)}"
                    )
                )
        except Exception as exc:  # broad: bad values leave the column text
            logger.warning(
                "arcgis_column_cast_failed",
                table=table_name,
                column=column,
                esri_type=esri_type,
                error=type(exc).__name__,
            )
