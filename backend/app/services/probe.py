"""Service type detection orchestration logic.

Coordinates WFS and ArcGIS probing to detect what kind of service a URL
points to and return a unified layer list.
"""

import structlog

import httpx

from app.services.arcgis import (
    _looks_like_arcgis,
    _looks_like_wfs,
    enrich_arcgis_feature_counts,
    normalize_arcgis_url,
    probe_arcgis_service,
)
from app.services.schemas import LayerInfo, ProbeResponse
from app.services.wfs import enrich_wfs_layers, probe_wfs

logger = structlog.stdlib.get_logger(__name__)


class ServiceNotRecognized(Exception):
    """Raised when the URL doesn't match any known service type."""

    def __init__(
        self,
        message: str = "Couldn't detect service type. Supported: WFS and ArcGIS Feature Service",
    ):
        super().__init__(message)


def _build_wfs_response(
    wfs_result: dict, enriched_layers: list[dict], url: str
) -> ProbeResponse:
    """Build a ProbeResponse from WFS detection results."""
    layers = [
        LayerInfo(
            name=layer["name"],
            title=layer.get("title"),
            geometry_type=layer.get("geometry_type"),
            feature_count=layer.get("feature_count"),
            layer_id=layer["name"],
        )
        for layer in enriched_layers
    ]
    return ProbeResponse(
        service_type=wfs_result["service_type"],
        url=url,
        layers=layers,
    )


def _build_arcgis_response(
    arcgis_result: dict,
    enriched_layers: list[dict],
    base_url: str,
    selected_layer_id: int | None = None,
) -> ProbeResponse:
    """Build a ProbeResponse from ArcGIS detection results."""
    layers = [
        LayerInfo(
            name=layer["name"],
            title=layer.get("title"),
            geometry_type=layer.get("geometry_type"),
            feature_count=layer.get("feature_count"),
            layer_type=layer.get("type", "layer"),
            layer_id=layer.get("id"),
            object_id_field=layer.get("object_id_field"),
        )
        for layer in enriched_layers
    ]
    return ProbeResponse(
        service_type=arcgis_result["service_type"],
        url=base_url,
        layers=layers,
        selected_layer_id=selected_layer_id,
    )


async def detect_service_type(
    url: str, client: httpx.AsyncClient, token: str | None = None
) -> ProbeResponse:
    """Detect whether a URL is a WFS or ArcGIS service and return probe results.

    Strategy:
    1. Fast path: URL pattern matching (_looks_like_arcgis / _looks_like_wfs)
    2. Slow path: try both (WFS first per user decision)

    Raises ServiceNotRecognized if neither probe succeeds.
    """
    # Fast path: ArcGIS URL pattern
    if _looks_like_arcgis(url):
        logger.info("URL pattern matches ArcGIS", url=url)
        base_url, layer_id = normalize_arcgis_url(url)
        result = await probe_arcgis_service(base_url, client, token=token)
        if result is not None:
            enriched = await enrich_arcgis_feature_counts(
                base_url, result["layers"], client, token=token
            )
            return _build_arcgis_response(
                result, enriched, base_url, selected_layer_id=layer_id
            )

    # Fast path: WFS URL pattern
    elif _looks_like_wfs(url):
        logger.info("URL pattern matches WFS", url=url)
        result = await probe_wfs(url, client, token=token)
        if result is not None:
            enriched = await enrich_wfs_layers(
                url, result["layers"], client, token=token
            )
            return _build_wfs_response(result, enriched, url)

    # Slow path: try both (WFS first per user decision)
    else:
        logger.info("No URL pattern match, trying both probes", url=url)

        # Try WFS first
        wfs_result = await probe_wfs(url, client, token=token)
        if wfs_result is not None:
            enriched = await enrich_wfs_layers(
                url, wfs_result["layers"], client, token=token
            )
            return _build_wfs_response(wfs_result, enriched, url)

        # Try ArcGIS
        base_url, layer_id = normalize_arcgis_url(url)
        arcgis_result = await probe_arcgis_service(base_url, client, token=token)
        if arcgis_result is not None:
            enriched = await enrich_arcgis_feature_counts(
                base_url, arcgis_result["layers"], client, token=token
            )
            return _build_arcgis_response(
                arcgis_result, enriched, base_url, selected_layer_id=layer_id
            )

    raise ServiceNotRecognized()
