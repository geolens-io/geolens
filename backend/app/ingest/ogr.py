"""Async subprocess wrappers for GDAL CLI tools (ogr2ogr, ogrinfo)."""

import asyncio
import json
import os
import re

from app.config import settings


class IngestionError(Exception):
    """Raised when an ingestion subprocess fails."""


# ---------------------------------------------------------------------------
# Geometry column auto-detection patterns
# ---------------------------------------------------------------------------

LAT_PATTERNS = {"lat", "latitude", "y", "lat_dd", "ycoord"}
LNG_PATTERNS = {"lon", "lng", "long", "longitude", "x", "lon_dd", "xcoord"}
WKT_PATTERNS = {"wkt", "geom", "geometry", "the_geom", "shape"}


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


def _extract_srid_from_json(coord_system: dict) -> int | None:
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

    return None


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


async def run_ogrinfo(file_path: str, layer_name: str | None = None) -> dict:
    """Run ogrinfo to detect CRS and layer metadata.

    Returns dict with keys: srid, geometry_type, layer_name, feature_count, all_layers.
    When multiple layers exist and no layer_name is specified, all_layers lists them.
    Tries JSON output first (GDAL 3.7+), falls back to text parsing.
    """
    source = _resolve_source_path(file_path)

    # Try JSON output first (GDAL 3.7+)
    cmd = ["ogrinfo", "-so", "-json", source]
    if layer_name:
        cmd.append(layer_name)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode == 0:
        try:
            data = json.loads(stdout.decode())
            layers = data.get("layers", [])
            if layers:
                layer = layers[0]
                geom_fields = layer.get("geometryFields", [])
                geometry_type = None
                coord_system = layer.get("coordinateSystem", {})
                if geom_fields:
                    geometry_type = geom_fields[0].get("type")
                    # coordinateSystem may be nested inside geometryFields
                    if not coord_system:
                        coord_system = geom_fields[0].get("coordinateSystem", {})
                srid = _extract_srid_from_json(coord_system or {})

                # Build all_layers list for multi-layer files
                all_layers = None
                if len(layers) > 1 and not layer_name:
                    all_layers = [
                        {
                            "name": lyr.get("name", ""),
                            "feature_count": lyr.get("featureCount", 0),
                            "field_count": len(lyr.get("fields", [])),
                        }
                        for lyr in layers
                    ]

                return {
                    "srid": srid,
                    "geometry_type": geometry_type,
                    "layer_name": layer.get("name", ""),
                    "feature_count": layer.get("featureCount"),
                    "all_layers": all_layers,
                }
            # No layers found but command succeeded
            return {
                "srid": None,
                "geometry_type": None,
                "layer_name": "",
                "feature_count": None,
                "all_layers": None,
            }
        except (json.JSONDecodeError, KeyError):
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
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise IngestionError(
            f"ogrinfo failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )

    result = _parse_text_ogrinfo(stdout.decode())
    result["all_layers"] = None
    return result


async def run_ogrinfo_preview(
    file_path: str, sample_limit: int = 5, layer_name: str | None = None
) -> dict:
    """Run ogrinfo to get metadata AND sample rows for preview.

    Uses -json -features -limit N to get structured output with sample features.
    Falls back to summary-only run_ogrinfo() if feature extraction fails.

    Returns dict with keys: srid, geometry_type, layer_name, feature_count,
    columns, sample_rows, all_layers.
    """
    source = _resolve_source_path(file_path)

    cmd = ["ogrinfo", "-json", "-features", "-limit", str(sample_limit), source]
    if layer_name:
        cmd.append(layer_name)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode == 0:
        try:
            data = json.loads(stdout.decode())
            layers = data.get("layers", [])
            if layers:
                # Find the target layer
                target_layer = layers[0]
                if layer_name:
                    for lyr in layers:
                        if lyr.get("name") == layer_name:
                            target_layer = lyr
                            break

                # Extract columns from layer fields
                columns = [
                    {"name": f["name"], "type": f["type"]}
                    for f in target_layer.get("fields", [])
                ]

                # Extract sample rows from features
                sample_rows = [
                    feat.get("properties", {})
                    for feat in target_layer.get("features", [])
                ]

                # Extract metadata
                coord_system = target_layer.get("coordinateSystem", {})
                srid = _extract_srid_from_json(coord_system or {})
                geometry_type = None
                geom_fields = target_layer.get("geometryFields", [])
                if geom_fields:
                    geometry_type = geom_fields[0].get("type")

                # Build all_layers list for multi-layer files
                all_layers = None
                if len(layers) > 1 and not layer_name:
                    all_layers = [
                        {
                            "name": lyr.get("name", ""),
                            "feature_count": lyr.get("featureCount", 0),
                            "field_count": len(lyr.get("fields", [])),
                        }
                        for lyr in layers
                    ]

                return {
                    "srid": srid,
                    "geometry_type": geometry_type,
                    "layer_name": target_layer.get("name", ""),
                    "feature_count": target_layer.get("featureCount"),
                    "columns": columns,
                    "sample_rows": sample_rows,
                    "all_layers": all_layers,
                }

            # No layers found but command succeeded
            return {
                "srid": None,
                "geometry_type": None,
                "layer_name": "",
                "feature_count": None,
                "columns": [],
                "sample_rows": [],
                "all_layers": None,
            }
        except (json.JSONDecodeError, KeyError):
            pass  # Fall through to fallback

    # Fallback: summary only (no sample rows)
    info = await run_ogrinfo(file_path, layer_name=layer_name)
    info["columns"] = []
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
        "-lco",
        "PRECISION=NO",
        "--config",
        "PG_USE_COPY",
        "YES",
    ]

    if not is_non_spatial:
        cmd.extend(
            [
                "-nlt",
                "PROMOTE_TO_MULTI",
                "-lco",
                "GEOMETRY_NAME=geom",
                "-lco",
                "SPATIAL_INDEX=GIST",
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

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

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
) -> None:
    """Run ogr2ogr to load a remote service layer into PostGIS.

    Args:
        gdal_source: GDAL-prefixed source string (e.g. "WFS:https://...")
        layer_name: Layer name (empty for ESRIJSON)
        table_name: Target table name (without schema prefix)
        db_conn_str: PG connection string for ogr2ogr
        service_type: "wfs" or "arcgis_featureserver"
        timeout: Seconds before killing subprocess (default 30 min)
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
        "-nlt",
        "PROMOTE_TO_MULTI",
        "-lco",
        "GEOMETRY_NAME=geom",
        "-lco",
        "FID=gid",
        "-lco",
        "PRECISION=NO",
        "-lco",
        "SPATIAL_INDEX=GIST",
        "-t_srs",
        "EPSG:4326",
        "--config",
        "PG_USE_COPY",
        "YES",
        "--config",
        "GDAL_HTTP_TIMEOUT",
        "120",
    ]

    if layer_name:
        cmd.append(layer_name)

    if service_type == "wfs":
        cmd.extend(["--config", "OGR_WFS_PAGE_SIZE", "1000"])

    env = None
    if token and service_type == "wfs":
        env = {**os.environ, "GDAL_HTTP_HEADERS": f"Authorization: Bearer {token}"}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise IngestionError(
            f"ogr2ogr timed out after {int(timeout)}s importing remote service"
        )

    if proc.returncode != 0:
        raise IngestionError(
            f"ogr2ogr failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )
