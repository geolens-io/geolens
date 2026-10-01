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
import sys
import uuid
from collections.abc import AsyncIterator
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
# feature_count is NULL (legacy/registered rows), so the parquet path enforces
# its own bounded-count cap regardless.
_MAX_EXPORT_FEATURES = 5_000_000

# Rows, or approximate bytes of Python values, held before a batch is encoded
# and appended to the file. Whichever bound trips first flushes, so memory
# follows these rather than the size of the selection.
_BATCH_MAX_ROWS = 100_000
_BATCH_MAX_BYTES = 32 * 1024 * 1024


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


def _holds_object(value: object) -> bool:
    """Whether ``value`` is a JSON object or an array holding one at any depth."""
    if not isinstance(value, (dict, list)):
        return False
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            return True
        if isinstance(item, list):
            pending.extend(item)
    return False


def _as_text(value: object) -> str:
    """JSON for an object or array, so readers can parse it; plain text otherwise."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def _text(values: list) -> "pa.Array":
    return pa.array(
        [None if v is None else _as_text(v) for v in values], type=pa.string()
    )


def build_geoparquet_table(
    geom: list[bytes | None],
    cols: dict[str, list],
    attr_names: list[str],
    geom_col: str = "geometry",
) -> "pa.Table":
    """Build a GeoParquet-annotated Arrow table from columnar Python values.

    WKB geometry lives in ``geom_col`` (renamed off "geometry" only when a
    user attribute claims that name). A column holding a JSON object, alone
    or inside an array, is written as text, and so is a column pyarrow can't
    unify, so the export still succeeds. Pure/DB-free, unit-testable.
    """
    arrays: dict[str, "pa.Array"] = {}
    for name in attr_names:
        values = cols[name]
        # As a struct, every row would take a slot for every key in the column.
        if any(_holds_object(v) for v in values):
            arrays[name] = _text(values)
            continue
        try:
            arrays[name] = pa.array(values)
        except (pa.ArrowInvalid, pa.ArrowTypeError, OverflowError):
            arrays[name] = _text(values)
    arrays[geom_col] = pa.array(geom, type=pa.binary())

    table = pa.table(arrays)
    return table.replace_schema_metadata(
        {b"geo": json.dumps(_geo_metadata(geom_col)).encode("utf-8")}
    )


def _common_type(current: pa.DataType, incoming: pa.DataType) -> pa.DataType | None:
    """The type holding the values of both, or None when none does.

    Arrow's promotion widens null and numeric types and the element of a list.
    It takes the larger precision and the larger scale of two decimals
    separately, which can drop integer digits, so decimals are widened here by
    digit counts instead.
    """
    if current.equals(incoming):
        return current
    if pa.types.is_list(current) and pa.types.is_list(incoming):
        element = _common_type(current.value_type, incoming.value_type)
        return None if element is None else pa.list_(element)
    if pa.types.is_decimal(current) and pa.types.is_decimal(incoming):
        scale = max(current.scale, incoming.scale)
        precision = scale + max(
            current.precision - current.scale, incoming.precision - incoming.scale
        )
        if precision <= 38:
            return pa.decimal128(precision, scale)
        return pa.decimal256(precision, scale) if precision <= 76 else None
    try:
        unified = pa.unify_schemas(
            [pa.schema([("c", current)]), pa.schema([("c", incoming)])],
            promote_options="permissive",
        )
    except pa.ArrowTypeError:
        return None
    return unified.field("c").type


def _wider_type(current: pa.DataType, incoming: pa.DataType) -> pa.DataType:
    """The type holding the values of both, or string when none does."""
    common = _common_type(current, incoming)
    return pa.string() if common is None else common


def _conform(table: pa.Table, schema: pa.Schema) -> tuple[pa.Table, pa.Schema]:
    """Cast ``table`` to ``schema``; return the table and the schema it took.

    A column whose values don't cast becomes string in both. Text is written
    the way build_geoparquet_table's fallback writes it, so a column reads
    the same whichever batch turned it into text.
    """
    columns = []
    for i, (field, column) in enumerate(zip(schema, table.columns)):
        if not pa.types.is_string(field.type):
            try:
                columns.append(column.cast(field.type))
                continue
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError):
                schema = schema.set(i, field.with_type(pa.string()))
        if not pa.types.is_string(column.type):
            column = _text(column.to_pylist())
        columns.append(column)
    return pa.table(columns, schema=schema), schema


class _GeoParquetWriter:
    """Appends batches to one GeoParquet file under a single file schema.

    Each batch infers its own Arrow types, so a column that is all NULL in an
    early batch, or whose later decimals have more digits, does not fit the
    schema the first batch fixed. The file is then re-encoded under the wider
    schema; a column whose type holds steady never pays for it. A column whose
    batches share no type, or whose values don't cast to it, becomes text.

    Blocking; call ``write`` and ``close`` via run_in_thread_draining so they
    don't stall the event loop.
    """

    def __init__(self, output_path: str, attr_names: list[str], geom_col: str) -> None:
        self._path = output_path
        self._attr_names = attr_names
        self._geom_col = geom_col
        self._writer: pq.ParquetWriter | None = None

    def write(self, geom: list[bytes | None], cols: dict[str, list]) -> None:
        table = build_geoparquet_table(geom, cols, self._attr_names, self._geom_col)
        if self._writer is None:
            self._writer = pq.ParquetWriter(self._path, table.schema)
        target = pa.schema(
            [
                field.with_type(_wider_type(field.type, incoming.type))
                for field, incoming in zip(self._writer.schema, table.schema)
            ],
            metadata=self._writer.schema.metadata,
        )
        batch, target = _conform(table, target)
        if not target.equals(self._writer.schema):
            self._reencode(target)
            # Rewriting can turn more columns into text than this batch did.
            batch, _ = _conform(table, self._writer.schema)
        self._writer.write_table(batch)

    def _reencode(self, schema: pa.Schema) -> None:
        """Rewrite the rows written so far under ``schema``, one row group at a time.

        A column whose earlier values don't cast becomes text and the rewrite
        starts over, so the reopened writer's schema can differ from ``schema``.
        """
        self._writer.close()
        written = self._path + ".prev"
        os.replace(self._path, written)
        with pq.ParquetFile(written) as source:
            while True:
                self._writer = pq.ParquetWriter(self._path, schema)
                for i in range(source.num_row_groups):
                    rows, fitted = _conform(source.read_row_group(i), schema)
                    if not fitted.equals(schema):
                        break
                    self._writer.write_table(rows)
                else:
                    break
                self._writer.close()
                schema = fitted
        os.remove(written)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            return
        # An empty selection still yields a valid file carrying the geo metadata.
        empty = build_geoparquet_table(
            [],
            {name: [] for name in self._attr_names},
            self._attr_names,
            self._geom_col,
        )
        pq.write_table(empty, self._path)

    def abort(self) -> None:
        """Release the file handle of an export that is being discarded."""
        writer, self._writer = self._writer, None
        if writer is not None:
            try:
                writer.close()
            except Exception:  # broad: best-effort close of a file about to be deleted
                pass


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

    fix(#1513): split out so the route can run this
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

    # The router's feature_count cap is skipped when NULL, so count the actual
    # selection here (LIMIT stops the scan at cap+1) before streaming it.
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


def _approx_bytes(value: object) -> int:
    """Python memory held by one cell, counting what an array or JSON value holds."""
    if not isinstance(value, (dict, list, tuple)):
        return sys.getsizeof(value)
    # A stack, not recursion: JSON can nest deeper than Python's recursion limit.
    total = 0
    pending = [value]
    while pending:
        item = pending.pop()
        total += sys.getsizeof(item)
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return total


async def _stream_batches(
    db: AsyncSession,
    sql: str,
    params: dict,
    attr_names: list[str],
    geom_idx: int,
) -> AsyncIterator[tuple[list[bytes | None], dict[str, list]]]:
    """Yield the planned selection as columnar batches of bounded size.

    A batch ends at ``_BATCH_MAX_ROWS`` rows or ``_BATCH_MAX_BYTES`` of
    accumulated values, whichever comes first, so a few very wide rows flush
    early instead of growing a batch without limit.
    """
    geom: list[bytes | None] = []
    cols: dict[str, list] = {name: [] for name in attr_names}
    held = 0

    result = await db.stream(text(sql).bindparams(**params))
    async for row in result:
        for i, name in enumerate(attr_names):
            cols[name].append(row[i])
            held += _approx_bytes(row[i])
        wkb = row[geom_idx]
        geom.append(bytes(wkb) if wkb is not None else None)
        held += _approx_bytes(wkb)

        if len(geom) >= _BATCH_MAX_ROWS or held >= _BATCH_MAX_BYTES:
            yield geom, cols
            geom = []
            cols = {name: [] for name in attr_names}
            held = 0

    if geom:
        yield geom, cols


async def _write_batches(
    sink: _GeoParquetWriter,
    db: AsyncSession,
    sql: str,
    params: dict,
    attr_names: list[str],
    geom_idx: int,
) -> None:
    """Append each batch of the row stream to ``sink``.

    Split out of ``export_parquet`` so ``asyncio.wait_for`` there bounds
    exactly this, the row source and its encoding, rather than the query
    construction and file setup around it.
    """
    async for geom, cols in _stream_batches(db, sql, params, attr_names, geom_idx):
        # CPU-bound Arrow encode+write can block the loop for a large batch;
        # threaded and drained (mirrors export/service.py's shapefile zip) so a
        # disconnect can't rmtree temp_dir mid-write.
        await run_in_thread_draining(sink.write, geom, cols)
        # The generator starts the next batch only after this loop resumes, so
        # drop ours first or two batches are live at once.
        del geom, cols


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
    the route can decide the response status before committing to bytes.

    Returns (file_path, download_filename, media_type). The caller owns the
    returned file's parent directory (FileResponse background cleanup).
    Rows are written in bounded batches, so memory does not grow with the
    selection.

    deadline: ``time.monotonic()`` stamp for the whole request. Reuses
        ``export_subprocess_timeout_seconds`` since an unindexed table can
        stream past the edge-proxy window with nothing else to stop it. None
        outside a request.
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

    exports_root = ensure_staging_ready(
        os.path.join(settings.upload_staging_dir, "exports")
    )
    temp_dir = str(exports_root / uuid.uuid4().hex)
    os.mkdir(temp_dir)
    # One naming rule for both verbs; see export_descriptor.
    filename, _ = export_descriptor(dataset_name, "parquet")
    output_path = os.path.join(temp_dir, filename)
    sink = _GeoParquetWriter(output_path, attr_names, _geometry_column_name(attr_names))

    row_stream_timeout = export_subprocess_timeout_seconds(deadline)
    try:
        try:
            await asyncio.wait_for(
                _write_batches(sink, db, sql, params, attr_names, geom_idx),
                timeout=row_stream_timeout,
            )
        except asyncio.TimeoutError:
            raise ExportError(
                f"GeoParquet export timed out after {int(row_stream_timeout)}s "
                "— the row source or the write is too slow"
            )
        await run_in_thread_draining(sink.close)
    except BaseException:
        sink.abort()
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return output_path, filename, PARQUET_MEDIA_TYPE
