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

from app.core.config import settings
from app.core.runtime.staging import ensure_staging_ready
from app.processing.export.service import validate_where_clause
from app.processing.export.where_validator import canonical_where
from app.processing.ingest.metadata import _qtable

PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"

# GeoParquet 1.1 file-level metadata. crs omitted => defaults to OGC:CRS84,
# which is exactly how PostGIS stores geom_4326 (x=lon, y=lat).
_GEO_METADATA = {
    "version": "1.1.0",
    "primary_column": "geometry",
    "columns": {
        "geometry": {
            "encoding": "WKB",
            # Empty list = "geometry types not advertised" per the spec; avoids a
            # second pass to collect distinct types.
            "geometry_types": [],
        }
    },
}


def _attr_names(column_info: list[dict] | None) -> list[str]:
    """Attribute column names in declared order, minus internal geometry cols."""
    skip = {"gid", "geom", "geom_4326", "geometry"}
    return [
        c["name"]
        for c in (column_info or [])
        if c.get("name") and c["name"] not in skip
    ]


def build_geoparquet_table(
    geom: list[bytes | None],
    cols: dict[str, list],
    attr_names: list[str],
) -> "pa.Table":
    """Build a GeoParquet-annotated Arrow table from columnar Python values.

    The geometry column holds WKB bytes; ``geo`` file metadata is attached so
    DuckDB/GeoPandas/QGIS recognize the file. pyarrow infers each attribute
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
    arrays["geometry"] = pa.array(geom, type=pa.binary())

    table = pa.table(arrays)
    return table.replace_schema_metadata(
        {b"geo": json.dumps(_GEO_METADATA).encode("utf-8")}
    )


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

    clauses: list[str] = ["geom_4326 IS NOT NULL"]
    params: dict = {}
    if bbox is not None and bbox[0] <= bbox[2]:
        clauses.append("geom_4326 && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)")
        params.update(minx=bbox[0], miny=bbox[1], maxx=bbox[2], maxy=bbox[3])
    if safe_where is not None:
        clauses.append(f"({safe_where})")
    where_sql = " AND ".join(clauses)

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

    table = build_geoparquet_table(geom, cols, attr_names)

    exports_root = ensure_staging_ready(
        os.path.join(settings.upload_staging_dir, "exports")
    )
    temp_dir = str(exports_root / uuid.uuid4().hex)
    os.mkdir(temp_dir)
    safe_name = re.sub(r"[^\w\-.]", "_", dataset_name)
    filename = f"{safe_name}.parquet"
    output_path = os.path.join(temp_dir, filename)
    try:
        pq.write_table(table, output_path)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return output_path, filename, PARQUET_MEDIA_TYPE
