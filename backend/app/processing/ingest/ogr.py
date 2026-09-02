"""Async subprocess wrappers for GDAL CLI tools (ogr2ogr, ogrinfo)."""

import asyncio
import json
import os
import re
from collections.abc import Callable
from typing import TypedDict

import structlog

from app.core.config import settings
from app.core.crs_uri import parse_crs_uri
from app.core.runtime.staging import (
    GDAL_HEADER_FILE_REDIRECT_ENV,
    ensure_staging_ready,
    gdal_header_dir,
)
from app.platform.service_items import materialise_oapif_items
from app.platform.service_endpoints import assert_endpoints_stay_on_origin
from app.core.service_tokens import (
    BEARER_SCHEME,
    HEADER_LINE_SEPARATOR,
    HEADER_LINE_VALUE_CHARSET,
    HEADER_NAME_CHARSET,
    HEADER_TOKEN_CHARSET,
    HEADER_TOKEN_MIN_LENGTH,
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
    credential_header_line,
)
from app.core.url_redaction import redact_url_credentials


# SEED-04 (Phase 1054): compiled once at module scope to avoid repeated re.compile().
# Matches GDAL driver-list lines like "  -> 'FITS' (read-only)" or " -> 'PCIDSK' (rw+v)".
# The trailing mode group (...) is optional — some GDAL builds emit bare driver names
# without a mode suffix, so the regex accepts " -> 'NAME'" with optional "(...)" after.
_OGR_DRIVER_LIST_LINE_RE = re.compile(r"^\s*->\s*'[^']+'\s*(\([^)]*\))?\s*$")

# When ogr2ogr/ogrinfo can find no driver willing to open the source, they
# print this one line followed by GDAL's full driver enumeration (100+
# lines) — the raw text a demo visitor saw verbatim in the job UI for an
# invalid march.gpkg upload. Anchored tightly to that exact phrase so no
# other failure class (bad SRS, permission denied, disk full, ...) matches.
_OGR_UNABLE_TO_OPEN_RE = re.compile(
    r"Unable to open datasource `[^']*' with the following drivers\."
)

# A second shape of the same user-facing problem: a driver DOES claim the
# source (by extension/header — e.g. GPKG is SQLite) but the content
# underneath is corrupt, which surfaces as SQLite's own error instead of a
# GDAL driver-enumeration failure. GDAL prints a "bad application_id=0x..."
# warning above this for GPKG specifically, but the "file is not a
# database" line is the one that's common to the class and safe to anchor
# on — it's SQLite's own open-failure text, not phrasing GDAL reuses for
# anything else. This fires when the SQLite header itself doesn't parse
# (e.g. the magic string is present but the page-size/header fields are
# garbage).
_SQLITE_NOT_A_DATABASE_RE = re.compile(r"file is not a database")

# fix(codex review, #1640): a THIRD shape of the same problem — the SQLite
# header parses fine (magic, page size, application_id all valid) but an
# interior b-tree page is corrupt, which SQLite reports as "database disk
# image is malformed" instead of "file is not a database". Empirically
# reproduced: a real GPKG (via ogr2ogr) with the first 100 header bytes
# untouched and ~1KB flipped inside a near-full leaf page of the sqlite
# schema b-tree (found via `dbstat`) makes `sqlite3` itself report exactly
# this string, and both ogrinfo and ogr2ogr surface it verbatim in stderr —
# ogrinfo's failure text does NOT also contain "with the following drivers"
# or "file is not a database", so without this pattern it fell through to
# the raw stderr (and the leaked staging path) unmodified.
_SQLITE_DISK_IMAGE_MALFORMED_RE = re.compile(r"database disk image is malformed")


def _is_unopenable_source_stderr(stderr_text: str) -> bool:
    """True when ``stderr_text`` matches a known "can't open this source" shape.

    All three patterns below mean the same thing to the person who uploaded
    the file — GDAL could not read it as a spatial dataset — so all three
    map to the same friendly message; see ``_friendly_open_failure_message``.
    """
    return bool(
        _OGR_UNABLE_TO_OPEN_RE.search(stderr_text)
        or _SQLITE_NOT_A_DATABASE_RE.search(stderr_text)
        or _SQLITE_DISK_IMAGE_MALFORMED_RE.search(stderr_text)
    )


# Human-readable label per uploaded extension, used only to phrase the
# friendly "could not open" message below. Unknown/missing extensions fall
# back to a generic "spatial data" phrasing.
_VECTOR_FORMAT_LABELS: dict[str, str] = {
    ".gpkg": "GeoPackage (.gpkg)",
    ".shp": "Shapefile (.shp)",
    ".zip": "zipped Shapefile or File Geodatabase (.zip)",
    ".geojson": "GeoJSON (.geojson)",
    ".json": "GeoJSON (.json)",
    ".csv": "CSV (.csv)",
    ".kml": "KML (.kml)",
    ".kmz": "KMZ (.kmz)",
    ".fgb": "FlatGeobuf (.fgb)",
    ".gml": "GML (.gml)",
    ".gdb": "File Geodatabase (.gdb)",
}


def _friendly_open_failure_message(original_filename: "str | None") -> str:
    """User-facing text for an ogr2ogr "unable to open datasource" failure.

    Deliberately built from ``original_filename`` alone — never from the
    staging path or the raw stderr — so the message can never leak the
    `/app/staging/<uuid>_...` path GDAL echoes back on this failure class.
    """
    name = os.path.basename(original_filename) if original_filename else None
    suffix = os.path.splitext(name)[1].lower() if name else ""
    format_label = _VECTOR_FORMAT_LABELS.get(suffix, "spatial data")
    if name:
        return (
            f"Could not open '{name}' as a spatial dataset — the file may be "
            f"corrupt, incomplete, or not a valid {format_label} file."
        )
    return (
        "Could not open the uploaded file as a spatial dataset — it may be "
        "corrupt, incomplete, or not a valid spatial data file."
    )


# fix(#1746): the worker's own refusals, as constants rather than composed
# strings. Each one becomes `IngestJob.error_message`, a log record, a
# notification reason and the exception the queue records, so none of them may
# name any part of the credential being judged. No brace in any of them, so
# none can grow an interpolation later.
HEADER_LINE_SHAPE_POLICY = (
    "SEC-FU-04: the service credential did not arrive as one header line "
    "(a header name, a colon and a space, then a value). Nothing was sent."
)

