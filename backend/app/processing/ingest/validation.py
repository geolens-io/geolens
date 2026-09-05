"""Upload file validation: magic bytes, zip safety, size limits.

Validates uploaded files beyond extension checks:
- Content-type verification via magic byte detection (puremagic), plus
  direct header sniffs for formats puremagic has no signature for (Parquet,
  FlatGeobuf)
- ZIP archive safety (compression ratio, nested archives, decompressed size)
- File size enforcement against configured limits
- VRT XML sniff + path-traversal guard on `<SourceFilename>` body (IA-P1-03)
"""

import codecs
import os
import re
import sqlite3
import struct
import tempfile
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path

from defusedxml import ElementTree as ET
import puremagic
import structlog

from app.core.upload_errors import UnsafeUploadError  # noqa: F401  (re-exported)
from app.core.url_redaction import redact_url_credentials

logger = structlog.get_logger()

# --- Constants ---

HEADER_READ_SIZE = 8192

# Maps file extension to set of acceptable puremagic-detected extensions
EXTENSION_CONTENT_MAP: dict[str, set[str]] = {
    ".zip": {".zip"},
    ".gpkg": {".gpkg", ".sqlite", ".db", ".sqlite3"},
    ".geojson": {".json", ".geojson"},
    ".json": {".json", ".geojson"},
    ".csv": {".csv", ".txt", ""},
    ".tif": {".tif", ".tiff"},
    ".tiff": {".tif", ".tiff"},
    ".xlsx": {".xlsx", ".zip", ".docx"},  # OOXML shares ZIP container
    ".xls": {".xls", ".doc"},  # Old BIFF format
    # KML is XML; puremagic reports `.xml` for the usual `<?xml` prologue and
    # nothing for a bare `<kml>` root, which the XML fallback below covers.
    ".kml": {".xml", ".kml"},
    # A KMZ is a zipped KML. puremagic reads the zip container and reports
    # `.docx` for it, the same OOXML confusion `.xlsx` already carries.
    ".kmz": {".kmz", ".zip", ".docx"},
}

# Maximum uploaded VRT XML size. User-provided VRTs are control-plane XML, not
# raster payloads; fail closed instead of partially scanning a prefix.
VRT_BODY_MAX_BYTES = 2 * 1024 * 1024

_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")

# Parquet files start AND end with this 4-byte magic; a missing footer magic
# is the standard truncation signal (the footer holds all file metadata).
_PARQUET_MAGIC = b"PAR1"

# FlatGeobuf's 8-byte magic is "fgb" + a major-version byte + "fgb" + a patch
# byte. Only the two literals are checked: pinning the version bytes would
# reject a file written by a newer FlatGeobuf that GDAL still reads fine.
_FGB_MAGIC_WORD = b"fgb"
_FGB_MAGIC_SIZE = 8

# XML byte-order marks, widest first: BOM_UTF32_LE begins with BOM_UTF16_LE,
# so checking UTF-16 first would read a UTF-32 document as UTF-16.
_XML_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# XML 1.0 Appendix F: with no BOM, a UTF-16/32 document is recognised from how
# the opening `<` is padded. Same assumption the spec makes — that the document
# begins with the `<`, not with whitespace.
_UNMARKED_WIDE_XML_PREFIXES = (
    b"\x00\x00\x00<",
    b"<\x00\x00\x00",
    b"\x00<",
    b"<\x00",
)

# ZIP bomb thresholds
MAX_COMPRESSION_RATIO = 500
MAX_DECOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_ARCHIVE_ENTRIES = 10_000
MAX_CENTRAL_DIRECTORY_BYTES = 32 * 1024 * 1024
ZIP_CONTAINER_EXTENSIONS = frozenset({".zip", ".xlsx", ".kmz"})

_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_CENTRAL_FILE_SIGNATURE = b"PK\x01\x02"
_CENTRAL_DIGITAL_SIGNATURE = b"PK\x05\x05"
_EOCD = struct.Struct("<4s4H2LH")
_ZIP64_LOCATOR = struct.Struct("<4sLQL")
_ZIP64_EOCD = struct.Struct("<4sQ2H2L4Q")
_CENTRAL_FILE_HEADER = struct.Struct("<4s6H3L5H2L")

ARCHIVE_EXTENSIONS = frozenset(
    {
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".rar",
        ".7z",
        ".bz2",
        ".xz",
    }
)

# fix(#1846, GHSA-hrf5-v3cq-frx5): a GDAL VRT is a set of instructions, not
# data -- it names the source GDAL should go and read, and that source may be
# any local path or any URL. `_reject_standalone_vrt` in ingest/router.py
# already refuses one as the uploaded file, but it matches the TOP-LEVEL
# filename, so the same document arriving as an archive member walked straight
# past it. Refused here at any depth and in any case.
#
# Extensions only, and deliberately not the whole answer: the drivers that read
# a document as instructions do not all agree to be identified by name (the WFS
# driver identifies on content alone, whatever the member is called). The
# layers that do not depend on the name are the input-driver allowlist in
# `ingest/gdal_drivers.py` and the GDAL_SKIP clamp in `raster/vrt.py`. This one
# is here because refusing at the door is a better answer than refusing at the
# driver when the name is honest, which for an ordinary upload it is.
DRIVER_METADATA_EXTENSIONS = frozenset({".vrt"})


