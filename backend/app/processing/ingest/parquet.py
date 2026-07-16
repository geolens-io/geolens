"""GeoParquet ingest reader/loader (pyarrow).

The Debian GDAL build ships without the Arrow/Parquet driver, so ogrinfo /
ogr2ogr cannot read ``.parquet`` uploads. This module is the ingest-side
mirror of ``processing/export/parquet.py``: preview metadata comes straight
from pyarrow, and the loader writes rows into PostGIS through the app's own
connection, producing the same table shape ``run_ogr2ogr`` creates (``gid``
serial PK, laundered lowercase column names, a ``_geolens_geom`` geometry
column that ``ensure_geom_column`` later renames to ``geom``) so the rest of
the ingest pipeline runs unchanged.

Supports GeoParquet 1.0/1.1 with WKB geometry encoding. Parquet files without
``geo`` metadata ingest as non-spatial tables (same as a CSV without geometry).
"""

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

if TYPE_CHECKING:
    from app.processing.ingest.ogr import OgrinfoResult

_INSERT_BATCH_ROWS = 5000


def _read_geo_metadata(pf: pq.ParquetFile) -> dict | None:
    """Parse the file-level ``geo`` key (GeoParquet), or None for plain parquet."""
    kv = pf.schema_arrow.metadata
    if not kv or b"geo" not in kv:
        return None
    try:
        geo = json.loads(kv[b"geo"])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return geo if isinstance(geo, dict) else None


def _geometry_column(geo: dict | None) -> tuple[str | None, dict]:
    """Return (primary geometry column name, its column metadata)."""
    if not geo:
        return None, {}
    primary = geo.get("primary_column")
    col_meta = (geo.get("columns") or {}).get(primary) or {}
    return primary, col_meta


def _srid_from_geo(col_meta: dict) -> int | None:
    """SRID from GeoParquet column metadata.

    Per spec, an omitted or null ``crs`` means OGC:CRS84 (= lon/lat 4326).
    A PROJJSON crs resolves through its EPSG id; anything unresolvable
    returns None so the pipeline's Missing-CRS / srid_override handling
    applies.
    """
    if col_meta.get("crs") is None:  # absent or explicit null -> CRS84
        return 4326
    crs = col_meta["crs"]
    if not isinstance(crs, dict):
        return None
    id_obj = crs.get("id") or {}
    authority, code = id_obj.get("authority"), id_obj.get("code")
    if authority == "EPSG" and code is not None:
        return int(code)
    if authority == "OGC" and str(code) == "CRS84":
        return 4326
    return None


def _check_wkb_encoding(col_meta: dict) -> None:
    encoding = col_meta.get("encoding", "WKB")
    if encoding != "WKB":
        from app.processing.ingest.ogr import IngestionError

        raise IngestionError(
            f"GeoParquet geometry encoding '{encoding}' is not supported; "
            "only WKB-encoded geometry columns can be imported."
        )


def _covering_column(geo: dict | None, primary: str | None) -> str | None:
    """Name of the GeoParquet 1.1 covering-bbox struct column, if declared.

    It is derived index metadata (per-row bbox), not user data — the loader
    and preview drop it.
    """
    if not geo or not primary:
        return None
    bbox = ((geo.get("columns", {}).get(primary) or {}).get("covering") or {}).get(
        "bbox"
    )
    if isinstance(bbox, dict):
        # spec shape: {"xmin": ["bbox", "xmin"], ...} — first path element
        # is the column name.
        for path in bbox.values():
            if isinstance(path, list) and path:
                return str(path[0])
    return None


def _ogr_type_name(t: pa.DataType) -> str:
    """Map an Arrow type to the OGR field-type name ogrinfo previews use."""
    if pa.types.is_dictionary(t):
        return _ogr_type_name(t.value_type)
    if pa.types.is_boolean(t):
        return "Integer(Boolean)"
    if pa.types.is_integer(t):
        return "Integer64" if t.bit_width == 64 else "Integer"
    if pa.types.is_floating(t) or pa.types.is_decimal(t):
        return "Real"
    if pa.types.is_timestamp(t):
        return "DateTime"
    if pa.types.is_date(t):
        return "Date"
    if pa.types.is_time(t):
        return "Time"
    if pa.types.is_binary(t) or pa.types.is_large_binary(t):
        return "Binary"
    return "String"


