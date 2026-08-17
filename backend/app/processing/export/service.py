"""Export orchestration: validate params, run ogr2ogr, package output."""

import os
import re
import shutil
import uuid
import zipfile
from urllib.parse import quote

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.processing.export.ogr import FORMAT_MAP, run_ogr2ogr_export
from app.processing.export.where_validator import validate_where_ast
from app.core.runtime.staging import ensure_staging_ready


def _zip_export_files(temp_dir: str, zip_path: str) -> None:
    """DEFLATE every ``export.*`` sidecar in *temp_dir* into *zip_path*.

    Blocking; call via ``asyncio.to_thread``.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(temp_dir):
            if fname.startswith("export."):
                zf.write(os.path.join(temp_dir, fname), fname)


def safe_content_disposition(filename: str) -> str:
    """Build Content-Disposition header with RFC 5987 encoding for non-ASCII filenames."""
    ascii_name = filename.encode("ascii", "replace").decode()
    encoded = quote(filename)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def file_response_content_disposition(filename: str) -> str:
    """Restate starlette ``FileResponse``'s Content-Disposition rule.

    The GET half of this route hands ``filename=`` to ``FileResponse``, which
    derives the header itself (``starlette/responses.py``, ``FileResponse
    .__init__``): a quoted ``filename=`` for names that survive percent-
    encoding unchanged, and an RFC 5987 ``filename*=`` otherwise. HEAD has no
    file to hand it, so the rule is restated here.

    Not ``safe_content_disposition()`` from ``export/service.py``: that one
    always appends ``filename*``, so HEAD would advertise a different header
    than the GET delivers. ``test_head_export_content_disposition_matches_get``
    pins the two byte-for-byte, over both branches, so a starlette change
    fails a test instead of shipping the mismatch.
    """
    quoted = quote(filename)
    if quoted != filename:
        return f"attachment; filename*=utf-8''{quoted}"
    return f'attachment; filename="{filename}"'


# SQL keywords to ignore during where-clause column validation
_SQL_KEYWORDS = frozenset(
    {
        "AND",
        "OR",
        "NOT",
        "IS",
        "NULL",
        "LIKE",
        "IN",
        "BETWEEN",
        "TRUE",
        "FALSE",
        "ASC",
        "DESC",
        "SELECT",
        "FROM",
        "WHERE",
    }
)

# Regex to extract identifiers from a WHERE clause
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Regex to detect numeric literals (integers and decimals)
_NUMERIC_RE = re.compile(r"^\d+(\.\d+)?$")


def validate_where_clause(where: str, column_info: list[dict] | None) -> str:
    """Validate that a WHERE clause only references known columns.

    Args:
        where: SQL WHERE expression string.
        column_info: List of column dicts, each with a "name" key.

    Returns:
        The where string unchanged if valid.

    Raises:
        ValueError: If column_info is missing or an unknown column is referenced.
    """
    if not column_info:
        raise ValueError("Cannot filter: no column info available")

    # IA-P1-04 (Phase 1069): explicit pre-parse rejection of meta-SQL tokens.
    # validate_where_ast (v1014 SEC-S09) catches most of these via AST allowlist,
    # but explicit string-level rejection gives a clearer error and provides
    # defense-in-depth against a sqlglot parser bug that silently tolerates a
    # statement terminator or comment in a future release.
    if ";" in where:
        raise ValueError("WHERE clause must not contain statement terminator ';'")
    if "--" in where:
        raise ValueError("WHERE clause must not contain SQL line comment '--'")
    if "/*" in where or "*/" in where:
        raise ValueError("WHERE clause must not contain SQL block comment '/* */'")
    # Unbalanced single-quote check — count unescaped quotes; legal usage is
    # always even (open + close). SQL '' is the escape sequence so we collapse
    # those first.
    quote_count = where.replace("''", "").count("'")
    if quote_count % 2 != 0:
        raise ValueError("WHERE clause has unbalanced single-quotes")

    # Phase 1062 SEC-S09: AST gate — rejects UNION / subqueries / DDL /
    # function calls that the identifier-only regex below cannot detect.
    validate_where_ast(where)

    # Existing identifier check (defense-in-depth): rejects column names that
    # aren't in this dataset's column_info, even if they parse cleanly.
    valid_names = {col["name"].lower() for col in column_info}

    identifiers = _IDENTIFIER_RE.findall(where)
    for ident in identifiers:
        upper = ident.upper()
        if upper in _SQL_KEYWORDS:
            continue
        if _NUMERIC_RE.match(ident):
            continue
        if ident.lower() not in valid_names:
            raise ValueError(f"Unknown column: {ident}")

    return where


def export_descriptor(dataset_name: str, format_key: str) -> tuple[str, str]:
    """The download's ``(filename, media_type)``, derived WITHOUT exporting.

    fix(#1513): the export route now answers HEAD, and a HEAD must advertise
    the same Content-Type and Content-Disposition its GET would send — while
    running none of the conversion that produces the file. Both verbs read
    this one function so they cannot advertise different things; nothing here
    touches the database or the filesystem.

    Raises:
        ValueError: If format_key is not a supported export format.
    """
    safe_name = re.sub(r"[^\w\-.]", "_", dataset_name)

    if format_key == "parquet":
        # Function-level import: parquet.py imports this module for
        # validate_where_clause, and it pulls pyarrow in with it.
        from app.processing.export.parquet import PARQUET_MEDIA_TYPE

        return f"{safe_name}.parquet", PARQUET_MEDIA_TYPE

    if format_key not in FORMAT_MAP:
        raise ValueError(f"Unsupported export format: {format_key}")

    fmt = FORMAT_MAP[format_key]
    # Shapefile is a multi-file format: ogr2ogr writes the export.* sidecars
    # and the caller ships the zip, so the DOWNLOAD's extension is .zip while
    # fmt["ext"] stays the driver's .shp.
    ext = ".zip" if format_key == "shp" else fmt["ext"]
    return f"{safe_name}{ext}", fmt["media"]


async def export_dataset(
    table_name: str,
    dataset_name: str,
    format_key: str,
    *,
    schema: str,
    target_srs: str | None = None,
    bbox: list[float] | None = None,
    where: str | None = None,
    column_info: list[dict] | None = None,
) -> tuple[str, str, str]:
    """Export a dataset table to a file.

    Args:
        table_name: PostGIS table name (without schema prefix).
        dataset_name: Human-readable dataset name for the output filename.
        format_key: One of the FORMAT_MAP keys (gpkg, geojson, shp, csv).
        schema: PostgreSQL schema containing ``table_name``.
        target_srs: Optional target CRS (e.g. "EPSG:3857").
        bbox: Optional bounding box [minx, miny, maxx, maxy] in WGS84.
        where: Optional SQL WHERE expression.
        column_info: Column metadata for where-clause validation.

    Returns:
        Tuple of (file_path, download_filename, media_type).

    Raises:
        ValueError: If format_key is invalid or where clause references unknown columns.
        ExportError: If ogr2ogr fails.
    """
    if format_key not in FORMAT_MAP:
        raise ValueError(f"Unsupported export format: {format_key}")

    if where is not None:
        validate_where_clause(where, column_info)

    fmt = FORMAT_MAP[format_key]
    driver = fmt["driver"]
    ext = fmt["ext"]
    filename, media_type = export_descriptor(dataset_name, format_key)

    # Verify export staging root before creating per-export temp directories.
    exports_root = ensure_staging_ready(
        os.path.join(settings.upload_staging_dir, "exports")
    )

    # Create unique temp directory for this export.
    export_id = uuid.uuid4().hex
    temp_dir_path = exports_root / export_id
    temp_dir_path.mkdir(parents=False, exist_ok=False)
    temp_dir = str(temp_dir_path)

    # fix(#435): own the temp directory until we hand a path back to the caller.
    # ogr2ogr failure, an oversized ZIP, or a cancelled request used to leave the
    # directory behind until some later process startup swept it.
    try:
        if format_key == "shp":
            # Shapefile: ogr2ogr outputs multiple files, then zip them
            ogr_output = os.path.join(temp_dir, f"export{ext}")
            await run_ogr2ogr_export(
                table_name,
                ogr_output,
                driver,
                schema=schema,
                target_srs=target_srs,
                bbox=bbox,
                where=where,
                format_key=format_key,
            )

            # Zip all export.* files. fix(#435): DEFLATE of a multi-GB shapefile
            # is CPU-bound and ran on the event loop, stalling every other request
            # (and job heartbeats) for the duration. fix(#435 codex r4): drained on
            # cancellation so the `except BaseException` rmtree below cannot delete
            # temp_dir while the zip thread is still writing into it.
            zip_path = os.path.join(temp_dir, filename)
            await run_in_thread_draining(_zip_export_files, temp_dir, zip_path)

            return zip_path, filename, media_type

        # Single-file formats
        output_path = os.path.join(temp_dir, filename)
        await run_ogr2ogr_export(
            table_name,
            output_path,
            driver,
            schema=schema,
            target_srs=target_srs,
            bbox=bbox,
            where=where,
            format_key=format_key,
        )

        return output_path, filename, media_type
    except BaseException:
        # BaseException, not Exception: a client disconnect cancels this task, and
        # asyncio.CancelledError inherits from BaseException on 3.8+.
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