# fix(#1846, GHSA-hrf5-v3cq-frx5): a SQLite database is also a document that
# can name external files. SQLite's virtual-table mechanism lets a schema row
# say "this table's rows come from over there", and the SpatiaLite extension
# the shipped GDAL links provides a family of modules whose "over there" is an
# arbitrary local path. A GeoPackage is a SQLite database the uploader writes
# in full, so the instructions and the data arrive in one legitimate `.gpkg`.
#
# Neither of the two driver clamps can reach this one. GPKG is the primary
# supported upload format and SQLite is its sibling, so neither can be dropped
# from the input allowlist or added to GDAL_SKIP, and the member name is honest
# because the file really is a GeoPackage. Measured ineffective on the shipped
# GDAL: SPATIALITE_SECURITY=strict, OGR_SQLITE_LOAD_EXTENSIONS=NONE,
# OGR_SQLITE_LIST_ALL_TABLES=NO. What is left is to read the schema ourselves
# and refuse the file, which is what `validate_sqlite_virtual_tables` does.
SQLITE_FAMILY_EXTENSIONS = frozenset({".gpkg", ".sqlite", ".sqlite3", ".db"})

# THE RULE FOR ARCHIVE MEMBERS, learned twice and at the cost of a finding
# each time: identify a member by its CONTENT, never by its name.
#
# GDAL never consults the member name. It asks each driver whether it
# recognises the bytes, and those answers are content tests: the SQLite family
# checks for a 16-byte header at offset 0, and the OGR VRT driver SEARCHES the
# leading bytes for its root element -- a substring search, so a byte-order
# mark, an XML declaration, a comment or arbitrary junk in front of it change
# nothing. Measured on GDAL 3.10.3 and 3.13.0.
#
# So an extension filter over archive members is not a filter. A database
# named `evil.bak`, `evil` or `data/evil.dat` is opened as SQLite exactly as
# `inner.gpkg` would be, and the first version of this check walked past all
# three. `DRIVER_METADATA_EXTENSIONS` above is a cheap early refusal for the
# honest case and is NOT the defense; `_scan_archive_members` is.
_SQLITE_HEADER = b"SQLite format 3\x00"
# Both VRT roots: the vector one is the finding, the raster one is here so the
# rule has no shape-shaped hole left in it.
_VRT_ROOT_MARKERS = (b"<OGRVRTDataSource", b"<VRTDataset")
# The window the markers are searched in, and the per-member cost of the scan.
# GDAL identifies from a few kilobytes; this matches that order.
MEMBER_SNIFF_BYTES = 4096

# The virtual-table modules an upload may declare. An ALLOWLIST, because the
# question is not "which modules are dangerous" (the SpatiaLite family alone
# has a dozen, and a future release adds more) but "which does a legitimate
# GeoPackage or SpatiaLite database need". Measured by writing one with the
# shipped GDAL: a GPKG carries `rtree` only, and `ogr2ogr -f SQLite -dsco
# SPATIALITE=YES` adds VirtualSpatialIndex, VirtualElementary and VirtualKNN2.
# Every one of these reads only the database's own tables.
#
# To widen it, add the module AND say here what writes it and what it reads.
# The refused set includes, among others, VirtualText, VirtualDbf, VirtualShape,
# VirtualXL, VirtualGPX, VirtualGeoJSON, VirtualXPath and VirtualBBox (all of
# which name an external file) and VirtualPostGIS, VirtualODBC, VirtualFDO and
# VirtualNetwork (which reach a database or a network), plus SQLite's own
# `csv`, `zipfile`, `fileio` and `fsdir` modules where a build provides them.
ALLOWED_VIRTUAL_TABLE_MODULES = frozenset(
    {
        "rtree",
        "rtree_i32",
        "geopoly",
        "virtualspatialindex",
        "virtualelementary",
        "virtualknn",
        "virtualknn2",
    }
)

# Bound the schema scan two ways. A database whose schema is larger than this
# is not one we can reason about, and reading it is not free -- and the walk
# above is linear, not free, so the bytes need their own ceiling rather than
# only the row count. 4 MB is far above any real GeoPackage schema.
MAX_SQLITE_SCHEMA_ROWS = 100_000
MAX_SQLITE_SCHEMA_BYTES = 4 * 1024 * 1024