def _pg_type(t: pa.DataType) -> str:
    """Map an Arrow type to the PostgreSQL column type the loader creates.

    Mirrors ogr2ogr's PRECISION=NO philosophy: predictable generic types
    (integer/bigint/double precision/varchar) over declared precision.
    """
    if pa.types.is_dictionary(t):
        return _pg_type(t.value_type)
    if pa.types.is_boolean(t):
        return "boolean"
    if pa.types.is_integer(t):
        # signed <=32-bit fits integer; int64/uint32/uint64 need bigint
        return (
            "integer"
            if t.bit_width <= 32 and pa.types.is_signed_integer(t)
            else "bigint"
        )
    if pa.types.is_floating(t) or pa.types.is_decimal(t):
        return "double precision"
    if pa.types.is_timestamp(t):
        return "timestamptz" if t.tz else "timestamp"
    if pa.types.is_date(t):
        return "date"
    if pa.types.is_time(t):
        return "time"
    if pa.types.is_binary(t) or pa.types.is_large_binary(t):
        return "bytea"
    return "varchar"


def _value_converter(t: pa.DataType) -> "Callable[[Any], Any] | None":
    """Python-value converter for types asyncpg can't take as-is (None = passthrough)."""
    if pa.types.is_dictionary(t):
        return _value_converter(t.value_type)
    if pa.types.is_decimal(t):
        return lambda v: None if v is None else float(v)
    if _pg_type(t) == "varchar" and not (
        pa.types.is_string(t) or pa.types.is_large_string(t)
    ):
        # nested/exotic types (list, struct, map, duration, ...) -> JSON-ish text
        return lambda v: None if v is None else json.dumps(v, default=str)
    return None


def _launder(name: str) -> str:
    """Lowercase + sanitize a column name the way ogr2ogr's PG driver does."""
    n = re.sub(r"[^a-z0-9_]", "_", name.lower())
    return (n or "col")[:63]


