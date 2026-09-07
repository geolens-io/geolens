"""GeoParquet export writer (pyarrow).

The Debian GDAL build has no Arrow/Parquet driver, so ogr2ogr can't emit
Parquet; this module writes GeoParquet 1.1 directly from PostGIS via
pyarrow instead, WKB-encoding geometry and attaching the ``geo`` metadata
key DuckDB/GeoPandas/QGIS read.

Output is always EPSG:4326 (OGC:CRS84); the router rejects a non-4326
``target_crs`` for parquet, so no reprojection is needed here.
"""

import asyncio
import json
import os
import shutil
import uuid
from typing import NamedTuple

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.core.runtime.staging import ensure_staging_ready
from app.processing.export.ogr import (
    ExportError,
    bbox_where_sql,
    export_subprocess_timeout_seconds,
)
from app.processing.export.service import export_descriptor, validate_where_clause
from app.processing.export.where_validator import canonical_where
from app.processing.ingest.metadata import _qtable, get_column_info

# Re-exported from `ogr.py`, which owns it so `api/main.py` can read the whole
# set of export media types without importing pyarrow (fix(#1532)).
from app.processing.export.ogr import PARQUET_MEDIA_TYPE  # noqa: F401

# Mirror router._MAX_EXPORT_FEATURES. The router skips its cap when a dataset's
# feature_count is NULL (legacy/registered rows); the parquet path builds the
# selection in memory, so it enforces its own bounded-count cap regardless.
_MAX_EXPORT_FEATURES = 5_000_000


class ExportTooLargeError(Exception):
    """Raised when a parquet export's selection exceeds _MAX_EXPORT_FEATURES."""


def _geo_metadata(primary_column: str) -> dict:
    """GeoParquet 1.1 file-level metadata for a given geometry column name.

    crs omitted => defaults to OGC:CRS84, which is exactly how PostGIS stores
    geom_4326 (x=lon, y=lat).
    """
    return {
        "version": "1.1.0",
        "primary_column": primary_column,
        "columns": {
            primary_column: {
                "encoding": "WKB",
                # Empty list = "geometry types not advertised" per the spec;
                # avoids a second pass to collect distinct types.
                "geometry_types": [],
            }
        },
    }


def _attr_names(column_info: list[dict] | None) -> list[str]:
    """Attribute column names in declared order, minus internal geometry cols.

    Only the true internal columns (gid + the two geometry columns) are dropped;
    a user attribute literally named ``geometry`` is a real column and is kept
    (the WKB output column is renamed to avoid the collision — see
    build_geoparquet_table).
    """
    skip = {"gid", "geom", "geom_4326"}
    return [
        c["name"]
        for c in (column_info or [])
        if c.get("name") and c["name"] not in skip
    ]


def _geometry_column_name(attr_names: list[str]) -> str:
    """Pick the WKB output column name, avoiding a collision with a user column
    that is itself named ``geometry`` (e.g. a CSV/WKT import's original column)."""
    if "geometry" not in attr_names:
        return "geometry"
    candidate = "geom_wkb"
    i = 1
    while candidate in attr_names:
        candidate = f"geom_wkb_{i}"
        i += 1
    return candidate


def build_geoparquet_table(
    geom: list[bytes | None],
    cols: dict[str, list],
    attr_names: list[str],
    geom_col: str = "geometry",
) -> "pa.Table":
    """Build a GeoParquet-annotated Arrow table from columnar Python values.

    WKB geometry lives in ``geom_col`` (renamed off "geometry" only when a
    user attribute claims that name). A column pyarrow can't unify falls
    back to string so the export still succeeds. Pure/DB-free, unit-testable.
    """
    arrays: dict[str, "pa.Array"] = {}
    for name in attr_names:
        try:
            arrays[name] = pa.array(cols[name])
        except (pa.ArrowInvalid, pa.ArrowTypeError):
            arrays[name] = pa.array(
                [None if v is None else str(v) for v in cols[name]],
                type=pa.string(),
            )
    arrays[geom_col] = pa.array(geom, type=pa.binary())

    table = pa.table(arrays)
    return table.replace_schema_metadata(
        {b"geo": json.dumps(_geo_metadata(geom_col)).encode("utf-8")}
    )


