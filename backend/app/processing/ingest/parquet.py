"""GeoParquet ingest reader/loader (pyarrow).

The Debian GDAL build ships without the Arrow/Parquet driver, so ogrinfo/
ogr2ogr cannot read ``.parquet`` uploads. Preview metadata comes straight
from pyarrow, and the loader writes rows into PostGIS through the app's own
connection, producing the same table shape ``run_ogr2ogr`` creates (``gid``
serial PK, laundered lowercase column names, a ``_geolens_geom`` column
``ensure_geom_column`` later renames to ``geom``) so the rest of the ingest
pipeline runs unchanged.

Supports GeoParquet 1.0/1.1 with WKB geometry encoding. Files without ``geo``
metadata ingest as non-spatial tables (same as a CSV without geometry).
"""

import asyncio
import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

if TYPE_CHECKING:
    from app.processing.ingest.ogr import OgrinfoResult

_INSERT_BATCH_ROWS = 5000

# The 500 MB upload cap is a weak proxy for a parquet file's work: it
# compresses well, and this loader runs in-process with no subprocess timeout
# (unlike ogr2ogr's OGR2OGR_FILE_TIMEOUT_SECONDS). So both ceilings are checked
# from the footer's row count before any row is written. Cells bound the work
# because a wide table costs more at the same row count; geometry counts as a
# cell even though ``plan`` skips it, or the ceiling would be understated.
_MAX_TOTAL_ROWS = 5_000_000
_MAX_TOTAL_CELLS = 100_000_000


