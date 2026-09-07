"""Export orchestration: validate params, run ogr2ogr, package output."""

import os
import re
import shutil
import uuid
import zipfile
from urllib.parse import quote

import structlog

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.core.csv_safety import numeric_column_names
from app.processing.export.ogr import FORMAT_MAP, run_ogr2ogr_export
from app.processing.export.where_validator import (
    mask_quoted_literals,
    validate_where_ast,
)
from app.core.runtime.staging import ensure_staging_ready

logger = structlog.stdlib.get_logger(__name__)


# fix(#1532): THE PROPERTY EVERY EXPORT FORMAT MUST KEEP — two
# conversions of unchanged data must produce identical bytes. #1532 keys its
# cached artifact on that digest, so a writer that stamps the conversion
# moment makes every rebuild look new: the selection stays permanently
# `contested`, and a contested selection refuses every range.
# `test_export_artifact_cache_1532.py` pins it per format; a new format needs
# a row there.

# The DOS epoch, the earliest a ZIP directory entry can represent. Chosen for
# the same reason as the GeoPackage constant below: it reads as "deliberately
# not a time" rather than as a wrong one.
_ZIP_FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)

# Regular file, 0644. Pinned rather than copied from the member's own stat
# so the archive can't move with the worker's umask.
#
# DEFLATE level is deliberately NOT pinned: zlib's default already resolves
# to a fixed level, and level 6 output can itself change between zlib
# releases, so pinning would read as a guarantee against an upgrade while
# providing none.
_ZIP_FIXED_EXTERNAL_ATTR = 0o100644 << 16

# dBASE III header: byte 0 is the version, bytes 1..3 are the date of last
# update as (year-1900, month, day). ogr2ogr writes TODAY, so two shapefile
# exports differ across a midnight boundary; rewritten to 1970-01-01.
# Nothing reads this field (verified with ogrinfo), and it's three bytes at
# a fixed offset, so it's patched in place rather than reopened via GDAL.
_DBF_LAST_UPDATE_OFFSET = 1
_DBF_FIXED_LAST_UPDATE = bytes((70, 1, 1))


def _normalize_dbf_date(path: str) -> None:
    """Blank the dBASE last-update date so it cannot vary by build day."""
    with open(path, "r+b") as handle:
        handle.seek(_DBF_LAST_UPDATE_OFFSET)
        handle.write(_DBF_FIXED_LAST_UPDATE)