def _json_safe(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def _open_and_inspect(file_path: str) -> tuple[pq.ParquetFile, dict]:
    """Open a parquet file and derive the ogrinfo-shaped metadata (blocking)."""
    pf = pq.ParquetFile(file_path)
    geo = _read_geo_metadata(pf)
    geom_col, col_meta = _geometry_column(geo)
    skip = {geom_col, _covering_column(geo, geom_col)} - {None}

    srid = None
    geometry_type = None
    if geom_col is not None:
        _check_wkb_encoding(col_meta)
        srid = _srid_from_geo(col_meta)
        declared = [g for g in col_meta.get("geometry_types") or [] if g]
        if declared:
            geometry_type = declared[0]
        else:
            # Our own exporter writes an empty geometry_types list; probe the
            # first non-null WKB value instead. Preview-grade only — the real
            # type is derived from PostGIS after load.
            geometry_type = "Unknown (any)"
            for batch in pf.iter_batches(batch_size=256, columns=[geom_col]):
                for wkb in batch.column(0).to_pylist():
                    if wkb is not None:
                        import shapely

                        geometry_type = shapely.from_wkb(wkb).geom_type
                        break
                else:
                    continue
                break

    columns = [
        {"name": f.name, "type": _ogr_type_name(f.type)}
        for f in pf.schema_arrow
        if f.name not in skip
    ]
    info: dict = {
        "srid": srid,
        "geometry_type": geometry_type,
        "layer_name": Path(file_path).stem,
        "feature_count": pf.metadata.num_rows,
        "columns": columns,
        "all_layers": None,
    }
    return pf, info


async def parquet_info(file_path: str, sample_limit: int = 0) -> "OgrinfoResult":
    """pyarrow stand-in for run_ogrinfo / run_ogrinfo_preview on .parquet files.

    Returns the same dict shape so PreviewResponse and the ingest task
    consume it unchanged. Raises pyarrow errors on corrupt files (the
    preview route maps any failure to a 422).
    """

    def _read() -> dict:
        pf, info = _open_and_inspect(file_path)
        if sample_limit > 0:
            attr_names = [c["name"] for c in info["columns"]]
            rows: list[dict] = []
            if attr_names and pf.metadata.num_rows:
                for batch in pf.iter_batches(
                    batch_size=sample_limit, columns=attr_names
                ):
                    for row in batch.to_pylist():
                        rows.append({k: _json_safe(v) for k, v in row.items()})
                        if len(rows) >= sample_limit:
                            break
                    break
            info["sample_rows"] = rows
        return info

    return await asyncio.to_thread(_read)


def _column_plan(
    schema_arrow: "pa.Schema", skip: set
) -> list[tuple[str, str, str, Any]]:
    """(source name, laundered PG name, PG type, value converter) per column.

    Seeds used-names with the loader's own columns; a source attribute that
    launders to "gid" lands as "gid_2" (rename_reserved_columns can't help
    here — the serial gid must exist before it runs).
    """
    used = {"gid", "_geolens_geom"}
    plan: list[tuple[str, str, str, Any]] = []
    for f in schema_arrow:
        if f.name in skip:
            continue
        base = _launder(f.name)
        pg_name, suffix = base, 2
        while pg_name in used:
            pg_name = f"{base[:60]}_{suffix}"
            suffix += 1
        used.add(pg_name)
        plan.append((f.name, pg_name, _pg_type(f.type), _value_converter(f.type)))
    return plan


async def load_parquet_to_postgis(
    file_path: str,
    table_name: str,
    *,
    schema: str,
    srid: int,
    include_geometry: bool,
) -> None:
    """pyarrow stand-in for run_ogr2ogr on .parquet files.

    Creates ``{schema}.{table_name}`` with the same conventions ogr2ogr uses
    (gid serial PK, ``_geolens_geom`` placeholder geometry column, laundered
    column names) and batch-inserts the rows. ``include_geometry=False``
    loads attribute columns only (non-spatial parquet, or a user geometry
    override where geometry is constructed post-load).

    ponytail: executemany inserts, not COPY — fine up to a few million rows;
    switch to asyncpg copy_records_to_table if load time ever matters.
    """
    from app.core.db import async_session
    from app.processing.ingest.metadata import _qtable, _validate_table_name

    _validate_table_name(table_name)
    _validate_table_name(schema)

    pf = await asyncio.to_thread(pq.ParquetFile, file_path)
    geo = _read_geo_metadata(pf)
    geom_col, col_meta = _geometry_column(geo)
    if geom_col is not None:
        _check_wkb_encoding(col_meta)
    if not include_geometry:
        geom_col = None
    source_geom_col = _geometry_column(geo)[0]
    skip = {source_geom_col, _covering_column(geo, source_geom_col)}
    plan = _column_plan(pf.schema_arrow, skip)

    def _q(ident: str) -> str:
        return '"' + ident.replace('"', '""') + '"'

    ddl_cols = ["gid serial PRIMARY KEY"]
    ddl_cols += [f"{_q(pg_name)} {pg_type}" for _, pg_name, pg_type, _ in plan]
    if geom_col is not None:
        ddl_cols.append(f"_geolens_geom geometry(Geometry, {int(srid)})")

    insert_cols = [_q(pg_name) for _, pg_name, _, _ in plan]
    insert_vals = [f":p{i}" for i in range(len(plan))]
    if geom_col is not None:
        insert_cols.append("_geolens_geom")
        # explicit cast: ST_GeomFromWKB has bytea AND text overloads, and an
        # untyped bind (e.g. an all-NULL batch) would be ambiguous.
        insert_vals.append(f"ST_GeomFromWKB(CAST(:geom AS bytea), {int(srid)})")

    tref = _qtable(table_name, schema=schema)
    ddl = f"CREATE TABLE {tref} ({', '.join(ddl_cols)})"
    insert_sql = (
        f"INSERT INTO {tref} ({', '.join(insert_cols)}) "
        f"VALUES ({', '.join(insert_vals)})"
    )

    read_cols = [src for src, _, _, _ in plan] + ([geom_col] if geom_col else [])

    async with async_session() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {tref}"))
        await session.execute(text(ddl))
        if not insert_cols:
            # geometry-only file loaded as non-spatial: nothing to insert.
            await session.commit()
            return
        # Blocking parquet decode runs in a thread per batch so the worker's
        # event loop (job heartbeats) stays responsive.
        batches = pf.iter_batches(batch_size=_INSERT_BATCH_ROWS, columns=read_cols)
        while True:
            batch = await asyncio.to_thread(next, batches, None)
            if batch is None:
                break
            cols = [batch.column(i).to_pylist() for i in range(len(read_cols))]
            params: list[dict] = []
            for r in range(batch.num_rows):
                row = {}
                for i, (_, _, _, conv) in enumerate(plan):
                    v = cols[i][r]
                    row[f"p{i}"] = conv(v) if conv else v
                if geom_col is not None:
                    row["geom"] = cols[len(plan)][r]
                params.append(row)
            if params:
                await session.execute(text(insert_sql), params)
        await session.commit()
