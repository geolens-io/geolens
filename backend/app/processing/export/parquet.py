"""GeoParquet export writer (pyarrow).

The Debian GDAL build ships without the Arrow/Parquet driver, so ogr2ogr
(export/ogr.py) cannot emit Parquet. This module writes a spec-valid
GeoParquet 1.1 file directly from PostGIS via pyarrow instead — the geometry
column is WKB-encoded and the file carries the ``geo`` metadata key that
DuckDB, GeoPandas, and QGIS read.

CRS: output is always EPSG:4326 (lon/lat), i.e. GeoParquet's default OGC:CRS84.
The router rejects a non-4326 ``target_crs`` for parquet, so no reprojection or
embedded PROJJSON is needed here.
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
# set of export media types without importing pyarrow (fix(#1532 review r9)).
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

    The WKB geometry lives in ``geom_col`` (renamed off "geometry" only when a
    user attribute already claims that name); ``geo`` file metadata is attached
    so DuckDB/GeoPandas/QGIS recognize the file. pyarrow infers each attribute
    column's type; a column it can't unify (rare, mixed JSON) falls back to
    string so the export still succeeds. Pure/DB-free so it is unit-testable.
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

    fix(#1513, codex P2 on #1522): split out of ``export_parquet`` so the route
    can run it BEFORE it answers a HEAD. Live introspection, filter validation
    and the bounded count are all queries, not conversion, so a HEAD can afford
    them — and has to: while these lived inside ``export_parquet`` a HEAD
    answered 200 and the caller's follow-up range GET then failed 400 or 413,
    which is worse than the 405 the HEAD route replaced, because it lies.

    Split at the conversion boundary, not at an arbitrary point: everything
    here is a read, and everything after it in ``export_parquet`` builds the
    file. Returning the plan means a GET pays for this exactly once.

    Raises:
        ValueError: bad filter (unknown column, malformed clause) -> 400.
        ExportTooLargeError: selection over the cap -> 413.
    """
    # Introspect the live table once and use it for BOTH column selection and
    # filter validation — dataset.column_info is nullable, and trusting it would
    # (a) silently export geometry-only and (b) reject a valid filter on a
    # metadata-less dataset even though the columns are right here.
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

    # No blanket geom_4326 IS NOT NULL: a full export must keep rows with null
    # geometry (they export with a null geometry cell, like the feature read path
    # and the other export formats). A bbox filter still drops them naturally —
    # a null geometry neither && nor ST_Intersects an envelope.
    clauses: list[str] = []
    params: dict = {}
    if bbox is not None:
        # Mirror the features query bbox semantics (features/service.py): an
        # envelope && prefilter for the index PLUS an exact ST_Intersects, and
        # the antimeridian split when minx > maxx (parse_bbox allows it). Using
        # only && would silently drop antimeridian boxes and return an
        # envelope-overlap superset instead of the rows actually in the bbox.
        # fix(#885): the fragment now comes from the shared builder in
        # export/ogr.py, so the ogr2ogr path splits identically instead of
        # handing a degenerate rectangle to -spat.
        clauses.append(bbox_where_sql(bbox))
        params.update(minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3])
    if safe_where is not None:
        # SQLAlchemy text() reads ":name" as a bind parameter; a colon inside a
        # string literal in the validated where clause (e.g. name = 'A:B' or an
        # ISO timestamp) would otherwise misparse as an unbound param and fail.
        # Escape colons to text()'s literal-colon form (\:). The bbox clause's
        # real :minx/:miny binds are added separately and stay unescaped.
        escaped_where = safe_where.replace(":", "\\:")
        clauses.append(f"({escaped_where})")
    where_sql = " AND ".join(clauses) if clauses else "TRUE"

    # Bound the in-memory build. The router caps by feature_count, but that guard
    # is skipped when feature_count is NULL, so count the actual selection here
    # (LIMIT stops the scan at cap+1) before streaming millions of rows into
    # Python lists and OOMing the worker.
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

    Takes the plan from ``plan_parquet_export`` rather than deriving it, so the
    route can decide the response status before it commits to producing bytes
    (fix(#1513)). Every rejection this export can produce has already happened
    by the time it is called.

    Returns (file_path, download_filename, media_type). The caller owns the
    returned file's parent directory (FileResponse background cleanup).

    Builds the whole selection in memory before writing one Parquet file.
    Bounded by the plan's count check; switch to a fixed-schema batched
    ParquetWriter if that ceiling ever needs raising.

    deadline: ``time.monotonic()`` stamp by which the whole request must be
        answered, from the route's entry. The ogr2ogr formats bound their
        subprocess wall clock and libpq ``statement_timeout`` by what is left
        of this (fix(#1778), ``export_subprocess_timeout_seconds``); this
        format has no subprocess, but an unindexed table or a wide selection
        can stream rows past the same edge-proxy window with nothing to stop
        it. Reuses that helper rather than deriving a second bound, and raises
        the same ``ExportError`` the ogr2ogr timeout raises, so the router's
        ``except ExportError`` handling — one 500, not a response nginx has
        already severed — is identical for every format. ``None`` for a
        caller outside a request, which is the same arithmetic with an
        elapsed time of zero.
    """
    attr_names, where_sql, params = plan

    # Select the attribute columns directly (not via to_jsonb) so the async
    # driver returns native Python values — dates, timestamps, UUIDs, numerics —
    # and Arrow infers real column types instead of everything-as-string. Geometry
    # is selected last and read positionally, so a user column that happens to
    # share the WKB alias can't shadow it. Idents are information_schema names,
    # double-quoted (embedded quotes doubled) defensively.
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
        # Arrow encoding + write are CPU-bound and can block the event loop for
        # a multi-GB export; run them in a thread (mirrors the shapefile zip path
        # in export/service.py), drained so a client disconnect can't rmtree
        # temp_dir mid-write.
        await run_in_thread_draining(
            _write_geoparquet, geom, cols, attr_names, geom_col, output_path
        )
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return output_path, filename, PARQUET_MEDIA_TYPE