HEADER_LINE_NAME_POLICY = (
    "SEC-FU-04: the service credential named a header this build will not "
    "write. A header name may use only letters, digits and the characters "
    "! # $ % & ' * + - . ^ _ ` | ~ ."
)

HEADER_LINE_VALUE_POLICY = (
    "SEC-FU-04: the service credential's value contains a character that "
    "cannot be written into an HTTP header. Only printable ASCII is "
    "permitted, so that no line break can smuggle a second header through "
    "libcurl."
)


def _legacy_bearer_line(token: str, service_format: str) -> str:
    """The line a pre-#1770 queued job's bare bearer token would have become.

    Composed by ``build_credential_header``, not here: this module writes the
    header file and validates what it is given, and the single-producer rule
    (``tests/test_credential_producer_structural.py``) exists so no second
    place in the tree can grow a prefix of its own. The builder applies the
    same base64url charset and length floor the previous version enforced on
    this exact value, so a token it refuses was never dispatchable anyway and
    the answer is the shape policy rather than a bearer-specific message: from
    here the two cases are indistinguishable, and the value is not named.
    """
    try:
        pair = build_credential_header(
            ServiceCredential(
                method=CredentialMethod.BEARER,
                service_format=service_format,
                token=token,
            )
        )
    except ValueError:
        raise ValueError(HEADER_LINE_SHAPE_POLICY) from None
    if pair is None:
        # A service format that carries no header at all. The caller gates on
        # the two that do, so this is unreachable from the one call site and
        # exists because a silent empty line would be worse than a refusal.
        raise ValueError(HEADER_LINE_SHAPE_POLICY)
    return credential_header_line(pair)


def _sanitize_authorization_token(
    header_line: "str | None", *, service_format: str
) -> "str | None":
    """SEC-FU-04: pin the credential header line to the shared policy.

    What crosses from the door to this worker is one finished header line
    (plan D9), not a bare token, so this judges a LINE: printable ASCII, no CR
    or LF, exactly one ``": "`` separator, and a name that passes
    ``header_name_rejection_reason``. A character outside that shape could let
    an attacker inject additional HTTP headers through the
    GDAL_HTTP_HEADER_FILE to libcurl pipeline, so this is a security boundary
    rather than a formatting preference.

    fix(#1277 review round 6): the rules come from ``app.core.service_tokens``,
    which every door applies as well — a caller learns immediately instead of
    after their single-use credential has been spent. This check stays
    regardless: the guarantee is about what reaches libcurl, and it must not
    come to rest on a validator running in another process.

    The bearer branch keeps the base64url charset and the length floor, so
    nothing about today's bearer guarantee weakens. It also keeps NAMING the
    offending character, because a bearer token is the one credential shape
    whose every character is already constrained to a set that carries no
    secret structure, and a worker-side ValueError is read by whoever is
    debugging a failed job.

    fix(#1746): every OTHER branch is policy-only. This exception becomes
    ``IngestJob.error_message``, a log record, a notification reason and the
    re-raise the queue records — ``scrub_secret_from_exception`` mutates it in
    place precisely so all four see the same text. Under basic authentication
    the value being judged is an encoded username and password, and naming a
    character of a password across all four sinks is not a debugging aid worth
    having.

    fix(#1746 B2b review r3): a value with no separator is the PRE-#1770 wire
    format, and it has to keep working. A worker that starts while
    authenticated WFS or OGC API jobs are already queued reads a bare bearer
    token out of ``procrastinate_jobs.args``, or out of the credential store
    behind a reference the old door stashed. Refusing it would fail every one
    of those deterministically at the next deploy or restart, which is worse
    than the skew #1689 accepted at this door: that one degraded to a 401 the
    operator could retry, and this would spend the single-use credential and
    fail before ogr2ogr started. So a bare value that satisfies the charset the
    previous version enforced is composed into the line it would have produced,
    through the same builder every other caller uses rather than by a second
    prefix in this module. Anything that is neither a valid line nor a valid
    bare token still raises the shape policy.

    ``service_format`` selects the builder's allowlist branch. Both header-auth
    formats compose an identical bearer line, so it changes no output; passing
    the caller's real value rather than a constant is what keeps the builder
    the authority on which formats may carry a header at all.

    Returns the line the file should hold, raises ValueError with a
    SEC-FU-04-prefixed message otherwise. None passes through.
    """
    if header_line is None:
        return None
    name, separator, value = header_line.partition(HEADER_LINE_SEPARATOR)
    if not separator:
        return _legacy_bearer_line(header_line, service_format)
    if not value or HEADER_LINE_SEPARATOR in value:
        raise ValueError(HEADER_LINE_SHAPE_POLICY)
    if not name or any(character not in HEADER_NAME_CHARSET for character in name):
        # The field-name GRAMMAR, and deliberately not the door's denylist of
        # reserved names: that one refuses a name a CALLER chose, and the
        # builder's own output for bearer and basic is `Authorization`, which
        # the denylist exists to keep a caller from claiming. Applying it here
        # would refuse every line this codebase composes.
        raise ValueError(HEADER_LINE_NAME_POLICY)
    if any(character not in HEADER_LINE_VALUE_CHARSET for character in value):
        raise ValueError(HEADER_LINE_VALUE_POLICY)
    if not value.startswith(BEARER_SCHEME):
        return header_line

    token = value[len(BEARER_SCHEME) :]
    if len(token) < HEADER_TOKEN_MIN_LENGTH:
        raise ValueError(
            "SEC-FU-04: Authorization token is empty or implausibly short "
            f"(minimum {HEADER_TOKEN_MIN_LENGTH} characters required to "
            "prevent single-char attack payloads)."
        )
    bad = [c for c in token if c not in HEADER_TOKEN_CHARSET]
    if bad:
        sample = bad[0]
        raise ValueError(
            f"SEC-FU-04: Authorization token contains non-base64url character "
            f"(first offender: {sample!r}); only [A-Za-z0-9._\\-=] are permitted "
            "to prevent CRLF header smuggling via GDAL_HTTP_HEADERS env var."
        )
    return header_line


