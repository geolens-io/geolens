"""Async subprocess wrappers for GDAL CLI tools (ogr2ogr, ogrinfo)."""

import asyncio
import json
import os
import re
import string
from typing import TypedDict

from app.core.config import settings
from app.core.crs_uri import parse_crs_uri


# SEED-04 (Phase 1054): compiled once at module scope to avoid repeated re.compile().
# Matches GDAL driver-list lines like "  -> 'FITS' (read-only)" or " -> 'PCIDSK' (rw+v)".
# The trailing mode group (...) is optional — some GDAL builds emit bare driver names
# without a mode suffix, so the regex accepts " -> 'NAME'" with optional "(...)" after.
_OGR_DRIVER_LIST_LINE_RE = re.compile(r"^\s*->\s*'[^']+'\s*(\([^)]*\))?\s*$")

# SEC-FU-04 (sec-audit-20260519.md line 535, Phase 1063-03):
# Allowed characters for an Authorization bearer token passed to GDAL_HTTP_HEADERS.
# JWT-shaped tokens use the base64url charset (RFC 4648 §5) plus dot separators
# (RFC 7519 — header.payload.signature segments). Restricting to this set prevents
# a token containing CR/LF from smuggling extra HTTP headers into libcurl via the
# GDAL_HTTP_HEADERS environment variable.
_BASE64URL_CHARSET = frozenset(string.ascii_letters + string.digits + "._-=")


def _sanitize_authorization_token(token: "str | None") -> "str | None":
    """SEC-FU-04: pin Authorization bearer token to base64url charset before GDAL env composition.

    A token containing CR/LF or arbitrary unicode could let an attacker inject additional
    HTTP headers via the GDAL_HTTP_HEADERS env-var → libcurl pipeline. JWT-shaped tokens
    use the base64url charset plus dot separators (RFC 4648 §5 + RFC 7519); legitimate
    tokens never include CR/LF/whitespace/unicode.

    Tokens shorter than 8 characters raise ValueError with a SEC-FU-04-prefixed
    message. The 8-character floor is intentional: legitimate JWT-shaped tokens
    always exceed this (a minimal three-segment header.payload.signature exceeds
    20 characters), and accepting 1-7 character tokens lets a single accidental
    truncation upstream — for example, a quoted JSON field cut at the wrong
    index, or an ArcGIS deployment that emits a short tracking token mistaken
    for a bearer — silently slip into the GDAL_HTTP_HEADERS pipeline. Callers
    who legitimately need to pass a sub-8-character token must use a different
    authentication path (e.g., GDAL_HTTP_HEADER_FILE with a custom header).

    Returns the token unchanged if every character is in _BASE64URL_CHARSET.
    Raises ValueError with a SEC-FU-04-prefixed message otherwise.
    None passes through (caller's no-token path).
    """
    if token is None:
        return None
    if not token or len(token) < 8:
        raise ValueError(
            "SEC-FU-04: Authorization token is empty or implausibly short "
            "(minimum 8 characters required to prevent single-char attack payloads)."
        )
    bad = [c for c in token if c not in _BASE64URL_CHARSET]
    if bad:
        sample = bad[0]
        raise ValueError(
            f"SEC-FU-04: Authorization token contains non-base64url character "
            f"(first offender: {sample!r}); only [A-Za-z0-9._\\-=] are permitted "
            "to prevent CRLF header smuggling via GDAL_HTTP_HEADERS env var."
        )
    return token


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


# ---------------------------------------------------------------------------
# Subprocess timeouts (R-5, R-9)
# ---------------------------------------------------------------------------
# Wall-clock limits protect the Procrastinate worker from hanging on a bad
# file or a slow/hung upstream service. Tune via settings if your datasets
# are routinely large.

