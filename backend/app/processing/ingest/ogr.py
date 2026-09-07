"""Async subprocess wrappers for GDAL CLI tools (ogr2ogr, ogrinfo)."""

import asyncio
import json
import os
import re
import time
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
from app.platform.service_endpoints import (
    assert_endpoints_stay_on_origin,
    fire_once,
    gdal_transport_env,
    require_wfs_layer,
)
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
    register_credential_secret,
    requires_header_token_policy,
)
from app.core.url_redaction import redact_url_credentials
from app.processing.ingest.gdal_drivers import local_input_driver_args
from app.core.async_io import run_in_thread_draining
from app.processing.ingest.validation import validate_content_directives
from app.processing.raster.vrt import gdal_service_safe_env, gdal_vector_safe_env


# Matches GDAL driver-list lines like "  -> 'FITS' (read-only)". The mode
# group is optional since some GDAL builds emit bare driver names.
_OGR_DRIVER_LIST_LINE_RE = re.compile(r"^\s*->\s*'[^']+'\s*(\([^)]*\))?\s*$")

# When no driver can open the source, ogr2ogr/ogrinfo print this line
# followed by GDAL's full driver enumeration (100+ lines) — raw text a demo
# visitor once saw verbatim in the job UI. Anchored tightly so no other
# failure class (bad SRS, permission denied, disk full) matches.
_OGR_UNABLE_TO_OPEN_RE = re.compile(
    r"Unable to open datasource `[^']*' with the following drivers\."
)

# A second shape: a driver DOES claim the source (e.g. GPKG is SQLite) but
# the content is corrupt, surfacing as SQLite's own "file is not a
# database" error instead of GDAL's enumeration. Fires when the SQLite
# header itself doesn't parse (magic present, page-size/header garbage).
_SQLITE_NOT_A_DATABASE_RE = re.compile(r"file is not a database")

# fix(#1640): a THIRD shape — the SQLite header parses fine but an interior
# b-tree page is corrupt, reported as "database disk image is malformed"
# instead. Neither of the other two patterns matches this text, so without
# it the raw stderr — including the leaked staging path — passed through unmodified.
_SQLITE_DISK_IMAGE_MALFORMED_RE = re.compile(r"database disk image is malformed")


def _is_unopenable_source_stderr(stderr_text: str) -> bool:
    """True when ``stderr_text`` matches a known "can't open this source" shape.

    The three patterns all mean the same thing to the uploader — GDAL
    couldn't read it as a spatial dataset — so they map to one friendly
    message; see ``_friendly_open_failure_message``.
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
# strings, so none may name any part of the credential being judged. No
# brace in any, so none can grow an interpolation later.
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

    Composed by ``build_credential_header``, not here — the single-producer
    rule (``tests/test_credential_producer_structural.py``) exists so no
    second place in the tree can grow a prefix of its own. The builder
    applies the same base64url charset/length floor the previous version
    enforced, so a refused token gets the shape policy, not a bearer-specific
    message; the value is not named.
    """
    # fix(#1840): the format gate moved UP to
    # `_sanitize_authorization_token`'s entry; see the comment there.
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
        # A service format that carries no header at all — a silent empty
        # line would be worse than a refusal.
        raise ValueError(HEADER_LINE_SHAPE_POLICY)
    return credential_header_line(pair)