def _write_geoparquet(
    geom: list[bytes | None],
    cols: dict[str, list],
    attr_names: list[str],
    geom_col: str,
    output_path: str,
) -> None:
    """Build the Arrow table and write the Parquet file (both CPU-bound).

    Blocking; call via run_in_thread_draining so it doesn't stall the event loop.
    """
    table = build_geoparquet_table(geom, cols, attr_names, geom_col)
    pq.write_table(table, output_path)


class ParquetExportPlan(NamedTuple):
    """The validated selection a parquet export will read. No bytes produced."""

    attr_names: list[str]
    where_sql: str
    params: dict


async def plan_parquet_export(
    db: AsyncSession,
    table_name: str,
    *,
    schema: str,
    bbox: list[float] | None = None,
    where: str | None = None,
) -> ParquetExportPlan:
    """Everything that decides a parquet export's STATUS, producing no file.

    fix(#1513, codex P2 on #1522): split out so the route can run this
    BEFORE answering a HEAD — introspection, filter validation and the
    bounded count are reads a HEAD can afford; left inside
    ``export_parquet``, a HEAD answered 200 while the GET later failed
    400/413.

    Raises:
        ValueError: bad filter (unknown column, malformed clause) -> 400.
        ExportTooLargeError: selection over the cap -> 413.
    """
    # Introspect the live table once for BOTH column selection and filter
    # validation: dataset.column_info is nullable, and trusting it would (a)
    # silently export geometry-only or (b) reject a valid filter when columns
    # are right here.
    live_columns = await get_column_info(db, table_name, schema=schema)
    attr_names = _attr_names(live_columns)

    if where is not None:
        # Same trust boundary as the ogr2ogr -where path: AST allowlist + column
        # check (against the live columns), then interpolate the canonical
        # re-render, never the raw bytes.
        validate_where_clause(where, live_columns)
        safe_where = canonical_where(where)
    else:
        safe_where = None

    # No blanket geom_4326 IS NOT NULL: a full export keeps null-geometry
    # rows (like the feature read path and other formats). A bbox filter
    # still drops them naturally — null neither && nor ST_Intersects.
    clauses: list[str] = []
    params: dict = {}
    if bbox is not None:
        # Mirrors features query bbox semantics (features/service.py): an &&
        # prefilter plus exact ST_Intersects, with the antimeridian split
        # when minx > maxx (parse_bbox allows it) — && alone would drop
        # antimeridian boxes and return an envelope-overlap superset.
        # fix(#885): fragment comes from the shared builder in export/ogr.py
        # so the ogr2ogr path splits identically.
        clauses.append(bbox_where_sql(bbox))
        params.update(minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3])
    if safe_where is not None:
        # SQLAlchemy text() reads ":name" as a bind; a colon inside the
        # validated where clause (e.g. 'A:B', an ISO timestamp) would
        # misparse. Escape to text()'s literal-colon form (\:); the bbox
        # clause's real :minx/:miny binds are added separately, unescaped.
        escaped_where = safe_where.replace(":", "\\:")
        clauses.append(f"({escaped_where})")
    where_sql = " AND ".join(clauses) if clauses else "TRUE"

    # Bound the in-memory build: the router's feature_count cap is skipped
    # when NULL, so count the actual selection here (LIMIT stops the scan at
    # cap+1) before streaming millions of rows into Python lists.
    count_sql = (
        f"SELECT COUNT(*) FROM (SELECT 1 FROM "
        f"{_qtable(table_name, schema=schema)} t "
        f"WHERE {where_sql} LIMIT :__cap) sub"
    )
    count = (
        await db.execute(
            text(count_sql).bindparams(**params, __cap=_MAX_EXPORT_FEATURES + 1)
        )
    ).scalar_one()
    if count > _MAX_EXPORT_FEATURES:
        raise ExportTooLargeError(
            f"Export selects more than {_MAX_EXPORT_FEATURES} features; narrow it "
            "with a bbox or attribute filter."
        )

    return ParquetExportPlan(attr_names, where_sql, params)