OGRINFO_TIMEOUT_SECONDS = 300  # 5 min — metadata probe, should be fast
OGR2OGR_FILE_TIMEOUT_SECONDS = 3600  # 1 hour — large files legitimately take a while
OGR2OGR_SERVICE_TIMEOUT_SECONDS = 1800  # 30 min — existing value, now a named constant


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
    """
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        except Exception:  # broad: kill() can fail with permission/state errors; fall back to terminate()
            try:
                proc.terminate()
            except Exception:  # broad: terminate() best-effort cleanup; give up if subprocess is already gone
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        raise IngestionError(
            f"{tool_name} timed out after {int(timeout)}s — the file or upstream service is too slow"
        )


# ---------------------------------------------------------------------------
# Geometry column auto-detection patterns
# ---------------------------------------------------------------------------

LAT_PATTERNS = {"lat", "latitude", "y", "lat_dd", "ycoord"}
LNG_PATTERNS = {"lon", "lng", "long", "longitude", "x", "lon_dd", "xcoord"}
WKT_PATTERNS = {"wkt", "geom", "geometry", "the_geom", "shape"}

# Column names that collide with GeoLens-internal PostGIS columns created
# during ingestion. If a source file has an attribute with any of these
# names, the ingest pipeline auto-renames it to `src_<name>` before the
# remaining post-ingest steps run. See metadata.py rename_reserved_columns.
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


def _resolve_source_path(file_path: str) -> str:
    """Wrap file path with /vsizip/ if it is a zip file."""
    if file_path.endswith(".zip"):
        return f"/vsizip/{file_path}"
    return file_path


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


async def run_ogrinfo(file_path: str, layer_name: str | None = None) -> OgrinfoResult:
    """Run ogrinfo to detect CRS and layer metadata.

    Returns dict with keys: srid, geometry_type, layer_name, feature_count, all_layers.
    When multiple layers exist and no layer_name is specified, all_layers lists them.
    Tries JSON output first (GDAL 3.7+), falls back to text parsing.
    """
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
        raise IngestionError(
            f"ogrinfo failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )

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
) -> None:
    """Run ogr2ogr to load a file into PostGIS.

    Args:
        file_path: Path to the source file.
        table_name: Target table name (without schema prefix).
        db_conn_str: PG connection string for ogr2ogr.
        source_srid: Optional SRID from ogrinfo. Used for CSV defaults.
        geometry_type: Geometry type from ogrinfo. None for non-spatial files.

    Raises:
        IngestionError: If ogr2ogr exits with non-zero code.
    """
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
        f"data.{table_name}",
        "-lco",
        "FID=gid",
        # -lco PRECISION=NO:
        #   GDAL's PostgreSQL driver defaults to PRECISION=YES, which honors source
        #   numeric(precision, scale) declarations and writes columns as PG NUMERIC.
        #   We set NO to force all numeric-family fields to FLOAT8 / INTEGER / VARCHAR.
        #   Tradeoff: we lose declared precision/scale but gain predictable query
        #   performance and simpler downstream type inference (metadata.py
        #   _infer_domain_type). Values above 2^53 may lose integer precision.
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

    # HYG-03 (Phase 1070, v1014 IN-02): GDAL_HTTP_FOLLOWLOCATION is NOT set
    # here because `run_ogr2ogr` processes LOCAL FILE PATHS only; libcurl
    # redirect control is irrelevant when there are no HTTP fetches. The
    # service-URL sibling `run_ogr2ogr_service` (below) DOES set
    # GDAL_HTTP_FOLLOWLOCATION=NO because it issues real HTTP requests.
    # See Phase 1061 Plan 04 SUMMARY for the SEC-S04 redirect-bypass closure.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _communicate_with_timeout(
        proc, OGR2OGR_FILE_TIMEOUT_SECONDS, tool_name="ogr2ogr"
    )

    if proc.returncode != 0:
        raise IngestionError(
            f"ogr2ogr failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )


async def run_ogr2ogr_service(
    gdal_source: str,
    layer_name: str,
    table_name: str,
    db_conn_str: str,
    service_type: str,
    timeout: float = 1800.0,
    token: str | None = None,
    is_non_spatial: bool = False,
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
    """
    cmd = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        db_conn_str,
        gdal_source,
        "-overwrite",
        "-nln",
        f"data.{table_name}",
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
        # UPDATE in clip_to_mercator_bounds (metadata.py) fails with:
        #   asyncpg.exceptions.InvalidParameterValueError:
        #     Geometry type (MultiPolygon) does not match column type (MultiSurface)
        #
        # -nlt GEOMETRY instructs ogr2ogr to emit a generic `geometry(Geometry,
        # 4326)` column with no subtype constraint, so any concrete subtype
        # stored by the service's features is accepted by PostGIS transparently.
        #
        # The concrete subtype for Dataset.geometry_type is derived post-ingest
        # via get_geometry_type() (metadata.py:165) which inspects the first
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

    # Phase 1061 SEC-S04: disable libcurl redirect-following inside ogr2ogr so
    # that a service URL pointing at a public proxy cannot 302 the GDAL HTTP
    # driver to an internal IP (169.254.169.254 / 10.x / 127.x).
    # validate_url_for_ssrf runs at submission time but ogr2ogr does its own
    # HTTP; GDAL_HTTP_FOLLOWLOCATION=NO is the only way to disable
    # redirect-following in libcurl under GDAL.
    #
    # IA-P1-06 (Phase 1068): Authorization headers MUST NOT pass through the
    # subprocess env (visible via /proc/<pid>/environ for the lifetime of the
    # process). Switch to GDAL_HTTP_HEADER_FILE pointed at a 0600 tempfile
    # that holds the header line — the env var is the file PATH, not the
    # token. The tempfile is unlinked in the finally block below.
    header_file_path: str | None = None
    try:
        env = {**os.environ, "GDAL_HTTP_FOLLOWLOCATION": "NO"}
        if token and service_type in ("wfs", "ogcapi_features"):
            safe_token = _sanitize_authorization_token(token)  # SEC-FU-04: raises ValueError before subprocess
            # Write the header to a 0600 tempfile under the staging dir
            # (predictable owner, ephemeral). Using tempfile + os.chmod 0o600
            # (NamedTemporaryFile already creates owner-only on POSIX, but
            # set explicitly for clarity).
            import tempfile

            fd, header_file_path = tempfile.mkstemp(
                prefix="gdal_auth_", suffix=".hdr"
            )
            try:
                os.write(fd, f"Authorization: Bearer {safe_token}\n".encode("ascii"))
            finally:
                os.close(fd)
            os.chmod(header_file_path, 0o600)
            env["GDAL_HTTP_HEADER_FILE"] = header_file_path

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Use the shared helper for graceful kill-on-timeout (R-9).
        stdout, stderr = await _communicate_with_timeout(
            proc, timeout, tool_name="ogr2ogr (service)"
        )
    finally:
        if header_file_path is not None:
            try:
                os.unlink(header_file_path)
            except OSError:
                # File may have been removed by another process; not a security
                # concern since contents are only the bearer token + we wrote
                # the file as 0600.
                pass

    if proc.returncode != 0:
        stripped = _strip_ogr_driver_list(stderr.decode())  # SEED-04: strip driver list noise
        raise IngestionError(
            f"ogr2ogr failed (exit {proc.returncode}): {stripped.strip()}"
        )
