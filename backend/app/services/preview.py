"""Remote service layer preview via ogrinfo."""

import asyncio
import json
import os

import structlog

from app.ingest.ogr import IngestionError, _extract_srid_from_json

logger = structlog.stdlib.get_logger(__name__)


def build_gdal_source(
    service_type: str,
    base_url: str,
    layer_name: str,
    layer_id: int | str | None = None,
    token: str | None = None,
    order_field: str | None = "OBJECTID",
    result_limit: int | None = None,
) -> tuple[str, str]:
    """Construct a GDAL-prefixed source string for a remote service.

    Returns:
        Tuple of (gdal_source, layer_name) where layer_name may be empty
        for drivers that embed the layer in the source URL.
    """
    if service_type.startswith("WFS"):
        return (f"WFS:{base_url}", layer_name)
    elif service_type.startswith("ArcGIS"):
        if layer_id is None:
            raise ValueError("ArcGIS layer preview requires a layer ID")
        query_url = f"{base_url}/{layer_id}/query?f=json&where=1%3D1"
        if order_field:
            query_url += f"&orderByFields={order_field}+ASC"
        if result_limit is not None:
            query_url += f"&resultRecordCount={result_limit}"
        if token:
            query_url += f"&token={token}"
        return (f"ESRIJSON:{query_url}", "")
    else:
        raise ValueError(f"Unsupported service type: {service_type}")


async def run_service_preview(
    gdal_source: str,
    layer_name: str,
    sample_limit: int = 5,
    timeout: float = 120.0,
    token: str | None = None,
) -> dict:
    """Run ogrinfo against a remote service to get layer metadata and sample rows.

    Args:
        gdal_source: GDAL-prefixed source string (e.g. "WFS:https://..." or "ESRIJSON:https://...")
        layer_name: Layer name to query (empty string for drivers that embed layer in URL)
        sample_limit: Maximum number of sample features to retrieve
        timeout: Seconds before killing the subprocess

    Returns:
        Dict with keys: srid, geometry_type, layer_name, feature_count, columns, sample_rows
    """
    empty_fallback = {
        "srid": None,
        "geometry_type": None,
        "layer_name": layer_name,
        "feature_count": None,
        "columns": [],
        "sample_rows": [],
    }

    cmd = [
        "ogrinfo",
        "-json",
        "-features",
        "-limit",
        str(sample_limit),
        "--config",
        "GDAL_HTTP_TIMEOUT",
        "60",
        gdal_source,
    ]
    if layer_name:
        cmd.append(layer_name)

    logger.info(
        "running ogrinfo for service preview",
        gdal_source=gdal_source,
        layer_name=layer_name,
    )

    env = None
    if token and gdal_source.startswith("WFS:"):
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
        logger.warning(
            "ogrinfo timed out for service preview",
            gdal_source=gdal_source,
            layer_name=layer_name,
            timeout=timeout,
        )
        return empty_fallback

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "unknown error"
        logger.error(
            "ogrinfo failed for service preview",
            gdal_source=gdal_source,
            returncode=proc.returncode,
            stderr=error_msg,
        )
        raise IngestionError(f"ogrinfo failed: {error_msg}")

    data = json.loads(stdout.decode())
    layers = data.get("layers", [])
    if not layers:
        logger.warning(
            "ogrinfo returned no layers",
            gdal_source=gdal_source,
        )
        return empty_fallback

    layer = layers[0]

    columns = [{"name": f["name"], "type": f["type"]} for f in layer.get("fields", [])]

    sample_rows = [feat.get("properties", {}) for feat in layer.get("features", [])]

    geom_fields = layer.get("geometryFields", [])
    geometry_type = None
    coord_system = layer.get("coordinateSystem", {})
    if geom_fields:
        geometry_type = geom_fields[0].get("type")
        if not coord_system:
            coord_system = geom_fields[0].get("coordinateSystem", {})

    srid = _extract_srid_from_json(coord_system or {})

    result = {
        "srid": srid,
        "geometry_type": geometry_type,
        "layer_name": layer.get("name", layer_name),
        "feature_count": layer.get("featureCount"),
        "columns": columns,
        "sample_rows": sample_rows,
    }

    logger.info(
        "service preview complete",
        gdal_source=gdal_source,
        layer_name=result["layer_name"],
        feature_count=result["feature_count"],
        column_count=len(columns),
        sample_count=len(sample_rows),
    )

    return result