async def _stream_rows(
    db: AsyncSession,
    sql: str,
    params: dict,
    attr_names: list[str],
    geom_idx: int,
) -> tuple[list[bytes | None], dict[str, list]]:
    """Read every row of the planned selection into columnar Python lists.

    Split out of ``export_parquet`` so ``asyncio.wait_for`` there bounds
    exactly this — the row source — rather than the query construction and
    file setup around it.
    """
    geom: list[bytes | None] = []
    cols: dict[str, list] = {name: [] for name in attr_names}

    result = await db.stream(text(sql).bindparams(**params))
    async for row in result:
        for i, name in enumerate(attr_names):
            cols[name].append(row[i])
        wkb = row[geom_idx]
        geom.append(bytes(wkb) if wkb is not None else None)

    return geom, cols


async def export_parquet(
    db: AsyncSession,
    table_name: str,
    dataset_name: str,
    *,
    schema: str,
    plan: ParquetExportPlan,
    deadline: float | None = None,
) -> tuple[str, str, str]:
    """Write the planned selection to a GeoParquet file.

    Takes the plan from ``plan_parquet_export`` rather than deriving it, so
    the route can decide the response status before committing to bytes
    (fix(#1513)).

    Returns (file_path, download_filename, media_type). The caller owns the
    returned file's parent directory (FileResponse background cleanup).
    Builds the whole selection in memory; bounded by the plan's count check.

    deadline: ``time.monotonic()`` stamp for the whole request. Reuses
        ``export_subprocess_timeout_seconds`` (fix(#1778)) since an
        unindexed table can stream past the edge-proxy window with nothing
        else to stop it. None outside a request.
    """
    attr_names, where_sql, params = plan

    # Selects attribute columns directly (not via to_jsonb) so the async
    # driver returns native Python values and Arrow infers real types.
    # Geometry is selected last, read positionally, so a user column sharing
    # the WKB alias can't shadow it. Idents double-quoted defensively.
    select_parts = ['"' + n.replace('"', '""') + '"' for n in attr_names]
    select_parts.append("ST_AsBinary(geom_4326)")
    sql = (
        f"SELECT {', '.join(select_parts)} "
        f"FROM {_qtable(table_name, schema=schema)} t WHERE {where_sql}"
    )
    geom_idx = len(attr_names)

    row_stream_timeout = export_subprocess_timeout_seconds(deadline)
    try:
        geom, cols = await asyncio.wait_for(
            _stream_rows(db, sql, params, attr_names, geom_idx),
            timeout=row_stream_timeout,
        )
    except asyncio.TimeoutError:
        raise ExportError(
            f"GeoParquet export timed out after {int(row_stream_timeout)}s "
            "— the row source is too slow"
        )

    exports_root = ensure_staging_ready(
        os.path.join(settings.upload_staging_dir, "exports")
    )
    temp_dir = str(exports_root / uuid.uuid4().hex)
    os.mkdir(temp_dir)
    # fix(#1513): one naming rule for both verbs — see export_descriptor.
    filename, _ = export_descriptor(dataset_name, "parquet")
    output_path = os.path.join(temp_dir, filename)
    geom_col = _geometry_column_name(attr_names)
    try:
        # CPU-bound Arrow encode+write can block the loop for a multi-GB
        # export; threaded and drained (mirrors export/service.py's
        # shapefile zip) so a disconnect can't rmtree temp_dir mid-write.
        await run_in_thread_draining(
            _write_geoparquet, geom, cols, attr_names, geom_col, output_path
        )
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return output_path, filename, PARQUET_MEDIA_TYPE
