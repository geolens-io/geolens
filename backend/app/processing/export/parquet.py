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

import json
import os
import re
import shutil
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.core.runtime.staging import ensure_staging_ready
from app.processing.export.service import validate_where_clause
from app.processing.export.where_validator import canonical_where
from app.processing.ingest.metadata import _qtable, get_column_info

PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"

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


async def export_parquet(
    db: AsyncSession,
    table_name: str,
    dataset_name: str,
    *,
    schema: str,
    bbox: list[float] | None = None,
    where: str | None = None,
) -> tuple[str, str, str]:
    """Export a PostGIS feature table to a GeoParquet file.

    Returns (file_path, download_filename, media_type). The caller owns the
    returned file's parent directory (FileResponse background cleanup).

    ponytail: builds the whole selection in memory before writing one Parquet
    file. Bounded by _MAX_EXPORT_FEATURES below; switch to a fixed-schema batched
    ParquetWriter if that ceiling ever needs raising.
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
        if bbox[0] > bbox[2]:
            clauses.append(
                "((geom_4326 && ST_MakeEnvelope(:minx, :miny, 180, :maxy, 4326)"
                " AND ST_Intersects(geom_4326, ST_MakeEnvelope(:minx, :miny, 180, :maxy, 4326)))"
                " OR (geom_4326 && ST_MakeEnvelope(-180, :miny, :maxx, :maxy, 4326)"
                " AND ST_Intersects(geom_4326, ST_MakeEnvelope(-180, :miny, :maxx, :maxy, 4326))))"
            )
        else:
            clauses.append(
                "geom_4326 && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)"
                " AND ST_Intersects(geom_4326, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
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

    geom: list[bytes | None] = []
    cols: dict[str, list] = {name: [] for name in attr_names}
    geom_idx = len(attr_names)

    result = await db.stream(text(sql).bindparams(**params))
    async for row in result:
        for i, name in enumerate(attr_names):
            cols[name].append(row[i])
        wkb = row[geom_idx]
        geom.append(bytes(wkb) if wkb is not None else None)

    exports_root = ensure_staging_ready(
        os.path.join(settings.upload_staging_dir, "exports")
    )
    temp_dir = str(exports_root / uuid.uuid4().hex)
    os.mkdir(temp_dir)
    safe_name = re.sub(r"[^\w\-.]", "_", dataset_name)
    filename = f"{safe_name}.parquet"
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