def _sanitize_authorization_token(
    header_line: "str | None", *, service_format: str
) -> "str | None":
    """SEC-FU-04: pin the credential header line to the shared policy.

    What crosses from the door to this worker is one finished header line
    (plan D9), not a bare token, so this judges a LINE: printable ASCII, no
    CR or LF, exactly one ``": "`` separator, and a name that passes
    ``header_name_rejection_reason``. A character outside that shape could
    let an attacker inject additional HTTP headers through the
    GDAL_HTTP_HEADER_FILE-to-libcurl pipeline — a security boundary, not a
    formatting preference. fix(#1277): these rules mirror
    ``app.core.service_tokens``, which every door also applies, but this
    check stays regardless since the guarantee is about what reaches libcurl
    and can't rest on a validator running in another process.

    The bearer branch keeps the base64url charset/length floor and NAMES the
    offending character — safe because every character of a bearer token is
    already constrained to a set with no secret structure. Every OTHER
    branch (fix(#1746)) is policy-only: the exception becomes
    ``IngestJob.error_message``, a log record, a notification reason and the
    queue's re-raise (``scrub_secret_from_exception`` keeps all four in
    sync), and under basic auth the judged value is an encoded
    username:password — naming a character of a password there isn't worth it.

    fix(#1746): a value with no separator is the pre-#1770 wire format and
    must keep working — a worker started while old jobs are queued reads a
    bare bearer token out of ``procrastinate_jobs.args`` or the credential
    store. Refusing it would fail those deterministically at the next
    deploy, worse than the skew #1689 already accepted at this door. So a
    bare value satisfying the old charset is composed into the line it would
    have produced, through the same builder every other caller uses.
    Anything neither a valid line nor a valid bare token raises the shape policy.

    ``service_format`` selects the builder's allowlist branch — passing the
    caller's real value (not a constant) keeps the builder the sole
    authority on which formats may carry a header.

    Returns the line the file should hold, raises ValueError with a
    SEC-FU-04-prefixed message otherwise. None passes through.
    """
    if header_line is None:
        return None
    # fix(#1840): the format gate belongs HERE, at this module's only
    # sanitization entry, not inside `_legacy_bearer_line` — which covered a
    # bare token but let a FINISHED line for a gated service_format (e.g.
    # ArcGIS) through unrefused. Both shapes are refused now; this is the
    # trust-boundary copy of the door's gate.
    if not requires_header_token_policy(service_format):
        raise ValueError(HEADER_LINE_SHAPE_POLICY)
    name, separator, value = header_line.partition(HEADER_LINE_SEPARATOR)
    if not separator:
        return _legacy_bearer_line(header_line, service_format)
    if not value or HEADER_LINE_SEPARATOR in value:
        raise ValueError(HEADER_LINE_SHAPE_POLICY)
    if not name or any(character not in HEADER_NAME_CHARSET for character in name):
        # Field-name GRAMMAR, deliberately not the door's reserved-name
        # denylist: the builder's own bearer/basic output is `Authorization`,
        # which that denylist exists to keep a CALLER from claiming.
        # Applying it here would refuse every line this codebase composes.
        raise ValueError(HEADER_LINE_NAME_POLICY)
    if any(character not in HEADER_LINE_VALUE_CHARSET for character in value):
        raise ValueError(HEADER_LINE_VALUE_POLICY)
    # fix(#1770): the D9 line — what crosses the queue for a modern job —
    # never touches `build_credential_header`, so without this the worker
    # service-import path relied only on the two explicit
    # `scrub_secret_from_exception` calls; no log line here was scrubbed.
    #
    # fix(#1844): registers the LINE, not the value. `_secret_variants`
    # (`core/url_redaction.py`) derives the bare token/basic blob/decoded
    # user:pass only from a secret CONTAINING `": "`, so registering
    # `Bearer <tok>` alone expanded to nothing — the worker couldn't scrub a
    # bare token an origin echoed back. Registering the line expands to
    # every shape and never yields the bare word `Authorization` (the tail
    # always starts after `": "`).
    #
    # fix(#1844): registers only AFTER the bearer grammar below is checked —
    # registering earlier let a line this function goes on to REFUSE seed
    # the registry (e.g. `Authorization: Bearer e` seeding the one-character
    # variant `e`, which then redacts every "e" in every log line for the rest
    # of the job). A refused line is not a secret in play.
    if value.startswith(BEARER_SCHEME):
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
                f"SEC-FU-04: Authorization token contains non-base64url "
                f"character (first offender: {sample!r}); only "
                "[A-Za-z0-9._\\-=] are permitted to prevent CRLF header "
                "smuggling via GDAL_HTTP_HEADERS env var."
            )

    register_credential_secret(header_line)
    return header_line


