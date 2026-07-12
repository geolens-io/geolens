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
from app.processing.ingest.metadata import _qtable

PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"


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
    bbox: list[float] | None = None,
    where: str | None = None,
    column_info: list[dict] | None = None,
) -> tuple[str, str, str]:
    """Export a PostGIS feature table to a GeoParquet file.

    Returns (file_path, download_filename, media_type). The caller owns the
    returned file's parent directory (FileResponse background cleanup).

    ponytail: builds the whole selection in memory before writing one Parquet
    file. The export is already capped at 5M features upstream; switch to a
    fixed-schema batched ParquetWriter if large-catalog exports OOM.
    """
    if where is not None:
        # Same trust boundary as the ogr2ogr -where path: AST allowlist + column
        # check, then interpolate the canonical re-render, never the raw bytes.
        validate_where_clause(where, column_info)
        safe_where = canonical_where(where)
    else:
        safe_where = None

    attr_names = _attr_names(column_info)

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
        clauses.append(f"({safe_where})")
    where_sql = " AND ".join(clauses) if clauses else "TRUE"

    sql = (
        "SELECT ST_AsBinary(geom_4326) AS wkb_geom, "
        "to_jsonb(t.*) - 'gid' - 'geom' - 'geom_4326' AS props_json "
        f"FROM {_qtable(table_name)} t WHERE {where_sql}"
    )

    geom: list[bytes | None] = []
    cols: dict[str, list] = {name: [] for name in attr_names}

    result = await db.stream(text(sql).bindparams(**params))
    async for row in result:
        m = row._mapping
        wkb = m["wkb_geom"]
        geom.append(bytes(wkb) if wkb is not None else None)
        props = m["props_json"] or {}
        for name in attr_names:
            cols[name].append(props.get(name))

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