def _strip_ogr_driver_list(stderr_text: str) -> str:
    """Remove GDAL driver-list lines from ogr2ogr stderr output.

    ogr2ogr emits a 150+ line enumeration of supported drivers before printing
    the actual error when it cannot open a source. These lines match the pattern
    "  -> 'DRIVER_NAME' (modes)" and are noise for the caller. This helper
    strips them so IngestionError messages contain only the actionable line(s).

    Blank lines that result from stripping (i.e., runs of consecutive blank
    lines) are collapsed to a single blank line. The result is stripped of
    leading/trailing whitespace.

    Safety: the regex only matches lines with the specific "-> 'NAME' (...)"
    shape. If GDAL changes its driver-list format in a future version, the worst
    case is that nothing gets stripped — never that real error content is removed.
    """
    if not stderr_text:
        return stderr_text

    lines = stderr_text.splitlines()
    kept: list[str] = []
    for line in lines:
        if _OGR_DRIVER_LIST_LINE_RE.match(line):
            continue
        kept.append(line)

    # Collapse runs of blank lines down to at most one.
    collapsed: list[str] = []
    prev_blank = False
    for line in kept:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank

    return "\n".join(collapsed).strip()


class OgrinfoResult(TypedDict, total=False):
    srid: int | None
    geometry_type: str | None
    layer_name: str
    feature_count: int | None
    columns: list[dict[str, str]]
    sample_rows: list[dict]
    all_layers: list[dict] | None


class IngestionError(Exception):
    """Raised when an ingestion subprocess fails."""


class IngestBudgetExceededError(IngestionError):
    """Raised when a source exceeds an ingest resource ceiling (fix(#948)).

    A subclass so the preview route can surface THIS message verbatim without
    widening the generic ``IngestionError`` handler, which also carries GDAL
    subprocess output. The text is server-authored and names the limit, the
    observed value, and what to do about it — telling a user only that their
    file "may be malformed or unsupported" when it is merely too large leaves
    them with nothing to act on. Raised from the parquet path today.
    """


def validate_layer_name_argv(layer_name: str) -> None:
    """Reject option-like layer names before they reach a GDAL argv.

    fix(#823): layer names are appended to ogrinfo/ogr2ogr argv as positional
    tokens. A value starting with '-' could be parsed by GDAL as a command-line
    flag instead of a layer name (argument-injection hygiene; the argv is
    exec'd directly, never a shell). Called by every spawner in this module
    that forwards a layer name.
    """
    if layer_name.startswith("-"):
        raise IngestionError(
            f"Invalid layer name {layer_name!r}: must not start with '-'"
        )


# ---------------------------------------------------------------------------
# Subprocess timeouts (R-5, R-9)
# ---------------------------------------------------------------------------
# Wall-clock limits protect the Procrastinate worker from hanging on a bad
# file or a slow/hung upstream service. Tune via settings if your datasets
# are routinely large.

OGRINFO_TIMEOUT_SECONDS = 300  # 5 min — metadata probe, should be fast
OGR2OGR_FILE_TIMEOUT_SECONDS = 3600  # 1 hour — large files legitimately take a while
OGR2OGR_SERVICE_TIMEOUT_SECONDS = 1800  # 30 min — existing value, now a named constant


async def _kill_and_reap_subprocess(proc: asyncio.subprocess.Process) -> None:
    """Best-effort kill + reap for a subprocess whose ``communicate()`` ended
    abnormally. Shared by both ``_communicate_with_timeout`` branches below
    so the kill/terminate/wait sequence has one implementation.
    """
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    except (
        Exception
    ):  # broad: kill() can fail with permission/state errors; fall back to terminate()
        try:
            proc.terminate()
        except Exception:  # broad: terminate() best-effort cleanup; give up if subprocess is already gone
            pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, ProcessLookupError):
        pass


async def _communicate_with_timeout(
    proc: asyncio.subprocess.Process,
    timeout: float,
    *,
    tool_name: str,
) -> tuple[bytes, bytes]:
    """Run ``proc.communicate()`` with a timeout + graceful kill fallback.

    On timeout, attempts ``proc.kill()``, then ``proc.terminate()``, then
    gives up — in all cases raises IngestionError so the caller surfaces a
    meaningful error instead of hanging the worker.

    On cancellation — a client disconnect cancels the request task, or
    Procrastinate cancels a worker job during graceful shutdown —
    ``asyncio.wait_for`` re-raises ``CancelledError`` from the outer task
    without touching the child process. Without the branch below, the
    ogr2ogr child is left running with nothing left to await it: a caller
    that then deletes its output directory (export cleanup) races a process
    that may still hold the file open. Runs the same kill/terminate/wait
    sequence as the timeout branch, then re-raises so cancellation still
    propagates.
    """
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill_and_reap_subprocess(proc)
        raise IngestionError(
            f"{tool_name} timed out after {int(timeout)}s — the file or upstream service is too slow"
        )
    except asyncio.CancelledError:
        await _kill_and_reap_subprocess(proc)
        raise


# ---------------------------------------------------------------------------
# Geometry column auto-detection patterns
# ---------------------------------------------------------------------------

LAT_PATTERNS = {"lat", "latitude", "y", "lat_dd", "ycoord"}
LNG_PATTERNS = {"lon", "lng", "long", "longitude", "x", "lon_dd", "xcoord"}
WKT_PATTERNS = {"wkt", "geom", "geometry", "the_geom", "shape"}

# Column names that collide with GeoLens-internal PostGIS columns created
# during ingestion. If a source file has an attribute with any of these
# names, the ingest pipeline auto-renames it to `src_<name>` before the
# remaining post-ingest steps run. See metadata_geometry.py
# rename_reserved_columns.
RESERVED_COLUMN_NAMES: frozenset[str] = frozenset(
    {"gid", "geom", "geometry", "geom_4326", "fid", "ogc_fid"}
)


def detect_geometry_columns(columns: list[dict]) -> dict:
    """Detect potential geometry columns from column metadata.

    Pattern-matches column names (case-insensitive) against known
    lat/lng and WKT naming conventions.

    Returns dict with keys: x_column, y_column, wkt_column (original case).
    """
    col_names = {c["name"].lower(): c["name"] for c in columns}

    x_col = next((col_names[n] for n in LNG_PATTERNS if n in col_names), None)
    y_col = next((col_names[n] for n in LAT_PATTERNS if n in col_names), None)
    wkt_col = next((col_names[n] for n in WKT_PATTERNS if n in col_names), None)

    return {"x_column": x_col, "y_column": y_col, "wkt_column": wkt_col}