def _strip_ogr_driver_list(stderr_text: str) -> str:
    """Remove GDAL driver-list lines from ogr2ogr stderr output.

    ogr2ogr emits a 150+ line driver enumeration before the actual error
    when it can't open a source; this strips those "  -> 'NAME' (modes)"
    lines so IngestionError messages carry only the actionable line(s).
    Runs of blank lines left behind collapse to one; result is stripped.

    Safety: the regex only matches that exact shape, so a future GDAL
    format change means nothing gets stripped, never that real content is removed.
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


# Subprocess timeouts (R-5, R-9): wall-clock limits protect the
# Procrastinate worker from hanging on a bad file or a slow/hung upstream
# service. Tune via settings if your datasets are routinely large.

# fix(#1746): what's left for ogr2ogr when in-process materialisation used
# the whole clock. A second, not zero, so it fails through the ordinary
# timeout path/message rather than an arithmetic edge — same floor
# `export_subprocess_timeout_seconds` keeps, for the same reason.
_SUBPROCESS_FLOOR_SECONDS = 1.0

OGRINFO_TIMEOUT_SECONDS = 300  # 5 min — metadata probe, should be fast
OGR2OGR_FILE_TIMEOUT_SECONDS = 3600  # 1 hour — large files legitimately take a while
OGR2OGR_SERVICE_TIMEOUT_SECONDS = 1800  # 30 min — existing value, now a named constant


async def _kill_and_reap_subprocess(proc: asyncio.subprocess.Process) -> None:
    """Best-effort kill + reap for a subprocess whose ``communicate()`` ended abnormally.

    Shared by both ``_communicate_with_timeout`` branches below.
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

    On cancellation (client disconnect, or Procrastinate shutdown),
    ``asyncio.wait_for`` re-raises ``CancelledError`` without touching the
    child process — without the branch below, a caller that then deletes
    its output directory (export cleanup) would race a process that may
    still hold the file open. Runs the same kill/terminate/wait sequence,
    then re-raises so cancellation still propagates.
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

    ogr2ogr opens its own PostgreSQL connection, outside SQLAlchemy's
    statement hooks, so ``PGOPTIONS`` is the connection-time equivalent.
    Single-tenant mode returns ``base_env`` unchanged.
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

    # Always expose all_layers when source has >1 layers, regardless of
    # whether a specific layer_name was requested — layer-select UX
    # (ReuploadDialog) needs the list even after a targeted preview.
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
    # fix(#1846, GHSA-hrf5-v3cq-frx5): all three layers, on every staged-file
    # argv — this is the last point before GDAL sees the file, and preview
    # runs before the door that validates a presigned upload's whole body.
    await run_in_thread_draining(
        validate_content_directives, file_path, original_filename
    )
    driver_args = local_input_driver_args(file_path)
    driver_env = gdal_vector_safe_env()

    # Try JSON output first (GDAL 3.7+)
    cmd = ["ogrinfo", "-so", "-json", *driver_args]
    # CSV driver types all fields as String by default; auto-detect so
    # numeric columns appear as Real/Integer in the preview schema.
    if file_path.lower().endswith(".csv"):
        cmd += ["-oo", "AUTODETECT_TYPE=YES"]
    cmd.append(source)
    if layer_name:
        cmd.append(layer_name)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=driver_env,
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
    cmd_text = ["ogrinfo", "-so", *driver_args, source]
    if layer_name:
        cmd_text.append(layer_name)
    proc = await asyncio.create_subprocess_exec(
        *cmd_text,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=driver_env,
    )
    stdout, stderr = await _communicate_with_timeout(
        proc, OGRINFO_TIMEOUT_SECONDS, tool_name="ogrinfo"
    )

    if proc.returncode != 0:
        stderr_text = stderr.decode().strip()
        if _is_unopenable_source_stderr(stderr_text):
            # Full stderr is diagnostic gold for us but noise (plus a leaked
            # staging path) for the job UI — log it here, raise a friendly message.
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
    # fix(#1846, GHSA-hrf5-v3cq-frx5): preview returns rows to the caller, so
    # it must not ask an unrestricted driver set what the file is, and a
    # database whose schema reads from outside the file must not reach it.
    await run_in_thread_draining(validate_content_directives, file_path)
    driver_args = local_input_driver_args(file_path)

    cmd = ["ogrinfo", "-json", "-features", "-limit", str(sample_limit), *driver_args]
    # CSV driver types all fields as String by default; auto-detect so
    # numeric columns appear as Real/Integer in the preview schema.
    if file_path.lower().endswith(".csv"):
        cmd += ["-oo", "AUTODETECT_TYPE=YES"]
    cmd.append(source)
    if layer_name:
        cmd.append(layer_name)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=gdal_vector_safe_env(),
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

        # fix(#541): stamp with effective_srid, not detected-or-4326. A file
        # with unknown CRS proceeds via srid_override; tagging it 4326
        # would make the downstream ST_Transform a no-op.
        srid = effective_srid if effective_srid is not None else source_srid
        await load_parquet_to_postgis(
            file_path,
            table_name,
            schema=schema,
            srid=srid if srid is not None else 4326,
            include_geometry=geometry_type is not None,
        )
        return

    # fix(#1846, GHSA-hrf5-v3cq-frx5): re-checked at commit, not trusted from
    # preview — the two calls read the staged file at different moments.
    await run_in_thread_draining(
        validate_content_directives, file_path, original_filename
    )
    source = _resolve_source_path(file_path)
    is_csv = file_path.lower().endswith(".csv")
    is_non_spatial = geometry_type is None

    cmd = [
        "ogr2ogr",
        # fix(#1846, GHSA-hrf5-v3cq-frx5): same driver allowlist the preview
        # used — the commit must not select a driver the preview refused.
        *local_input_driver_args(file_path),
        "-f",
        "PostgreSQL",
        db_conn_str,
        source,
        "-overwrite",
        "-nln",
        f"{schema}.{table_name}",
        "-lco",
        "FID=gid",
        # -lco PRECISION=NO: forces numeric-family fields to FLOAT8/INTEGER/
        # VARCHAR instead of GDAL's default PG NUMERIC. Trades declared
        # precision/scale (values above 2^53 may lose integer precision) for
        # predictable query performance and simpler type inference
        # (metadata_attributes.py _infer_domain_type). Locked decision — do
        # not change without review.
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

    # `run_ogr2ogr` processes LOCAL FILE PATHS only, so it issues no HTTP
    # fetches — `run_ogr2ogr_service` below is the one with an HTTP surface
    # (see its fix(#937) note). In multi-tenant mode PGOPTIONS also selects
    # the active tenant's writer role for this independent libpq connection.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # fix(#1846, GHSA-hrf5-v3cq-frx5): the clamp is the BASE the tenant
        # role is layered onto, so both single- and multi-tenant carry it.
        env=_tenant_writer_subprocess_env(schema, base_env=gdal_vector_safe_env()),
    )
    stdout, stderr = await _communicate_with_timeout(
        proc, OGR2OGR_FILE_TIMEOUT_SECONDS, tool_name="ogr2ogr"
    )

    if proc.returncode != 0:
        stderr_text = stderr.decode().strip()
        if _is_unopenable_source_stderr(stderr_text):
            # Same rationale as run_ogrinfo above.
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
        service_type: "wfs", "ogcapi_features" or "arcgis_featureserver"
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
            have begun. fix(#1271): callers date origin contacts off this
            rather than guessing from exception types, since every local
            preflight happens before it fires.
    """
    from app.processing.ingest.metadata import _validate_table_name

    _validate_table_name(table_name)
    _validate_table_name(schema)

    # fix(#1746): a protected OGC API collection is read HERE, not by GDAL,
    # so the credential never becomes a header file — GDAL applies a header
    # file to every request the process makes, and a collection whose page 2
    # names a different origin would otherwise hand it the credential too.
    # GDAL 3.10.3 has no way to scope a header to one origin (measured; see
    # `platform/service_items`). WFS is untouched: its driver pages by
    # startIndex against the capabilities endpoint and ignores `next`.
    items_path: str | None = None
    # fix(#1746): one clock over the materialisation AND the subprocess —
    # otherwise a service trickling pages inside the per-read timeout could
    # hold a worker for hours and still get the full timeout to convert.
    deadline = time.monotonic() + timeout
    # fix(#1746): ONE callback, wrapped to fire at most once, handed to every
    # site that might reach the origin first (page walk, preflight, spawn) —
    # nulling it after one "expected" caller would assume a callee that
    # returns early or is stubbed still fires it, silently losing the contact date.
    arm_origin_contact = fire_once(on_spawn)
    if token and service_type == "ogcapi_features":
        items_path = (
            await materialise_oapif_items(
                gdal_source.split(":", 1)[1],
                layer_name,
                credential_line=_sanitize_authorization_token(
                    token, service_format=service_type
                )
                or "",
                staging_dir=ensure_staging_ready(settings.upload_staging_dir),
                deadline=deadline,
                # fix(#1746): the origin is contacted by the walk now, not
                # the subprocess — a materialisation failing on its first
                # page still reached the service. Fires at most once; spawn
                # below skips it if the walk already fired.
                on_first_request=arm_origin_contact,
            )
        ).path
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
        # -lco PRECISION=NO: same tradeoff as run_ogr2ogr — see its comment.
        "-lco",
        "PRECISION=NO",
        "--config",
        "PG_USE_COPY",
        "YES",
        "--config",
        "GDAL_HTTP_TIMEOUT",
        str(settings.ingest_http_timeout_seconds),  # configurable, default 300
    ]

    if not is_non_spatial:
        # WHY -nlt GEOMETRY, not PROMOTE_TO_MULTI: some OGC/WFS services
        # (e.g. GeoServer) declare abstract geometry types (MultiSurface,
        # MultiCurve) in their schema; ogr2ogr honours that, but when
        # concrete features (MultiPolygon) arrive, the post-ingest
        # bounds-clip UPDATE in clip_to_mercator_bounds
        # (metadata_mercator.py) fails with "Geometry type (MultiPolygon)
        # does not match column type (MultiSurface)". -nlt GEOMETRY
        # emits a constraint-free `geometry(Geometry, 4326)` column instead,
        # so any concrete subtype is accepted. The concrete
        # Dataset.geometry_type is derived post-ingest via
        # get_geometry_type() (metadata_extent.py). run_ogr2ogr() (file
        # ingest) keeps PROMOTE_TO_MULTI since local files always report
        # concrete types.
        #
        # GEOMETRY_NAME=_geolens_geom avoids a CREATE TABLE collision when
        # the service publishes a `geom`/`geometry` attribute;
        # `ensure_geom_column` renames the placeholder after
        # `rename_reserved_columns` moves any source attribute to `src_<name>`.
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

    # fix(#937): GDAL_HTTP_FOLLOWLOCATION is NOT a real GDAL option and never
    # did anything — measured on GDAL 3.10.3 (worker image) and 3.12.1, a
    # 302 is followed identically with or without it, and GDAL exposes no
    # option that stops it. Never re-add it. Actual defenses on this path:
    # validate_url_for_ssrf rejects private/link-local hosts at submission
    # time, and the subprocess runs under a wall-clock timeout.
    #
    # Unlike the httpx path (make_safe_client pins the validated IP and
    # re-validates every 3xx Location), libcurl under GDAL resolves DNS
    # itself with no per-request pin and follows redirects unconditionally.
    # So both a connect-time DNS-rebinding TOCTOU and a post-validation 302
    # to an internal/metadata IP remain open here, mitigated only
    # operationally: worker egress firewalling and blocking link-local/
    # metadata IPs at the network layer.
    #
    # Authorization headers MUST NOT pass through the subprocess env
    # (visible via /proc/<pid>/environ for the process lifetime) — use
    # GDAL_HTTP_HEADER_FILE pointed at a 0600 tempfile holding the header
    # line instead; the env var is the file PATH, not the token. Unlinked in
    # the finally block below.
    header_file_path: str | None = None
    try:
        env = _tenant_writer_subprocess_env(
            schema,
            # fix(#1846, GHSA-hrf5-v3cq-frx5): keeps WFS/OAPIF, the point of
            # this call, and refuses the rest — a service response has no
            # business selecting the VRT driver or shelling out to a helper.
            base_env=gdal_service_safe_env(),
        )
        assert env is not None  # base_env is always returned in single-tenant mode
        if token and service_type in ("wfs", "ogcapi_features"):
            # fix(#1746) plan D9: for these two formats `token` IS the
            # finished header line the door composed, so this validates and
            # writes it verbatim — composing `Authorization: Bearer ` here
            # too would have produced `Authorization: Bearer Authorization:
            # Basic <blob>`, a working-looking string that just 401s.
            header_line = _sanitize_authorization_token(
                token, service_format=service_type
            )  # SEC-FU-04: raises ValueError before subprocess

            # fix(#1828): a credentialed WFS never reaches GDAL without a
            # layer, since GDAL opened layerless reads every layer's schema.
            require_wfs_layer(
                layer_name, service_format=service_type, credential_line=header_line
            )
            # fix(#1746): GDAL applies the header file to the operation
            # endpoints the service's own description advertises — fresh
            # requests no redirect rule can see. Checked here as well as at
            # the door because the document can change between a preview
            # and the import, and this is the side that spends the credential.
            await assert_endpoints_stay_on_origin(
                gdal_source.split(":", 1)[1],
                service_format=service_type,
                # fix(#1746): sent WITH the credential, so a protected
                # service answers with the document this import will act on
                # rather than a 401. Scoped to the layer being imported —
                # the collection whose document names the endpoint that
                # gets the header.
                credential_line=header_line,
                collection=layer_name or None,
                # fix(#1746): same clock as the subprocess it precedes, and
                # arms the origin-contact callback — firing only at spawn
                # would leave `origin_contact_attempted`/`last_checked_at`
                # stale for exactly the failures this preflight produces.
                deadline=deadline,
                on_first_request=arm_origin_contact,
            )
            # Header written to a 0600 tempfile under the staging dir.
            import tempfile

            # fix(#1746): mkstemp had no dir=, so it landed wherever
            # `tempfile.tempdir` pointed — a SIGKILL/OOM before the finally
            # block below then leaked the bearer-header tempfile.
            #
            # fix(#1746): the directory is the container tmpfs, not the
            # staging volume — staging is persistent and gets tarred into
            # backups (`scripts/backup-entrypoint.sh`), so an orphaned
            # header could be archived. `gdal_header_dir()` is 0700 under
            # /tmp, the worker's own 512m tmpfs: private to this container,
            # gone on restart, swept at boot.
            fd, header_file_path = tempfile.mkstemp(
                prefix="gdal_auth_", suffix=".hdr", dir=gdal_header_dir()
            )
            try:
                os.write(fd, f"{header_line}\n".encode("ascii"))
            finally:
                os.close(fd)
            os.chmod(header_file_path, 0o600)
            env["GDAL_HTTP_HEADER_FILE"] = header_file_path
            env.update(gdal_transport_env(service_type))
            # Plan rule A: GDAL forwards `Authorization` only to the host it
            # was given to, but forwards every other header name verbatim
            # across hosts, so a service-chosen API key is redirect-exposed
            # here and can't be protected from inside (bounded
            # operationally, AGENTS.md Rule 2). IF_SAME_HOST, not NO: a
            # same-host canonical redirect (e.g. a trailing slash) must
            # keep the credential or a protected service answers 401.
            env.update(GDAL_HEADER_FILE_REDIRECT_ENV)

        # fix(#1746): computed HERE, not at each spender, so it accounts for
        # all of them (page walk, preflight). Floored so a preflight that
        # used the whole budget still fails through the ordinary subprocess
        # timeout rather than an arithmetic edge.
        timeout = max(deadline - time.monotonic(), _SUBPROCESS_FLOOR_SECONDS)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        if arm_origin_contact is not None:
            # No-op when the walk or preflight already reached the origin.
            arm_origin_contact()

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
        # fix(#1277): redact BEFORE the text becomes an exception. For
        # ArcGIS the credential rides in the ESRIJSON source URL query
        # string (only WFS/OGC API get the header-file treatment above),
        # and GDAL echoes the failed source. Every consumer of this
        # exception is a sink (error_message, log, notification, re-raise);
        # scrubbing here is the one boundary rather than four chances to forget.
        raise IngestionError(
            f"ogr2ogr failed (exit {proc.returncode}): "
            f"{redact_url_credentials(stripped.strip())}"
        )