def _check_ingest_budget(num_rows: int, num_columns: int) -> None:
    """Reject a parquet file whose footer already says it is too big.

    Raises ``IngestBudgetExceededError`` naming the limit and the observed
    value.
    """
    from app.processing.ingest.ogr import IngestBudgetExceededError

    if num_rows > _MAX_TOTAL_ROWS:
        raise IngestBudgetExceededError(
            f"Parquet file has {num_rows:,} rows, above the "
            f"{_MAX_TOTAL_ROWS:,}-row ingest limit. Split the file or load a "
            "subset.",
            code="ingest_row_limit_exceeded",
            values={"rows": num_rows, "limit": _MAX_TOTAL_ROWS},
        )
    cells = num_rows * num_columns
    if cells > _MAX_TOTAL_CELLS:
        raise IngestBudgetExceededError(
            f"Parquet file has {cells:,} cells ({num_rows:,} rows x "
            f"{num_columns:,} columns), above the {_MAX_TOTAL_CELLS:,}-cell "
            "ingest limit. Split the file or drop columns you do not need.",
            code="ingest_cell_limit_exceeded",
            values={"cells": cells, "limit": _MAX_TOTAL_CELLS},
        )


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

    An OMITTED ``crs`` key means OGC:CRS84 (4326); explicit
    ``"crs": null`` means unknown/unassigned. Either that or a PROJJSON
    without a resolvable EPSG id returns None so Missing-CRS/srid_override
    handling applies.
    """
    if "crs" not in col_meta:  # omitted -> OGC:CRS84
        return 4326
    crs = col_meta["crs"]
    if not isinstance(crs, dict):  # explicit null -> unknown CRS
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
        # signed <=32-bit fits integer; int64/uint32 fit bigint; uint64 can
        # exceed bigint's max so it gets numeric.
        if pa.types.is_unsigned_integer(t) and t.bit_width == 64:
            return "numeric"
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


def _wkb_dimensions(wkb: bytes) -> tuple[bool, bool]:
    """Header-only (has Z, has M) sniff for EWKB flags and ISO type ranges.

    Reads the 5-byte header instead of a full shapely parse, so a
    whole-column scan stays cheap.
    """
    if not wkb or len(wkb) < 5:
        return False, False
    order = "little" if wkb[0] == 1 else "big"
    gtype = int.from_bytes(wkb[1:5], order)
    if gtype & 0xE0000000:  # EWKB flag bits (Z / M / SRID) present
        return bool(gtype & 0x80000000), bool(gtype & 0x40000000)
    iso = (gtype // 1000) % 4  # 1000+base = Z, 2000+base = M, 3000+base = ZM
    return iso in (1, 3), iso in (2, 3)


def _geometry_dimensions(
    pf: "pq.ParquetFile", geom_col: str, col_meta: dict
) -> tuple[bool, bool]:
    """(has Z, has M) for the geometry column (blocking).

    GeoParquet metadata marks 3D variants with a " Z", " M" or
    " ZM" suffix in ``geometry_types``; an empty list (e.g. our own exporter)
    is scanned row-by-row, stopping once both are found, so a late-file Z or M
    row can't slip past a 2D typmod.
    """
    declared = [g for g in (col_meta.get("geometry_types") or []) if g]
    if declared:
        return (
            any(g.endswith((" Z", " ZM")) for g in declared),
            any(g.endswith((" M", " ZM")) for g in declared),
        )
    has_z = has_m = False
    for batch in pf.iter_batches(batch_size=4096, columns=[geom_col]):
        for wkb in batch.column(0).to_pylist():
            if wkb is None:
                continue
            z, m = _wkb_dimensions(wkb)
            has_z, has_m = has_z or z, has_m or m
            if has_z and has_m:
                return True, True
    return has_z, has_m


def _json_safe(v: Any) -> Any:
    # NaN/Infinity would 500 the preview response — Starlette
    # serializes JSON with allow_nan=False. Render them as null.
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def _open_and_inspect(file_path: str) -> tuple[pq.ParquetFile, dict]:
    """Open a parquet file and derive the ogrinfo-shaped metadata (blocking)."""
    pf = pq.ParquetFile(file_path)
    geo = _read_geo_metadata(pf)
    geom_col, col_meta = _geometry_column(geo)
    skip = {geom_col, _covering_column(geo, geom_col)} - {None}

    # The loader's footer gate, applied here too: this runs before the loader,
    # and the geometry probe below scans until the first non-NULL WKB,
    # unbounded on a file with millions of leading NULLs. The column count
    # assumes the geometry column is present (preview doesn't know
    # include_geometry), the conservative direction for a gate.
    _check_ingest_budget(
        pf.metadata.num_rows,
        sum(1 for f in pf.schema_arrow if f.name not in skip)
        + (1 if geom_col is not None else 0),
    )

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

    Uses executemany inserts, not COPY, which is fine up to a few million
    rows.
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

    # Before anything reads row data: _geometry_dimensions below decodes the
    # whole geometry column when geometry_types isn't declared (true of our
    # own exporter's files). Everything above reads footer metadata only.
    _check_ingest_budget(
        pf.metadata.num_rows, len(plan) + (1 if geom_col is not None else 0)
    )

    def _q(ident: str) -> str:
        return '"' + ident.replace('"', '""') + '"'

    has_z = has_m = False
    if geom_col is not None:
        has_z, has_m = await asyncio.to_thread(
            _geometry_dimensions, pf, geom_col, col_meta
        )

    ddl_cols = ["gid serial PRIMARY KEY"]
    ddl_cols += [f"{_q(pg_name)} {pg_type}" for _, pg_name, pg_type, _ in plan]
    if geom_col is not None:
        # A 2D typmod rejects Z WKB ("Geometry has Z dimension but column
        # does not"), so the type follows the source's dimensions.
        gtype = {
            (True, True): "GeometryZM",
            (True, False): "GeometryZ",
            (False, True): "GeometryM",
        }.get((has_z, has_m), "Geometry")
        ddl_cols.append(f"_geolens_geom geometry({gtype}, {int(srid)})")

    insert_cols = [_q(pg_name) for _, pg_name, _, _ in plan]
    insert_vals = [f":p{i}" for i in range(len(plan))]
    if geom_col is not None:
        insert_cols.append("_geolens_geom")
        # explicit cast: ST_GeomFromWKB has bytea AND text overloads, and an
        # untyped bind (e.g. an all-NULL batch) would be ambiguous.
        wkb_expr = f"ST_GeomFromWKB(CAST(:geom AS bytea), {int(srid)})"
        # Lift lower-dimension rows (missing Z or M becomes 0) so
        # the typed column accepts mixed-dimension sources.
        lift = {
            (True, True): "ST_Force4D",
            (True, False): "ST_Force3D",
            (False, True): "ST_Force3DM",
        }.get((has_z, has_m))
        insert_vals.append(f"{lift}({wkb_expr})" if lift else wkb_expr)

    tref = _qtable(table_name, schema=schema)
    ddl = f"CREATE TABLE {tref} ({', '.join(ddl_cols)})"
    insert_sql = (
        f"INSERT INTO {tref} ({', '.join(insert_cols)}) "
        f"VALUES ({', '.join(insert_vals)})"
    )

    read_cols = [src for src, _, _, _ in plan] + ([geom_col] if geom_col else [])

    if not insert_cols:
        # A geometry-only file loaded as non-spatial would publish an empty
        # dataset.
        from app.processing.ingest.ogr import IngestionError

        raise IngestionError(
            "Parquet file contains only a geometry column; loading it "
            "without geometry would produce an empty dataset."
        )

    async with async_session() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {tref}"))
        await session.execute(text(ddl))
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