# Comment stripping is a single left-to-right walk, not a regex.
#
# `re.compile(r"/\*.*?\*/", re.DOTALL)` is quadratic on text holding many `/*`
# with no `*/`: every opener restarts a lazy scan that runs to the end of the
# string. That text is uploader-chosen through a perfectly valid schema (a
# column DEFAULT is enough), the scan runs synchronously, and this used to be
# reachable from preview. Measured: 32 KB 0.9 s, 64 KB 3.6 s, 128 KB 11.5 s.
#
# The "standard linear block comment" pattern
# `r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/"` does NOT fix it, which is worth writing
# down because it looks like it should: it is linear for TERMINATED comments,
# but with no terminator it still scans forward from every opener. Measured on
# the same input it was slower than the lazy pattern (6.3 s at 64 KB).
#
# The walk below is O(n) with a `str.find` per construct: 4 MB in about 2 ms.
# It also respects quoting, which no comment regex can, so a `--` or `/*`
# inside a string literal stays inside it and a quoted identifier containing
# `USING` cannot fool the module match further down.
_SQL_QUOTE_PAIRS = {"'": "'", '"': '"', "`": "`", "[": "]"}
# Deliberately looser than the module pattern below, and matched on the
# normalised statement: anything that looks at all like a virtual table has to
# reach the module check, where an unreadable spelling is refused rather than
# skipped. A pre-filter that anchored on CREATE would be one more place a
# spelling could slip through unexamined.
_VIRTUAL_TABLE_RE = re.compile(r"\bVIRTUAL\s+TABLE\b", re.IGNORECASE)
# A SQLite identifier: bare, or quoted four different ways, and a quoted one
# may contain spaces. Spelling this out rather than using a character class
# matters for a real GeoPackage: its spatial index is named after the layer, so
# a layer called "my layer" produces `CREATE VIRTUAL TABLE "rtree_my layer_geom"
# USING rtree(...)`, and a class-based name pattern would fail to read the
# module there and refuse a legitimate upload.
_SQLITE_NAME = r"""(?:"[^"]*"|'[^']*'|\[[^\]]*\]|`[^`]*`|\w+)"""
_VIRTUAL_MODULE_RE = re.compile(
    r"\bCREATE\s+(?:TEMP\s+|TEMPORARY\s+)?VIRTUAL\s+TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?:{_SQLITE_NAME}\s*\.\s*)?{_SQLITE_NAME}\s+"
    rf"USING\s+({_SQLITE_NAME})",
    re.IGNORECASE,
)
_ATTACH_RE = re.compile(r"\bATTACH\s+(?:DATABASE\b|[\'\"])", re.IGNORECASE)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments in one pass, leaving quoted text untouched."""
    out: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == "-" and sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline < 0 else newline
            continue
        if char == "/" and sql.startswith("/*", index):
            close = sql.find("*/", index + 2)
            # An unterminated block comment runs to the end, which is what
            # SQLite does with it too.
            index = length if close < 0 else close + 2
            out.append(" ")
            continue
        closer = _SQL_QUOTE_PAIRS.get(char)
        if closer is not None:
            close = sql.find(closer, index + 1)
            end = length if close < 0 else close + 1
            out.append(sql[index:end])
            index = end
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _describe(source: str | None) -> str:
    """How to name the refused file to the user.

    ``None`` when the caller had no user-visible filename to give -- the
    preview knows only the staging path, and a staging basename carries the job
    id and the temp prefix, which is exactly the leak
    ``_friendly_open_failure_message`` exists to avoid in ``ingest/ogr.py``.
    """
    return f"'{source}'" if source else "The uploaded file"


def _refuse_virtual_table(entry: str, module: str | None, source: str | None) -> None:
    logger.warning(
        "Upload declares an external-source virtual table",
        event_type="security",
        reason="sqlite_virtual_table",
        filename=source,
        entry=entry,
        module=module,
    )
    raise UnsafeUploadError(
        f"{_describe(source)} declares the virtual table '{entry}', which "
        "tells the database engine to read its rows from somewhere outside "
        "the file. Uploads may only carry their own data. Export the layers "
        "you want as ordinary tables and upload that."
    )


# The two SQLite result codes that mean "this is not a database I can read",
# as opposed to "I could not get at it". Kept as a named set because the
# difference decides whether this check speaks or stands aside.
_NOT_A_READABLE_DATABASE = frozenset({sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT})


def _handle_unreadable_database(exc: sqlite3.Error, source: str | None) -> None:
    """Decide whether an open failure is this check's to report.

    A file whose bytes are not a database has no schema to name an outside
    source, and GDAL -- reading it through the same SQLite -- will not read it
    either. `validate_file_content` already refuses a `.gpkg` whose magic bytes
    are not a database, and `ingest/ogr.py` has a carefully worded message for
    the open failure that follows. Answering "not a database" here would only
    replace that message with a worse one, so those two codes stand aside.

    Anything else -- a permission problem, an encrypted file, a code this does
    not recognise -- is a file this cannot vouch for, and it refuses.
    """
    if getattr(exc, "sqlite_errorcode", None) in _NOT_A_READABLE_DATABASE:
        return
    raise UnsafeUploadError(
        f"{_describe(source)} could not be read as a database file."
    ) from exc


def _scan_sqlite_schema(db_path: str, source: str | None) -> None:
    """Refuse a SQLite database whose schema names an outside source.

    Opened through the stdlib driver in read-only immutable mode, so no page is
    written, no journal is replayed, and nothing in the schema is instantiated
    -- a virtual table's module is loaded on first ACCESS to the table, and
    reading ``sqlite_master`` is not that. The raw ``sql`` column is what is
    inspected: ``PRAGMA`` output reports a virtual table as an ordinary one and
    would show none of this.

    ``immutable=1`` also means a sidecar ``-wal``/``-journal`` is ignored rather
    than replayed, so in principle this could read an older schema than a
    replaying reader would. It cannot here: a top-level upload is one staged
    file with no sidecar, and an archive member is copied out on its own.
    """
    if not os.path.isfile(db_path):
        # Not a refusal: there is no content to judge. A staged file that is
        # gone is an operational failure the callers already report in their
        # own words ("Staging file no longer available", or GDAL's friendly
        # open failure), and answering "not a database" here would replace a
        # true message with a misleading one.
        return
    # as_uri() percent-encodes, so a staging path containing ? or # cannot
    # smuggle extra URI parameters past the two set here.
    uri = f"{Path(os.path.abspath(db_path)).as_uri()}?mode=ro&immutable=1"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True)
        # Ask the size before reading the text, so an oversized schema is
        # refused rather than materialised and walked.
        (total_bytes,) = connection.execute(
            "SELECT COALESCE(SUM(LENGTH(sql)), 0) FROM sqlite_master "
            "WHERE sql IS NOT NULL"
        ).fetchone()
        if total_bytes > MAX_SQLITE_SCHEMA_BYTES:
            raise UnsafeUploadError(
                f"{_describe(source)} declares "
                f"{total_bytes // (1024 * 1024)} MB of schema, more than the "
                f"{MAX_SQLITE_SCHEMA_BYTES // (1024 * 1024)} MB an upload is "
                "checked for."
            )
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL "
            f"LIMIT {MAX_SQLITE_SCHEMA_ROWS + 1}"
        ).fetchall()
    except sqlite3.Error as exc:
        _handle_unreadable_database(exc, source)
        return
    finally:
        if connection is not None:
            connection.close()

    if len(rows) > MAX_SQLITE_SCHEMA_ROWS:
        # Truncating the scan would mean the rows past the cap were never
        # looked at, which is the one outcome this must not produce quietly.
        raise UnsafeUploadError(
            f"{_describe(source)} declares more than {MAX_SQLITE_SCHEMA_ROWS} "
            "schema objects, which is more than an upload is checked for."
        )

    for name, sql in rows:
        # Comments stripped and whitespace collapsed BEFORE anything is
        # matched: SQLite accepts a statement split across lines and
        # interrupted by comments, so a pattern that did not normalise first
        # would answer "no virtual table here" to a spelling the engine reads
        # perfectly well.
        statement = " ".join(_strip_sql_comments(sql or "").split())
        entry = name or "?"
        if _ATTACH_RE.search(statement):
            _refuse_virtual_table(entry, "ATTACH", source)
        if not _VIRTUAL_TABLE_RE.search(statement):
            continue
        match = _VIRTUAL_MODULE_RE.search(statement)
        if match is None:
            # A virtual table whose module this cannot read confidently. The
            # engine will read it; refusing is the only honest answer.
            _refuse_virtual_table(entry, None, source)
            return
        module = match.group(1).strip("\"'[]`").lower()
        if module not in ALLOWED_VIRTUAL_TABLE_MODULES:
            _refuse_virtual_table(entry, module, source)


# Reading a member to its end makes zipfile verify the CRC, and a member whose
# compressed bytes are damaged raises from the archive rather than from us.
# None of these is a ValueError, and every door above maps ValueError -- the
# upload gauntlet's docstring promises it and `tasks_vector` catches exactly
# that -- so an ordinary truncated upload would fail its job with an uncaught
# exception instead of the refusal the caller is meant to see.
#
# `validate_zip_safety` never reads member DATA (it works from the central
# directory), so it cannot have caught this on the way past: the conversion has
# to live at the reads.
# RuntimeError is what zipfile raises for a password-protected member and
# NotImplementedError for a compression method it does not implement. Neither
# is a ValueError, `validate_zip_safety` passes both (it never reads member
# data), and both are ordinary things to find in an upload rather than bugs --
# so both belong here with the corruption cases. The tuple is narrow and only
# wraps the member reads, so a genuine RuntimeError from elsewhere is untouched.
_CORRUPT_MEMBER_ERRORS = (
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
    RuntimeError,
    NotImplementedError,
)


@contextmanager
def _member_read_errors(entry: str):
    """Turn a damaged member into the same refusal shape every door maps."""
    try:
        yield
    except _CORRUPT_MEMBER_ERRORS as exc:
        raise UnsafeUploadError(
            f"The archive entry '{entry}' could not be read. The upload may be "
            "corrupt, truncated, password-protected, or compressed with a "
            "method this server does not support."
        ) from exc


class _ScanBudget:
    """Decompressed bytes the archive scan may spend, in total.

    A per-member bound is not a bound: ten thousand members each just under
    the per-member limit is ten thousand times the limit. This is the budget
    for the whole walk, and it is the same total ``validate_zip_safety``
    allows the archive to hold, so the scan can never decompress more than the
    archive was permitted to contain.
    """

    def __init__(self, limit: int) -> None:
        self.remaining = limit

    def spend(self, count: int, entry: str) -> None:
        self.remaining -= count
        if self.remaining < 0:
            raise UnsafeUploadError(
                f"Reading '{entry}' would take this upload past the "
                f"{MAX_DECOMPRESSED_BYTES // (1024**3)} GB decompressed limit."
            )


def _member_head(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, budget: _ScanBudget
) -> bytes:
    """The leading bytes GDAL would identify this member by."""
    with _member_read_errors(info.filename):
        with archive.open(info) as member:
            head = member.read(MEMBER_SNIFF_BYTES)
    budget.spend(len(head), info.filename)
    return head


def _refuse_vrt_member(entry: str, source: str | None) -> None:
    logger.warning(
        "Archive member carries GDAL driver metadata",
        event_type="security",
        reason="driver_metadata_member",
        filename=source,
        entry=entry,
    )
    raise UnsafeUploadError(
        f"The archive entry '{entry}' is a GDAL VRT. A VRT describes where to "
        "read data from rather than carrying any, so it is not accepted "
        "inside an upload. Upload the data files themselves."
    )


def _copy_member_bounded(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: str,
    budget: _ScanBudget,
) -> None:
    """Copy one archive member out, against the shared scan budget."""
    with _member_read_errors(info.filename):
        with archive.open(info) as member, open(destination, "wb") as out:
            while True:
                chunk = member.read(1024 * 1024)
                if not chunk:
                    break
                budget.spend(len(chunk), info.filename)
                out.write(chunk)


def _scan_archive_members(file_path: str, filename: str | None) -> None:
    """Refuse an archive whose members instruct GDAL to read somewhere else.

    Every member is judged by its leading bytes, never by its name -- see the
    rule beside ``_SQLITE_HEADER``. A member GDAL would open as SQLite has its
    schema read; a member carrying a VRT root is refused outright.

    ``validate_zip_safety`` runs FIRST, so the entry count, the per-entry
    compression ratio and the declared total are bounded before a single byte
    is decompressed here. On the preview path this runs before the ingest
    task's own call, so it cannot inherit that guarantee -- it has to ask for
    it. What is left is then held to one shared budget.
    """
    if not os.path.isfile(file_path):
        return  # same reasoning as _scan_sqlite_schema
    try:
        validate_zip_safety(file_path)
    except UnsafeUploadError:
        raise
    except ValueError as exc:
        # The same refusal, raised as this module's own class so the endpoints
        # that let a content refusal's wording through let this one through
        # too instead of flattening it into a generic message.
        raise UnsafeUploadError(str(exc)) from exc

    budget = _ScanBudget(MAX_DECOMPRESSED_BYTES)
    try:
        archive = zipfile.ZipFile(file_path, "r")
    except zipfile.BadZipFile as exc:
        # `validate_zip_safety` above would normally have refused this already;
        # kept because the guard belongs with the open, not with whatever ran
        # before it (a previous revision had it and the rewrite dropped it).
        raise UnsafeUploadError("File is not a valid ZIP container.") from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            entry = f"{filename}:{info.filename}" if filename else info.filename
            head = _member_head(archive, info, budget)
            if any(marker in head for marker in _VRT_ROOT_MARKERS):
                _refuse_vrt_member(info.filename, filename)
            if not head.startswith(_SQLITE_HEADER):
                continue
            handle, staged = tempfile.mkstemp(
                suffix=Path(info.filename).suffix,
                dir=Path(file_path).parent,
            )
            os.close(handle)
            try:
                _copy_member_bounded(archive, info, staged, budget)
                _scan_sqlite_schema(staged, entry)
            finally:
                Path(staged).unlink(missing_ok=True)


def validate_content_directives(file_path: str, filename: str | None = None) -> None:
    """Refuse an upload whose content tells GDAL to read somewhere else.

    Two shapes, one question. A top-level SQLite-family file has its schema
    read, because a virtual-table module can name a source outside the
    database. An archive has every member judged BY CONTENT: one GDAL would
    open as SQLite is scanned the same way, and one carrying a VRT root is
    refused.

    A top-level file is still matched by extension, and that is sound where an
    archive member is not: the declared extension is exactly what
    ``local_input_driver_args`` hands GDAL as ``-if``, so for that file the
    declared extension IS the driver set. Inside an archive GDAL sees every
    member and chooses for itself, which is the whole of the rule beside
    ``_SQLITE_HEADER``.

    Raises:
        UnsafeUploadError: when the content names a source outside the file,
            when the archive fails the bomb checks, or when a database cannot
            be opened for a reason that is not "these bytes are not a
            database" -- see ``_handle_unreadable_database`` for why that one
            case stands aside instead.
    """
    # A staging basename is not a user-visible name; see `_describe`.
    source = filename
    suffix = Path(source or file_path).suffix.lower()
    if suffix in SQLITE_FAMILY_EXTENSIONS:
        _scan_sqlite_schema(file_path, source)
        return
    if suffix in ZIP_CONTAINER_EXTENSIONS:
        _scan_archive_members(file_path, source)


def _zip_directory_metadata(file_path: str) -> tuple[int, int, int]:
    """Return member count, central-directory offset, and size without parsing members."""
    path = Path(file_path)
    file_size = path.stat().st_size
    tail_size = min(file_size, _EOCD.size + 65_535)

    with path.open("rb") as archive:
        archive.seek(file_size - tail_size)
        tail = archive.read(tail_size)

        search_end = len(tail)
        eocd_offset = -1
        eocd: tuple | None = None
        while search_end > 0:
            candidate = tail.rfind(_EOCD_SIGNATURE, 0, search_end)
            if candidate < 0:
                break
            if candidate + _EOCD.size <= len(tail):
                unpacked = _EOCD.unpack_from(tail, candidate)
                comment_length = unpacked[7]
                if candidate + _EOCD.size + comment_length == len(tail):
                    eocd_offset = file_size - tail_size + candidate
                    eocd = unpacked
                    break
            search_end = candidate

        if eocd is None:
            raise zipfile.BadZipFile("End of central directory not found")

        (
            _signature,
            disk_number,
            directory_disk,
            entries_on_disk,
            total_entries,
            directory_size,
            directory_offset,
            _comment_length,
        ) = eocd

        uses_zip64 = (
            entries_on_disk == 0xFFFF
            or total_entries == 0xFFFF
            or directory_size == 0xFFFFFFFF
            or directory_offset == 0xFFFFFFFF
        )
        if uses_zip64:
            locator_offset = eocd_offset - _ZIP64_LOCATOR.size
            if locator_offset < 0:
                raise zipfile.BadZipFile("ZIP64 locator not found")
            archive.seek(locator_offset)
            locator = archive.read(_ZIP64_LOCATOR.size)
            if len(locator) != _ZIP64_LOCATOR.size:
                raise zipfile.BadZipFile("Truncated ZIP64 locator")
            locator_signature, zip64_disk, zip64_offset, total_disks = (
                _ZIP64_LOCATOR.unpack(locator)
            )
            if locator_signature != _ZIP64_LOCATOR_SIGNATURE:
                raise zipfile.BadZipFile("ZIP64 locator not found")
            if zip64_disk != 0 or total_disks != 1:
                raise zipfile.BadZipFile("Multi-disk ZIP archives are not supported")

            archive.seek(zip64_offset)
            record = archive.read(_ZIP64_EOCD.size)
            if len(record) != _ZIP64_EOCD.size:
                raise zipfile.BadZipFile("Truncated ZIP64 end record")
            values = _ZIP64_EOCD.unpack(record)
            if values[0] != _ZIP64_EOCD_SIGNATURE:
                raise zipfile.BadZipFile("ZIP64 end record not found")
            disk_number = values[4]
            directory_disk = values[5]
            entries_on_disk = values[6]
            total_entries = values[7]
            directory_size = values[8]
            directory_offset = values[9]

        if disk_number != 0 or directory_disk != 0 or entries_on_disk != total_entries:
            raise zipfile.BadZipFile("Multi-disk ZIP archives are not supported")
        if directory_offset + directory_size > eocd_offset:
            raise zipfile.BadZipFile("Invalid central directory bounds")

        return int(total_entries), int(directory_offset), int(directory_size)


def _validate_zip_directory_cardinality(file_path: str) -> None:
    """Bound ZIP metadata before ZipFile materializes a ZipInfo per member."""
    reported_entries, directory_offset, directory_size = _zip_directory_metadata(
        file_path
    )
    if reported_entries > MAX_ARCHIVE_ENTRIES:
        raise ValueError(
            f"ZIP contains {reported_entries} entries; the maximum is "
            f"{MAX_ARCHIVE_ENTRIES}."
        )
    if directory_size > MAX_CENTRAL_DIRECTORY_BYTES:
        raise ValueError(
            "ZIP central directory exceeds the "
            f"{MAX_CENTRAL_DIRECTORY_BYTES // (1024 * 1024)} MB metadata limit."
        )

    count = 0
    remaining = directory_size
    saw_digital_signature = False
    with open(file_path, "rb") as archive:
        archive.seek(directory_offset)
        while remaining:
            signature = archive.read(4)
            if len(signature) != 4:
                raise zipfile.BadZipFile("Truncated central directory")

            if signature == _CENTRAL_FILE_SIGNATURE:
                rest = archive.read(_CENTRAL_FILE_HEADER.size - 4)
                if len(rest) != _CENTRAL_FILE_HEADER.size - 4:
                    raise zipfile.BadZipFile("Truncated central directory entry")
                fields = _CENTRAL_FILE_HEADER.unpack(signature + rest)
                variable_size = fields[10] + fields[11] + fields[12]
                entry_size = _CENTRAL_FILE_HEADER.size + variable_size
                if entry_size > remaining:
                    raise zipfile.BadZipFile("Invalid central directory entry size")
                archive.seek(variable_size, 1)
                remaining -= entry_size
                count += 1
                if count > MAX_ARCHIVE_ENTRIES:
                    raise ValueError(
                        f"ZIP contains more than {MAX_ARCHIVE_ENTRIES} entries."
                    )
                continue

            if signature == _CENTRAL_DIGITAL_SIGNATURE:
                if saw_digital_signature or count != reported_entries:
                    raise zipfile.BadZipFile(
                        "Invalid central-directory digital signature placement"
                    )
                length_bytes = archive.read(2)
                if len(length_bytes) != 2:
                    raise zipfile.BadZipFile("Truncated central-directory signature")
                signature_size = struct.unpack("<H", length_bytes)[0]
                record_size = 6 + signature_size
                if record_size > remaining:
                    raise zipfile.BadZipFile("Invalid central-directory signature size")
                if record_size != remaining:
                    raise zipfile.BadZipFile(
                        "Central-directory digital signature must be the final record"
                    )
                archive.seek(signature_size, 1)
                remaining -= record_size
                saw_digital_signature = True
                continue

            raise zipfile.BadZipFile("Invalid central directory signature")

    if count != reported_entries:
        raise zipfile.BadZipFile("ZIP member count does not match central directory")


def _is_text_content(header: bytes) -> bool:
    """Check if header bytes appear to be text (no null bytes)."""
    return b"\x00" not in header


def _xml_local_name(tag: object) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1]


def _reject_uploaded_vrt_source(raw_path: str) -> None:
    """Reject SourceFilename values that can escape the staged upload bundle."""
    if not raw_path:
        raise ValueError("VRT <SourceFilename> is empty.")
    if "\x00" in raw_path:
        raise ValueError("VRT <SourceFilename> contains a null byte.")
    if ".." in raw_path:
        logger.warning(
            "VRT body contains path-traversal marker",
            event_type="security",
            reason="vrt_path_traversal",
            source_filename=redact_url_credentials(raw_path)[:200],
        )
        raise ValueError(
            "VRT <SourceFilename> contains a path-traversal marker. "
            "Use relative paths without '..' segments."
        )
    if (
        raw_path.startswith("/")
        or raw_path.startswith("\\\\")
        or _WINDOWS_ABSOLUTE_RE.match(raw_path)
    ):
        logger.warning(
            "VRT body contains absolute source path",
            event_type="security",
            reason="vrt_absolute_path",
            source_filename=redact_url_credentials(raw_path)[:200],
        )
        raise ValueError(
            "VRT <SourceFilename> uses an absolute path. "
            "Uploaded VRTs may only reference relative files in the upload bundle."
        )
    if _URL_SCHEME_RE.match(raw_path) or raw_path.lower().startswith("/vsi"):
        logger.warning(
            "VRT body contains remote or VSI source",
            event_type="security",
            reason="vrt_remote_source",
            source_filename=redact_url_credentials(raw_path)[:200],
        )
        raise ValueError(
            "VRT <SourceFilename> uses a remote or GDAL VSI source. "
            "Uploaded VRTs may only reference relative files in the upload bundle."
        )


def validate_vrt_body(file_path: str) -> None:
    """Validate a user-uploaded .vrt file's XML body.

    IA-P1-03 (Phase 1068): the GDAL VRT driver follows `<SourceFilename>`
    body content as if it were a path/URL. A malicious VRT can declare
    `<SourceFilename>../../etc/hostname</SourceFilename>` and GDAL will
    happily open the resolved path, leaking host content into the raster
    pipeline. Defense-in-depth alongside the staging-dir resolution check
    in `manifest_sources.classify_manifest_source`.

    Rejects:
    - VRTs whose XML body doesn't start with `<VRTDataset`
    - `<SourceFilename>` containing any `..` segment
    - `<SourceFilename>` resolving to an absolute path, URL, or GDAL VSI path.
      Internally generated managed-storage VRTs are produced by the raster/VRT
      pipeline and do not pass through this user-upload validator.

    Raises ValueError with user-friendly message on any violation.
    """
    # codeql[py/path-injection] fix(#1708): file_path is always server-staged — every caller (router upload_file/upload_from_url, tasks_common, presigned probe) builds it under managed staging from a basename-stripped, byte-clamped name. This module sniffs content and never derives a path, so the guarantee is the caller's.
    with open(file_path, "rb") as f:
        body = f.read(VRT_BODY_MAX_BYTES + 1)

    if not body:
        raise ValueError("The uploaded VRT file is empty.")
    if len(body) > VRT_BODY_MAX_BYTES:
        raise ValueError(
            f"Uploaded VRT XML exceeds the {VRT_BODY_MAX_BYTES // (1024 * 1024)} MB limit."
        )

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError(
            "File has .vrt extension but is not a valid VRT XML document "
            f"(missing <VRTDataset root element or invalid XML: {exc})."
        ) from exc

    if _xml_local_name(root.tag) != "VRTDataset":
        raise ValueError(
            "File has .vrt extension but is not a valid VRT XML document "
            "(missing <VRTDataset root element)."
        )

    for elem in root.iter():
        if _xml_local_name(elem.tag) == "SourceFilename":
            _reject_uploaded_vrt_source((elem.text or "").strip())


def validate_parquet_file(file_path: str) -> None:
    """Validate the PAR1 header and footer magic of a .parquet upload.

    Catches wrong-content and truncated files before pyarrow ever opens
    them. Raises ValueError with a user-friendly message.
    """
    path = Path(file_path)
    # 12 bytes = header magic + 4-byte footer length + footer magic.
    # codeql[py/path-injection] fix(#1708): file_path is always server-staged — every caller (router upload_file/upload_from_url, tasks_common, presigned probe) builds it under managed staging from a basename-stripped, byte-clamped name. This module sniffs content and never derives a path, so the guarantee is the caller's.
    if path.stat().st_size < 12:
        raise ValueError("The uploaded file is not a valid Parquet file.")
    # codeql[py/path-injection] fix(#1708): file_path is always server-staged — every caller (router upload_file/upload_from_url, tasks_common, presigned probe) builds it under managed staging from a basename-stripped, byte-clamped name. This module sniffs content and never derives a path, so the guarantee is the caller's.
    with path.open("rb") as f:
        head = f.read(4)
        f.seek(-4, 2)
        tail = f.read(4)
    if head != _PARQUET_MAGIC or tail != _PARQUET_MAGIC:
        raise ValueError(
            "File has .parquet extension but is not a valid Parquet file "
            "(missing PAR1 magic bytes — the file may be corrupt or truncated)."
        )


def validate_flatgeobuf_file(file_path: str) -> None:
    """Validate the 8-byte magic header of a ``.fgb`` upload.

    puremagic has no FlatGeobuf signature (it raises ``PureError`` on one), so
    without this check every ``.fgb`` would fall through the unknown-extension
    branch and reach GDAL unverified. Raises ValueError with a user-friendly
    message.
    """
    # codeql[py/path-injection] fix(#1708): file_path is always server-staged — every caller (router upload_file/upload_from_url, tasks_common, presigned probe) builds it under managed staging from a basename-stripped, byte-clamped name. This module sniffs content and never derives a path, so the guarantee is the caller's.
    with open(file_path, "rb") as f:
        header = f.read(_FGB_MAGIC_SIZE)
    if (
        len(header) < _FGB_MAGIC_SIZE
        or header[0:3] != _FGB_MAGIC_WORD
        or header[4:7] != _FGB_MAGIC_WORD
    ):
        raise ValueError(
            "File has .fgb extension but is not a valid FlatGeobuf file "
            "(missing the FlatGeobuf magic bytes)."
        )


def _is_xml_like(header: bytes) -> bool:
    """True when the header opens an XML/KML document.

    A structural check rather than a magic signature: KML written without an
    ``<?xml`` prologue is valid and common, and puremagic detects nothing for
    it.

    Encoding-aware because LIBKML reads UTF-16 KML (verified against the
    worker's GDAL), and a UTF-16 document's interleaved NUL bytes make the
    plain "no NULs" text check call it binary. The BOM decides the encoding
    when there is one; XML 1.0 Appendix F's byte patterns decide when there
    is not.
    """
    for bom, encoding in _XML_BOMS:
        if header.startswith(bom):
            decoded = header[len(bom) :].decode(encoding, "ignore")
            return decoded.lstrip().startswith("<")
    if header.startswith(_UNMARKED_WIDE_XML_PREFIXES):
        return True
    if not _is_text_content(header):
        return False
    return header.lstrip().startswith(b"<")


def validate_file_content(file_path: str, filename: str) -> None:
    """Verify file content matches declared extension via magic bytes.

    Raises ValueError with user-friendly message on mismatch or empty file.
    """
    suffix = Path(filename).suffix.lower()

    # IA-P1-03: .vrt gets its own XML+traversal check (magic bytes are
    # XML which puremagic doesn't reliably distinguish from generic text).
    if suffix == ".vrt":
        validate_vrt_body(file_path)
        return

    # Parquet has a fixed header+footer magic; check both directly instead
    # of relying on puremagic's header-only detection.
    if suffix == ".parquet":
        validate_parquet_file(file_path)
        return

    # FlatGeobuf has a fixed 8-byte header magic that puremagic does not know.
    if suffix == ".fgb":
        validate_flatgeobuf_file(file_path)
        return

    # codeql[py/path-injection] fix(#1708): file_path is always server-staged — every caller (router upload_file/upload_from_url, tasks_common, presigned probe) builds it under managed staging from a basename-stripped, byte-clamped name. This module sniffs content and never derives a path, so the guarantee is the caller's.
    with open(file_path, "rb") as f:
        header = f.read(HEADER_READ_SIZE)

    if len(header) == 0:
        raise ValueError("The uploaded file is empty.")

    # Skip magic-byte validation for extensions without known content rules
    if suffix not in EXTENSION_CONTENT_MAP:
        return

    try:
        detected = puremagic.from_string(header, filename=filename)
    except puremagic.PureError:
        detected = ""

    allowed = EXTENSION_CONTENT_MAP.get(suffix, set())

    if detected in allowed:
        return

    # Text-based formats may not be detected by puremagic.
    # Allow if content appears to be text (no null bytes).
    if suffix in (".geojson", ".json", ".csv") and _is_text_content(header):
        return

    # KML gets the narrower text rule: it must at least open a tag, so a plain
    # text file renamed to .kml is still refused here rather than by GDAL.
    if suffix == ".kml" and _is_xml_like(header):
        return

    logger.warning(
        "Upload content mismatch",
        event_type="security",
        reason="content_mismatch",
        filename=filename,
        declared_extension=suffix,
        detected_type=detected,
    )
    raise ValueError(
        f"File content detected as '{detected or 'unknown'}' "
        f"but extension is '{suffix}'. "
        f"Please upload with the correct extension."
    )


def validate_zip_safety(file_path: str) -> None:
    """Check ZIP archive for bomb indicators without extracting.

    Raises ValueError if:
    - File is not a valid ZIP
    - Any entry has compression ratio > MAX_COMPRESSION_RATIO
    - Any entry is a GDAL driver-metadata document (see
      DRIVER_METADATA_EXTENSIONS)
    - Any entry is a nested archive
    - Total decompressed size > MAX_DECOMPRESSED_BYTES
    """
    try:
        _validate_zip_directory_cardinality(file_path)
        with zipfile.ZipFile(file_path, "r") as zf:
            total_uncompressed = 0

            for info in zf.infolist():
                total_uncompressed += info.file_size

                # Per-entry compression ratio check
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_COMPRESSION_RATIO:
                        logger.warning(
                            "ZIP bomb indicator: high compression ratio",
                            event_type="security",
                            reason="zip_bomb_indicator",
                            filename=Path(file_path).name,
                            entry=info.filename,
                            ratio=f"{ratio:.0f}:1",
                        )
                        raise ValueError(
                            f"ZIP entry '{info.filename}' has suspicious compression "
                            f"ratio ({ratio:.0f}:1). Maximum allowed is "
                            f"{MAX_COMPRESSION_RATIO}:1."
                        )

                entry_ext = Path(info.filename).suffix.lower()

                # Driver-metadata check (see DRIVER_METADATA_EXTENSIONS)
                if entry_ext in DRIVER_METADATA_EXTENSIONS:
                    logger.warning(
                        "ZIP contains a GDAL driver-metadata member",
                        event_type="security",
                        reason="driver_metadata_member",
                        filename=Path(file_path).name,
                        entry=info.filename,
                    )
                    raise ValueError(
                        f"ZIP entry '{info.filename}' is a GDAL VRT. A VRT "
                        "describes where to read data from rather than "
                        "carrying any, so it is not accepted inside an "
                        "upload. Upload the data files themselves."
                    )

                # Nested archive check
                if entry_ext in ARCHIVE_EXTENSIONS:
                    logger.warning(
                        "ZIP contains nested archive",
                        event_type="security",
                        reason="nested_archive",
                        filename=Path(file_path).name,
                        nested_entry=info.filename,
                    )
                    raise ValueError(
                        f"ZIP contains nested archive '{info.filename}'. "
                        f"Nested archives are not supported for geospatial uploads."
                    )

            # Total decompressed size check
            if total_uncompressed > MAX_DECOMPRESSED_BYTES:
                size_gb = total_uncompressed / (1024**3)
                limit_gb = MAX_DECOMPRESSED_BYTES // (1024**3)
                logger.warning(
                    "ZIP bomb indicator: excessive decompressed size",
                    event_type="security",
                    reason="zip_bomb_indicator",
                    filename=Path(file_path).name,
                    decompressed_gb=f"{size_gb:.1f}",
                )
                raise ValueError(
                    f"ZIP total decompressed size ({size_gb:.1f} GB) exceeds "
                    f"the {limit_gb} GB limit."
                )

    except zipfile.BadZipFile:
        raise ValueError("File is not a valid ZIP container.")


def validate_archive_safety(file_path: str, filename: str) -> None:
    """Apply ZIP safety checks to every accepted ZIP-container source format."""
    if Path(filename).suffix.lower() in ZIP_CONTAINER_EXTENSIONS:
        validate_zip_safety(file_path)


def validate_file_size(file_path: str, max_size_bytes: int) -> None:
    """Verify file does not exceed configured size limit.

    Raises ValueError with user-friendly message if exceeded.
    """
    file_size = Path(file_path).stat().st_size
    if file_size > max_size_bytes:
        size_mb = file_size / (1024 * 1024)
        limit_mb = max_size_bytes / (1024 * 1024)
        raise ValueError(
            f"File size ({size_mb:.1f} MB) exceeds the maximum allowed ({limit_mb:.0f} MB)."
        )