def build_pg_conn_str() -> str:
    """Build a PG connection string for ogr2ogr from settings."""
    return settings.ogr_connection_string


def _tenant_subprocess_env(
    schema: str,
    *,
    writer: bool,
    base_env: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Bind a libpq/GDAL connection to the active tenant's SET-only role.

    ogr2ogr opens its own PostgreSQL connection, outside SQLAlchemy's statement
    hooks. ``PGOPTIONS`` is therefore the equivalent connection-time binder.
    In single-tenant mode this returns ``base_env`` unchanged so the legacy
    subprocess environment remains byte-for-byte compatible.
    """
    from app.core.db.tenant_schema import (
        tenant_data_schema,
        tenant_reader_role,
        tenant_writer_role,
    )
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return base_env

    tenant_id = current_tenant_var.get()
    if tenant_id is None:
        raise RuntimeError("ogr2ogr tenant access requires an active tenant context")

    expected_schema = tenant_data_schema(tenant_id)
    if schema != expected_schema:
        raise RuntimeError(
            "ogr2ogr target schema does not match the active tenant: "
            f"expected {expected_schema!r}, got {schema!r}"
        )

    role = tenant_writer_role(tenant_id) if writer else tenant_reader_role(tenant_id)
    env = dict(os.environ if base_env is None else base_env)
    existing_options = env.get("PGOPTIONS", "").strip()
    role_option = f"-c role={role}"
    env["PGOPTIONS"] = (
        f"{existing_options} {role_option}" if existing_options else role_option
    )
    return env


def _tenant_writer_subprocess_env(
    schema: str,
    *,
    base_env: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Bind an independent ogr2ogr connection to a tenant writer role."""
    return _tenant_subprocess_env(schema, writer=True, base_env=base_env)


def _tenant_reader_subprocess_env(
    schema: str,
    *,
    base_env: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Bind an independent ogr2ogr connection to a tenant reader role."""
    return _tenant_subprocess_env(schema, writer=False, base_env=base_env)


def _resolve_source_path(file_path: str) -> str:
    """Wrap file path with /vsizip/ if it is a zip file."""
    if file_path.endswith(".zip"):
        return f"/vsizip/{file_path}"
    return file_path


def _is_parquet(file_path: str) -> bool:
    """The Debian GDAL build has no Arrow/Parquet driver — .parquet files
    are handled by the pure-pyarrow path in ingest/parquet.py instead of
    the GDAL subprocesses in this module."""
    return file_path.lower().endswith(".parquet")


def extract_srid_from_json(coord_system: dict) -> int | None:
    """Extract EPSG SRID from ogrinfo JSON coordinateSystem field."""
    if not coord_system:
        return None

    # Try projjson.id.code first
    projjson = coord_system.get("projjson")
    if projjson:
        id_obj = projjson.get("id")
        if id_obj and id_obj.get("authority") == "EPSG":
            code = id_obj.get("code")
            if code is not None:
                return int(code)

    # Fall back to parsing WKT for AUTHORITY["EPSG","XXXX"]
    wkt = coord_system.get("wkt")
    if wkt:
        match = re.search(r'AUTHORITY\["EPSG","(\d+)"\]', wkt)
        if match:
            return int(match.group(1))

    # Phase 1057 CRS-06 (D-07): Third fallback — parse URI/URN-form CRS from the
    # `name` field.  ogrinfo populates coordinateSystem.name with the source CRS
    # reference (URI or URN) when projjson/WKT lack an EPSG authority.  This covers:
    #   - OGC API Features sources declaring storageCrs as a URI/URN (e.g. pygeoapi)
    #   - WFS 2.0 sources with DefaultCRS as a URN (e.g. urn:ogc:def:crs:EPSG::4326)
    # Unrecognised URIs return None, preserving the null-CRS fallthrough (D-07).
    # This block fires ONLY when projjson + WKT both returned None — authoritative
    # EPSG declarations in those fields always win (D-07 ordering guarantee).
    name = coord_system.get("name")
    if name:
        srid = parse_crs_uri(name)
        if srid is not None:
            return srid

    return None


def _extract_common_layer_metadata(
    data: dict, layer_name: str | None
) -> tuple[dict, dict]:
    """Extract the target layer and common metadata from parsed ogrinfo JSON.

    Returns ``(target_layer, metadata_dict)`` where metadata_dict carries
    the fields common to both ``run_ogrinfo`` and ``run_ogrinfo_preview``:
    srid, geometry_type, layer_name, feature_count, columns, all_layers.

    ``columns`` is a list of ``{"name": str, "type": str}`` mirroring the
    field definitions from the target layer. Populating it in the shared
    helper (rather than only in ``run_ogrinfo_preview``) lets shapefile
    ingest reuse the DBF-collision detector without spawning a second
    ogrinfo subprocess (PERF-1).

    Raises KeyError if the JSON has no ``layers`` entry so callers can
    fall through to their fallback path. KISS-12.
    """
    layers = data.get("layers", [])
    if not layers:
        raise KeyError("no layers in ogrinfo JSON output")

    target_layer = layers[0]
    if layer_name:
        for lyr in layers:
            if lyr.get("name") == layer_name:
                target_layer = lyr
                break

    geom_fields = target_layer.get("geometryFields", [])
    geometry_type: str | None = None
    coord_system = target_layer.get("coordinateSystem", {})
    if geom_fields:
        geometry_type = geom_fields[0].get("type")
        # coordinateSystem may be nested inside geometryFields
        if not coord_system:
            coord_system = geom_fields[0].get("coordinateSystem", {})
    srid = extract_srid_from_json(coord_system or {})

    columns = [
        {"name": f.get("name", ""), "type": f.get("type", "")}
        for f in target_layer.get("fields", [])
    ]

    # GPKG-01 Phase 1058: always expose all_layers when source has >1 layers,
    # regardless of whether a specific layer_name was requested.  Callers that
    # do not need the full list can ignore the key; callers that show layer-select
    # UX (ReuploadDialog) need the list even after a targeted preview.
    all_layers = None
    if len(layers) > 1:
        all_layers = [
            {
                "name": lyr.get("name", ""),
                "feature_count": lyr.get("featureCount", 0),
                "field_count": len(lyr.get("fields", [])),
            }
            for lyr in layers
        ]

    return target_layer, {
        "srid": srid,
        "geometry_type": geometry_type,
        "layer_name": target_layer.get("name", ""),
        "feature_count": target_layer.get("featureCount"),
        "columns": columns,
        "all_layers": all_layers,
    }


def _parse_text_ogrinfo(output: str) -> dict:
    """Parse text output from ogrinfo -so (fallback for GDAL < 3.7)."""
    srid = None
    geometry_type = None
    layer_name = ""
    feature_count = None

    for line in output.splitlines():
        line = line.strip()

        if line.startswith("Layer name:"):
            layer_name = line.split(":", 1)[1].strip()
        elif line.startswith("Geometry:"):
            geometry_type = line.split(":", 1)[1].strip()
        elif line.startswith("Feature Count:"):
            try:
                feature_count = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass

        # Look for EPSG code in the output
        epsg_match = re.search(r"EPSG:(\d+)", line)
        if epsg_match and srid is None:
            srid = int(epsg_match.group(1))

    return {
        "srid": srid,
        "geometry_type": geometry_type,
        "layer_name": layer_name,
        "feature_count": feature_count,
    }


async def run_ogrinfo(
    file_path: str,
    layer_name: str | None = None,
    *,
    original_filename: str | None = None,
) -> OgrinfoResult:
    """Run ogrinfo to detect CRS and layer metadata.

    Returns dict with keys: srid, geometry_type, layer_name, feature_count, all_layers.
    When multiple layers exist and no layer_name is specified, all_layers lists them.
    Tries JSON output first (GDAL 3.7+), falls back to text parsing.

    Args:
        original_filename: The user-visible upload filename (not the staging
            path in ``file_path``), used only to phrase the friendly message
            on an "unable to open" failure. Optional — callers without it
            (e.g. the preview endpoint) still get a generic-but-safe message.
    """
    if layer_name:
        validate_layer_name_argv(layer_name)
    if _is_parquet(file_path):
        from app.processing.ingest.parquet import parquet_info

        return await parquet_info(file_path)

    source = _resolve_source_path(file_path)

    # Try JSON output first (GDAL 3.7+)
    cmd = ["ogrinfo", "-so", "-json", source]
    # CSV driver types all fields as String by default; auto-detect so
    # numeric columns appear as Real/Integer in the preview schema.
    if file_path.lower().endswith(".csv"):
        cmd[3:3] = ["-oo", "AUTODETECT_TYPE=YES"]
    if layer_name:
        cmd.append(layer_name)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _communicate_with_timeout(
        proc, OGRINFO_TIMEOUT_SECONDS, tool_name="ogrinfo"
    )

    if proc.returncode == 0:
        try:
            data = json.loads(stdout.decode())
            _, metadata = _extract_common_layer_metadata(data, layer_name)
            return metadata
        except KeyError:
            # No layers in JSON output but command succeeded — return empty shell.
            return {
                "srid": None,
                "geometry_type": None,
                "layer_name": "",
                "feature_count": None,
                "columns": [],
                "all_layers": None,
            }
        except json.JSONDecodeError:
            pass  # Fall through to text fallback

    # Fallback: text output (GDAL < 3.7 or -json flag failed)
    cmd_text = ["ogrinfo", "-so", source]
    if layer_name:
        cmd_text.append(layer_name)
    proc = await asyncio.create_subprocess_exec(
        *cmd_text,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _communicate_with_timeout(
        proc, OGRINFO_TIMEOUT_SECONDS, tool_name="ogrinfo"
    )

    if proc.returncode != 0:
        stderr_text = stderr.decode().strip()
        if _is_unopenable_source_stderr(stderr_text):
            # The full stderr (driver enumeration, or SQLite's own corrupt-
            # database diagnostics) is diagnostic gold for us and unreadable
            # noise — plus a leaked staging path — for the job UI. Log the
            # raw text at error level here, the one place that still sees
            # it, then raise a short, human-readable IngestionError.
            structlog.get_logger().error(
                "ogrinfo could not open source file",
                exit_code=proc.returncode,
                stderr=stderr_text,
                original_filename=original_filename,
            )
            raise IngestionError(_friendly_open_failure_message(original_filename))
        raise IngestionError(f"ogrinfo failed (exit {proc.returncode}): {stderr_text}")

    result = _parse_text_ogrinfo(stdout.decode())
    # Text-fallback parse doesn't extract field definitions, so the DBF
    # collision detector will still have to fall back to ogrinfo_preview
    # on GDAL < 3.7. Keep the key present so callers can rely on it.
    result["columns"] = []
    result["all_layers"] = None
    return result


async def run_ogrinfo_preview(
    file_path: str, sample_limit: int = 5, layer_name: str | None = None
) -> OgrinfoResult:
    """Run ogrinfo to get metadata AND sample rows for preview.

    Uses -json -features -limit N to get structured output with sample features.
    Falls back to summary-only run_ogrinfo() if feature extraction fails.

    Returns dict with keys: srid, geometry_type, layer_name, feature_count,
    columns, sample_rows, all_layers.
    """
    if layer_name:
        validate_layer_name_argv(layer_name)
    if _is_parquet(file_path):
        from app.processing.ingest.parquet import parquet_info

        return await parquet_info(file_path, sample_limit=sample_limit)

    source = _resolve_source_path(file_path)

    cmd = ["ogrinfo", "-json", "-features", "-limit", str(sample_limit), source]
    # CSV driver types all fields as String by default; auto-detect so
    # numeric columns appear as Real/Integer in the preview schema.
    if file_path.lower().endswith(".csv"):
        cmd[1:1] = ["-oo", "AUTODETECT_TYPE=YES"]
    if layer_name:
        cmd.append(layer_name)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _communicate_with_timeout(
        proc, OGRINFO_TIMEOUT_SECONDS, tool_name="ogrinfo"
    )

    if proc.returncode == 0:
        try:
            data = json.loads(stdout.decode())
            target_layer, metadata = _extract_common_layer_metadata(data, layer_name)
            # Preview also extracts sample rows; columns come from the
            # shared helper (PERF-1).
            metadata["sample_rows"] = [
                feat.get("properties", {}) for feat in target_layer.get("features", [])
            ]
            return metadata
        except KeyError:
            # No layers in JSON output but command succeeded — return empty shell.
            return {
                "srid": None,
                "geometry_type": None,
                "layer_name": "",
                "feature_count": None,
                "columns": [],
                "sample_rows": [],
                "all_layers": None,
            }
        except json.JSONDecodeError:
            pass  # Fall through to fallback

    # Fallback: summary only (no sample rows)
    info = await run_ogrinfo(file_path, layer_name=layer_name)
    info.setdefault("columns", [])
    info["sample_rows"] = []
    return info


async def run_ogr2ogr(
    file_path: str,
    table_name: str,
    db_conn_str: str,
    source_srid: int | None = None,
    geometry_type: str | None = None,
    layer_name: str | None = None,
    *,
    schema: str,
    effective_srid: int | None = None,
    original_filename: str | None = None,
) -> None:
    """Run ogr2ogr to load a file into PostGIS.

    Args:
        file_path: Path to the source file.
        table_name: Target table name (without schema prefix).
        db_conn_str: PG connection string for ogr2ogr.
        source_srid: Optional SRID from ogrinfo. Used for CSV defaults.
        geometry_type: Geometry type from ogrinfo. None for non-spatial files.
        schema: Target PostgreSQL schema. Required so callers cannot silently
            fall back to the shared ``data`` schema in multi-tenant mode.
        effective_srid: The SRID ``add_4326_column`` will be called with
            (user srid_override > detected > 4326). Used only by the parquet
            path, which must stamp geometries with the SRID the downstream
            ST_Transform will trust; GDAL formats carry their own CRS.
        original_filename: The user-visible upload filename (not the staging
            path in ``file_path``), used only to phrase the friendly message
            on an "unable to open" failure.

    Raises:
        IngestionError: If ogr2ogr exits with non-zero code.
    """
    from app.processing.ingest.metadata import _validate_table_name

    _validate_table_name(table_name)
    _validate_table_name(schema)
    if layer_name:
        validate_layer_name_argv(layer_name)

    if _is_parquet(file_path):
        from app.processing.ingest.parquet import load_parquet_to_postgis

        # fix(#541 review): stamp with effective_srid, not detected-or-4326.
        # For a file with unknown CRS (explicit crs:null / unresolvable
        # PROJJSON) the user proceeds via srid_override; tagging those
        # geometries 4326 would make the downstream ST_Transform a no-op.
        srid = effective_srid if effective_srid is not None else source_srid
        await load_parquet_to_postgis(
            file_path,
            table_name,
            schema=schema,
            srid=srid if srid is not None else 4326,
            include_geometry=geometry_type is not None,
        )
        return

    source = _resolve_source_path(file_path)
    is_csv = file_path.lower().endswith(".csv")
    is_non_spatial = geometry_type is None

    cmd = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        db_conn_str,
        source,
        "-overwrite",
        "-nln",
        f"{schema}.{table_name}",
        "-lco",
        "FID=gid",
        # -lco PRECISION=NO:
        #   GDAL's PostgreSQL driver defaults to PRECISION=YES, which honors source
        #   numeric(precision, scale) declarations and writes columns as PG NUMERIC.
        #   We set NO to force all numeric-family fields to FLOAT8 / INTEGER / VARCHAR.
        #   Tradeoff: we lose declared precision/scale but gain predictable query
        #   performance and simpler downstream type inference
        #   (metadata_attributes.py _infer_domain_type). Values above 2^53 may
        #   lose integer precision.
        #   Locked via .planning/quick/260410-d7k-.../260410-d7k-CONTEXT.md decision
        #   ("PRECISION=NO: leave it, document why"). Do not change without review.
        "-lco",
        "PRECISION=NO",
        "--config",
        "PG_USE_COPY",
        "YES",
        "--config",
        "SHAPE_ENCODING",
        "UTF-8",
    ]

    if not is_non_spatial:
        cmd.extend(
            [
                "-nlt",
                "PROMOTE_TO_MULTI",
                # Use a non-colliding target name so that source attributes
                # named `geom` or `geometry` (valid GeoJSON/Shapefile/GeoPackage
                # property names) do not clash with the pipeline geometry
                # column at CREATE TABLE time. `rename_reserved_columns` will
                # rename the source attribute to `src_<name>` afterwards, and
                # `ensure_geom_column` renames this placeholder to `geom`.
                "-lco",
                "GEOMETRY_NAME=_geolens_geom",
                "-lco",
                "SPATIAL_INDEX=NONE",
            ]
        )

    if is_csv and not is_non_spatial:
        cmd.extend(
            [
                "-oo",
                "X_POSSIBLE_NAMES=lon*,lng*,long*,x",
                "-oo",
                "Y_POSSIBLE_NAMES=lat*,y",
                "-oo",
                "GEOM_POSSIBLE_NAMES=WKT,wkt,geometry,geom,the_geom,shape",
            ]
        )
        if source_srid is None:
            cmd.extend(["-a_srs", "EPSG:4326"])

    if layer_name:
        cmd.append(layer_name)

    # HYG-03 (Phase 1070, v1014 IN-02): `run_ogr2ogr` processes LOCAL FILE
    # PATHS only, so it issues no HTTP fetches; the service-URL sibling
    # `run_ogr2ogr_service` (below) is the one with an HTTP surface — see the
    # fix(#937) note there for what actually bounds it.
    # In multi-tenant mode PGOPTIONS also selects the active tenant's writer
    # role for this independently opened libpq connection.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_tenant_writer_subprocess_env(schema),
    )
    stdout, stderr = await _communicate_with_timeout(
        proc, OGR2OGR_FILE_TIMEOUT_SECONDS, tool_name="ogr2ogr"
    )

    if proc.returncode != 0:
        stderr_text = stderr.decode().strip()
        if _is_unopenable_source_stderr(stderr_text):
            # Same rationale as the matching branch in run_ogrinfo above:
            # log the full diagnostic once, raise a short user-facing one.
            structlog.get_logger().error(
                "ogr2ogr could not open source file",
                exit_code=proc.returncode,
                stderr=stderr_text,
                original_filename=original_filename,
            )
            raise IngestionError(_friendly_open_failure_message(original_filename))
        raise IngestionError(f"ogr2ogr failed (exit {proc.returncode}): {stderr_text}")


async def run_ogr2ogr_service(
    gdal_source: str,
    layer_name: str,
    table_name: str,
    db_conn_str: str,
    service_type: str,
    timeout: float = 1800.0,
    token: str | None = None,
    is_non_spatial: bool = False,
    append: bool = False,
    *,
    schema: str,
    on_spawn: "Callable[[], None] | None" = None,
) -> None:
    """Run ogr2ogr to load a remote service layer into PostGIS.

    Args:
        gdal_source: GDAL-prefixed source string (e.g. "WFS:https://...")
        layer_name: Layer name (empty for ESRIJSON)
        table_name: Target table name (without schema prefix)
        db_conn_str: PG connection string for ogr2ogr
        service_type: "wfs" or "arcgis_featureserver"
        timeout: Seconds before killing subprocess (default 30 min)
        is_non_spatial: When True, omit geometry-specific flags (-nlt, -t_srs,
            GEOMETRY_NAME) to avoid dropping attribute columns for tables with
            no geometry (ArcGIS Table layers, non-spatial WFS, etc.)
        append: When True, append to an existing target layer instead of
            overwriting it. Used by chunked ArcGIS imports after the first page.
        schema: Target PostgreSQL schema. Required so service imports cannot
            silently write into the shared ``data`` schema.
        on_spawn: Invoked once, immediately after the subprocess exists —
            the first moment an outbound attempt can truthfully be said to
            have begun. Callers that date origin contacts key off this
            rather than guessing from exception types, because every local
            preflight (argv validation, token sanitization, tempfile setup,
            spawn itself) happens before it fires (fix #1271 review).
    """
    from app.processing.ingest.metadata import _validate_table_name

    _validate_table_name(table_name)
    _validate_table_name(schema)

    # fix(#1746 B2b review r16): a protected OGC API collection is read HERE
    # rather than by GDAL, and the credential never becomes a header file at
    # all. Its pages choose the next one, GDAL follows that link, and the
    # header file applies to every request the process makes, so a collection
    # whose first page is same-origin can hand the credential to any origin it
    # names on page two. GDAL 3.10.3 offers no way to scope the header to one
    # origin; that was measured, and `platform/service_items` carries the
    # result and the command. WFS is untouched: its driver pages by startIndex
    # against the endpoint the capabilities advertise, and ignores a `next`
    # attribute outright, which was measured the same way.
    items_path: str | None = None
    if token and service_type == "ogcapi_features":
        items_path = await materialise_oapif_items(
            gdal_source.split(":", 1)[1],
            layer_name,
            credential_line=_sanitize_authorization_token(
                token, service_format=service_type
            )
            or "",
            staging_dir=ensure_staging_ready(settings.upload_staging_dir),
        )
        gdal_source, layer_name, token = items_path, "", None

    if layer_name:
        validate_layer_name_argv(layer_name)
    cmd = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        db_conn_str,
        gdal_source,
        "-append" if append else "-overwrite",
        "-nln",
        f"{schema}.{table_name}",
        "-lco",
        "FID=gid",
        # -lco PRECISION=NO: same tradeoff as run_ogr2ogr — forces all
        # numeric-family fields to FLOAT8/INTEGER/VARCHAR for predictable type
        # inference. See run_ogr2ogr comment and CONTEXT.md decision for details.
        "-lco",
        "PRECISION=NO",
        "--config",
        "PG_USE_COPY",
        "YES",
        "--config",
        "GDAL_HTTP_TIMEOUT",
        str(settings.ingest_http_timeout_seconds),  # SEED-02: configurable, default 300
    ]

    if not is_non_spatial:
        # Spatial layers: reproject to WGS84 and emit a constraint-free
        # geometry column.
        #
        # D-01 / Phase 1057 — WHY -nlt GEOMETRY (not PROMOTE_TO_MULTI):
        # Some OGC/WFS services (e.g. GeoServer) declare abstract geometry
        # types in their schema (MultiSurface, MultiCurve, CompoundSurface).
        # ogr2ogr honours that declaration and creates the PostGIS column with
        # the same abstract subtype.  When the actual features arrive as
        # concrete geometries (MultiPolygon), the post-ingest bounds-clip
        # UPDATE in clip_to_mercator_bounds (metadata_mercator.py) fails with:
        #   asyncpg.exceptions.InvalidParameterValueError:
        #     Geometry type (MultiPolygon) does not match column type (MultiSurface)
        #
        # -nlt GEOMETRY instructs ogr2ogr to emit a generic `geometry(Geometry,
        # 4326)` column with no subtype constraint, so any concrete subtype
        # stored by the service's features is accepted by PostGIS transparently.
        #
        # The concrete subtype for Dataset.geometry_type is derived post-ingest
        # via get_geometry_type() (metadata_extent.py) which inspects the first
        # feature with `SELECT GeometryType(geom) … LIMIT 1`.  This keeps the
        # downstream record_type classification, icons, and UX unchanged.
        #
        # The file-ingest sibling run_ogr2ogr() continues to use
        # PROMOTE_TO_MULTI because local files always report concrete types;
        # the abstract-type problem only arises on the service-ingest path.
        #
        # GEOMETRY_NAME=_geolens_geom avoids a CREATE TABLE collision when the
        # remote service publishes an attribute named `geom`/`geometry`. The
        # post-ingest `ensure_geom_column` step renames the placeholder to
        # `geom` after `rename_reserved_columns` has moved any source
        # attribute to `src_<name>`.
        cmd += [
            "-nlt",
            "GEOMETRY",
            "-lco",
            "GEOMETRY_NAME=_geolens_geom",
            "-lco",
            "SPATIAL_INDEX=NONE",
            "-t_srs",
            "EPSG:4326",
        ]

    if layer_name:
        cmd.append(layer_name)

    if service_type == "wfs":
        cmd.extend(["--config", "OGR_WFS_PAGE_SIZE", "1000"])

    # fix(#937): Phase 1061 SEC-S04 set GDAL_HTTP_FOLLOWLOCATION=NO here,
    # believing it disabled libcurl redirect-following inside ogr2ogr. It is
    # not a GDAL configuration option and never did anything; measured on GDAL
    # 3.10.3 (the worker image) and 3.12.1, a 302 is followed identically with
    # and without it, and GDAL exposes no option that stops it. Do not re-add
    # it. The defenses this path actually has: validate_url_for_ssrf rejects
    # private/link-local hosts at submission time, and the subprocess runs
    # under a wall-clock timeout.
    #
    # SEC-008 (re-derived for #937): unlike the httpx path (make_safe_client
    # pins the validated IP via _SSRFGuardTransport and re-validates every 3xx
    # Location), libcurl under GDAL resolves DNS itself with no per-request pin
    # hook and follows redirects unconditionally. So BOTH a connect-time
    # DNS-rebinding TOCTOU and a post-validation 302 to an internal IP
    # (169.254.169.254 / 10.x / 127.x) remain open on this path — the previous
    # sign-off recorded the redirect half as bounded, which was wrong. Both
    # must be mitigated operationally: egress firewalling of the worker and
    # blocking link-local/metadata IPs at the network layer.
    #
    # IA-P1-06 (Phase 1068): Authorization headers MUST NOT pass through the
    # subprocess env (visible via /proc/<pid>/environ for the lifetime of the
    # process). Switch to GDAL_HTTP_HEADER_FILE pointed at a 0600 tempfile
    # that holds the header line — the env var is the file PATH, not the
    # token. The tempfile is unlinked in the finally block below.
    header_file_path: str | None = None
    try:
        env = _tenant_writer_subprocess_env(
            schema,
            base_env={**os.environ},
        )
        assert env is not None  # base_env is always returned in single-tenant mode
        if token and service_type in ("wfs", "ogcapi_features"):
            # fix(#1746) plan D9: for these two formats `token` IS the finished
            # header line the door composed, so this validates a line and
            # writes it verbatim. It used to compose `Authorization: Bearer `
            # here, and keeping that while being handed a finished line would
            # have produced `Authorization: Bearer Authorization: Basic <blob>`
            # — a working-looking string that 401s at the origin and reads in a
            # log like a credential problem rather than a bug. The one composer
            # is `build_credential_header`, and it ran at the door.
            header_line = _sanitize_authorization_token(
                token, service_format=service_type
            )  # SEC-FU-04: raises ValueError before subprocess

            # fix(#1746 B2b review r13): GDAL applies the header file to the
            # operation endpoints the service's own description advertises,
            # and those are fresh requests no redirect rule can see. Checked
            # here as well as at the door because the document can change
            # between a preview and the import it leads to, and this is the
            # side that actually spends the credential.
            await assert_endpoints_stay_on_origin(
                gdal_source.split(":", 1)[1],
                service_format=service_type,
                # fix(#1746 B2b review r14): sent WITH the credential, so a
                # protected service answers with the document this import will
                # act on rather than a 401 that told the check nothing. And
                # scoped to the layer being imported, which is the collection
                # whose own document names the endpoint that gets the header.
                credential_line=header_line,
                collection=layer_name or None,
            )
            # Write the header to a 0600 tempfile under the staging dir
            # (predictable owner, ephemeral). Using tempfile + os.chmod 0o600
            # (NamedTemporaryFile already creates owner-only on POSIX, but
            # set explicitly for clarity).
            import tempfile

            # fix(#1746): mkstemp had no dir=, so it landed wherever
            # `tempfile.tempdir` happened to point — a SIGKILL/OOM before the
            # finally block below then leaks the bearer-header tempfile outside
            # anything a sweep can reach.
            #
            # fix(#1746 codex r2): the directory is the container tmpfs, not
            # the staging volume. Staging is persistent and
            # `scripts/backup-entrypoint.sh` tars it every cycle, so an
            # orphaned header could be archived into a backup.
            # `gdal_header_dir()` is 0700 under /tmp, which the worker mounts
            # as its own 512m tmpfs: private to this container, gone on
            # restart, and swept at boot for anything that leaks in between.
            fd, header_file_path = tempfile.mkstemp(
                prefix="gdal_auth_", suffix=".hdr", dir=gdal_header_dir()
            )
            try:
                os.write(fd, f"{header_line}\n".encode("ascii"))
            finally:
                os.close(fd)
            os.chmod(header_file_path, 0o600)
            env["GDAL_HTTP_HEADER_FILE"] = header_file_path
            # Plan rule A: GDAL forwards `Authorization` only to the host it
            # was given to, and forwards every other header name verbatim even
            # across hosts, so a service-chosen API key is redirect-exposed on
            # this path and cannot be protected from inside (bounded
            # operationally, AGENTS.md Rule 2). The value is stated rather than
            # inherited, and it is IF_SAME_HOST rather than NO: a same-host
            # canonical redirect, such as one adding a trailing slash, must
            # keep the credential or a protected service answers 401.
            env.update(GDAL_HEADER_FILE_REDIRECT_ENV)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        if on_spawn is not None:
            on_spawn()

        # Use the shared helper for graceful kill-on-timeout (R-9).
        stdout, stderr = await _communicate_with_timeout(
            proc, timeout, tool_name="ogr2ogr (service)"
        )
    finally:
        if items_path is not None:
            try:
                os.unlink(items_path)
            except OSError:
                # Already gone is the outcome this wanted; the staging sweep
                # reclaims one a SIGKILL leaves behind.
                pass
        if header_file_path is not None:
            try:
                os.unlink(header_file_path)
            except OSError:
                # File may have been removed by another process; not a security
                # concern since contents are only the bearer token + we wrote
                # the file as 0600.
                pass

    if proc.returncode != 0:
        stripped = _strip_ogr_driver_list(
            stderr.decode()
        )  # SEED-04: strip driver list noise
        # fix(#1277 review): redact BEFORE the text becomes an exception, not
        # after. For ArcGIS the credential rides in the ESRIJSON source URL
        # (build_gdal_source puts it in the query string — only the WFS and
        # OGC API branches get the header-file treatment above), and GDAL
        # echoes the source it failed on. Every consumer of this exception is
        # a sink: the persisted IngestJob.error_message, the log record, the
        # notification reason, and the re-raise the queue records. Scrubbing
        # at each of those is four chances to forget; scrubbing here is the
        # boundary where the credential stops existing in error text at all.
        raise IngestionError(
            f"ogr2ogr failed (exit {proc.returncode}): "
            f"{redact_url_credentials(stripped.strip())}"
        )