def _zip_export_files(temp_dir: str, zip_path: str) -> None:
    """DEFLATE every ``export.*`` sidecar in *temp_dir* into *zip_path*.

    Byte-deterministic for unchanged data (see rule above): sorted member
    order (not the filesystem's), a fixed ``date_time`` instead of mtime,
    and stated mode/compression level. Blocking; call via
    ``asyncio.to_thread``.
    """
    members = sorted(f for f in os.listdir(temp_dir) if f.startswith("export."))
    for fname in members:
        if fname.endswith(".dbf"):
            _normalize_dbf_date(os.path.join(temp_dir, fname))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in members:
            member = os.path.join(temp_dir, fname)
            info = zipfile.ZipInfo(fname, date_time=_ZIP_FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _ZIP_FIXED_EXTERNAL_ATTR
            # ZipFile.open() decides ZIP64 from `file_size` alone (normally
            # filled by ZipFile.write() from stat). Without it, a >2 GiB
            # member (#435's payload) raises instead of writing.
            info.file_size = os.path.getsize(member)
            with open(member, "rb") as src, zf.open(info, "w") as dest:
                # Streamed rather than read whole, for the same size reason.
                shutil.copyfileobj(src, dest)


# fix(#1532): the timestamp ogr2ogr stamps into every GeoPackage,
# rewritten to this. Any constant works; the GeoPackage epoch reads as
# "deliberately not a time" rather than a wrong one.
_GPKG_FIXED_LAST_CHANGE = "1970-01-01T00:00:00.000Z"

# Tables the GeoPackage spec gives a timestamp column. `gpkg_contents` is always
# present; the metadata one only when the driver wrote metadata, so both are
# attempted and a missing table is not an error.
_GPKG_TIMESTAMP_COLUMNS = (
    ("gpkg_contents", "last_change"),
    ("gpkg_metadata_reference", "timestamp"),
)

# fix(#1633): SQLite header fields the row-level UPDATEs can't reach —
# offset 24-27 (change counter, bumped per write txn) and offset 92-95
# ("version-valid-for") diverge between otherwise-identical builds because
# ogr2ogr's write path commits a different transaction count under load.
#
# fix(#1633): a FIXED value here would defeat what SQLite
# uses the pair for (detecting another connection's write) — derive it from
# the NORMALIZED content instead so unchanged data still gets one counter.
_GPKG_HEADER_CHANGE_COUNTER_OFFSET = 24
_GPKG_HEADER_VERSION_VALID_FOR_OFFSET = 92
# Never write a change counter of 0 — a brand-new SQLite file always starts
# at 1, so 0 does not read as "a real counter value" even though the format
# does not forbid it.
_GPKG_HEADER_COUNTER_FALLBACK_WHEN_ZERO = 1
# fix(#1633): read/hash size for _stamp_gpkg_header_counters.
# `export_dataset` supports multi-GB GeoPackages under a 2 GiB container
# memory cap, so loading the whole file into a bytearray (then hashlib
# copying it again) could OOM. Both header offsets sit inside byte 0..99, so
# only the FIRST chunk ever needs the zero substitution.
_GPKG_HASH_CHUNK_SIZE = 1024 * 1024


def _stamp_gpkg_header_counters(path: str) -> None:
    """Derive the SQLite change-counter pair from the file's own content.

    fix(#1633): a fixed value would defeat detection of a
    different connection's write; the digest of the file with both counter
    fields zeroed keeps unchanged data on one counter, changed data on
    another. Streamed in chunks (codex P1) — same digest as hashing whole.

    Must run after the sqlite3 connection that did the row-level normalize
    is closed, or writing through it would re-bump the counter it just set.
    """
    import hashlib
    import struct

    zero = b"\x00\x00\x00\x00"
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        first_chunk = True
        while chunk := handle.read(_GPKG_HASH_CHUNK_SIZE):
            if first_chunk:
                chunk = bytearray(chunk)
                chunk[
                    _GPKG_HEADER_CHANGE_COUNTER_OFFSET : _GPKG_HEADER_CHANGE_COUNTER_OFFSET
                    + 4
                ] = zero
                chunk[
                    _GPKG_HEADER_VERSION_VALID_FOR_OFFSET : _GPKG_HEADER_VERSION_VALID_FOR_OFFSET
                    + 4
                ] = zero
                first_chunk = False
            hasher.update(chunk)
    digest = hasher.digest()
    counter = (
        struct.unpack(">I", digest[:4])[0] or _GPKG_HEADER_COUNTER_FALLBACK_WHEN_ZERO
    )
    stamped = struct.pack(">I", counter)

    with open(path, "r+b") as handle:
        handle.seek(_GPKG_HEADER_CHANGE_COUNTER_OFFSET)
        handle.write(stamped)
        handle.seek(_GPKG_HEADER_VERSION_VALID_FOR_OFFSET)
        handle.write(stamped)


def normalize_gpkg_timestamps(path: str) -> None:
    """Make a GeoPackage byte-deterministic for unchanged data.

    ogr2ogr stamps ``gpkg_contents.last_change`` with the conversion moment,
    so identical data produces different bytes, and #1532's cache keys the
    artifact on that digest — every rebuild looked like a DIFFERENT
    representation, so `contested` never cleared and ranges never worked
    for the default format.

    Fixes the digest rather than the rule (distinct bytes SHOULD refuse
    ranges): GeoPackage was reporting a change that hadn't happened.
    GeoJSON already has this property; this gives it to GPKG.

    Uses stdlib sqlite3, not GDAL: the columns are spec-defined, and the
    driver would mean a second full open and rewrite.

    fix(#1633): also derives the SQLite header's change-counter pair from
    the normalized content (see `_stamp_gpkg_header_counters`), since that
    counter is bumped by transaction COUNT, not content.
    """
    import sqlite3

    conn = sqlite3.connect(path)
    normalized = False
    try:
        for table, column in _GPKG_TIMESTAMP_COLUMNS:
            try:
                conn.execute(
                    f"UPDATE {table} SET {column} = ?",  # noqa: S608 - spec-fixed names
                    (_GPKG_FIXED_LAST_CHANGE,),
                )
            except sqlite3.OperationalError:
                # The table is optional in the spec; its absence is not an error.
                continue
        conn.commit()
        normalized = True
    except sqlite3.DatabaseError:
        # Not a SQLite file at all ("file is not a database"). This step
        # exists for cache determinism, not validation: an unopenable
        # GeoPackage is served exactly as ogr2ogr wrote it, and the cache
        # degrades to whole responses on a contested selection rather than a
        # wrong one.
        logger.warning("gpkg_timestamp_normalize_skipped", path=path, exc_info=True)
    finally:
        # Closed explicitly: sqlite3's context manager commits but does NOT
        # close, and an open handle can leave the rollback journal beside the
        # file — which the caller is about to hash.
        conn.close()

    if normalized:
        # fix(#1633): only for a file genuinely opened as SQLite above — the
        # DatabaseError branch already left the invalid file untouched.
        _stamp_gpkg_header_counters(path)


def safe_content_disposition(filename: str) -> str:
    """Build Content-Disposition header with RFC 5987 encoding for non-ASCII filenames."""
    ascii_name = filename.encode("ascii", "replace").decode()
    encoded = quote(filename)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def file_response_content_disposition(filename: str) -> str:
    """Restate starlette ``FileResponse``'s Content-Disposition rule.

    HEAD has no file to hand ``FileResponse``, so the rule (quoted
    ``filename=``, or RFC 5987 ``filename*=`` when percent-encoding
    changes it) is restated here — not ``safe_content_disposition()``,
    which always appends ``filename*`` and would disagree with GET.
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
    # validate_where_ast (v1014 SEC-S09) catches most via AST allowlist, but
    # string-level rejection gives a clearer error and defends against a
    # sqlglot parser bug tolerating a terminator/comment in a future release.
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

    # fix(#1870): the walk reads the code around the values, never the values.
    # A quoted literal is never a column reference, so masking it here cannot
    # admit an unknown column before, after or between literals.
    identifiers = _IDENTIFIER_RE.findall(mask_quoted_literals(where))
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

    fix(#1513): both HEAD and GET read this one function so they can't
    advertise different Content-Type/Disposition.

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
    pmtiles_maxzoom: int | None = None,
    deadline: float | None = None,
) -> tuple[str, str, str]:
    """Export a dataset table to a file.

    Args:
        table_name: PostGIS table name (without schema prefix).
        dataset_name: Human-readable dataset name for the output filename.
        format_key: One of the FORMAT_MAP keys (gpkg, geojson, shp, csv).
        schema: PostgreSQL schema containing ``table_name``.
        target_srs: Optional target CRS (e.g. "EPSG:3857").
        bbox: [minx, miny, maxx, maxy] in WGS84.
        where: Optional SQL WHERE expression.
        column_info: Column metadata for where-clause validation.
        deadline: ``time.monotonic()`` stamp by which the whole request must
            be answered; passed to the ogr2ogr subprocess, which reads what
            is left of it at spawn time (fix(#1778)).

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

    # fix(#435): own the temp directory until a path is handed back to the
    # caller — a failure or cancelled request otherwise left it behind.
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
                pmtiles_maxzoom=pmtiles_maxzoom,
                deadline=deadline,
            )

            # Zip all export.* files. fix(#435): DEFLATE of a multi-GB
            # shapefile is CPU-bound and ran on the event loop, stalling
            # every other request. fix(#435): drained on
            # cancellation so the `except BaseException` rmtree below can't
            # delete temp_dir while the zip thread still writes into it.
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
            # fix(#1686): pmtiles is a single-file format, so THIS
            # call is the one that must carry the extent-budgeted cap — the
            # shp branch above can never be pmtiles.
            pmtiles_maxzoom=pmtiles_maxzoom,
            deadline=deadline,
            # fix(#1778): CSV formula hardening exempts a leading
            # sign only in columns the database calls numeric, so it needs
            # types, not values. Empty for other formats or missing column_info.
            numeric_columns=numeric_column_names(column_info),
        )
        if format_key == "gpkg":
            # fix(#1532): off the event loop, like every other
            # blocking step here — it is a SQLite write over a file that can be
            # gigabytes.
            await run_in_thread_draining(normalize_gpkg_timestamps, output_path)

        return output_path, filename, media_type
    except BaseException:
        # BaseException, not Exception: a client disconnect cancels this task, and
        # asyncio.CancelledError inherits from BaseException on 3.8+.
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
