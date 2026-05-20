"""Service type detection orchestration logic.

Coordinates WFS, OGC API Features, and ArcGIS probing to detect what kind of
service a URL points to and return a unified layer list.

# Phase 1057 PROBE-05 + D-04 + D-05
# -----------------------------------
# D-04 (anti-misdiagnosis): The per-probe short-circuit (each 'if result is not
#   None: return' below) was ALREADY correct before this fix. The real latency
#   bottleneck was enrich_ogcapi_layers and enrich_wfs_layers: per-layer ogrinfo
#   subprocesses gated by Semaphore(5) × N collections × ~3-4s each (~60s for
#   17 pygeoapi collections). The orchestrator structure is preserved unchanged.
#
# D-05 (fix): enrich_ogcapi_layers and enrich_wfs_layers are REMOVED. OGC API
#   and WFS probe results now carry geometry_type=None, feature_count=None, and
#   a backend-classified kind='vector'|'raster' (D-09 / CLASS-07). The preview
#   path at preview.py runs ogrinfo lazily for the single layer the user selects.
#
# ArcGIS enrichment (enrich_arcgis_feature_counts) is NOT dropped — it uses fast
# HTTP returnCountOnly queries, not ogrinfo, so it is not the latency bottleneck.
"""

from urllib.parse import urlparse

import httpx
import structlog

from app.modules.catalog.sources.adapters.arcgis import (
    _looks_like_arcgis,
    enrich_arcgis_feature_counts,
    normalize_arcgis_url,
    probe_arcgis_service,
)
from app.modules.catalog.sources.adapters.ogcapi import probe_ogcapi
from app.modules.catalog.sources.adapters.wfs import probe_wfs
from app.modules.catalog.sources.classify import classify_layer_kind
from app.modules.catalog.sources.schemas import LayerInfo, ProbeResponse

logger = structlog.stdlib.get_logger(__name__)


def _looks_like_wfs(url: str) -> bool:
    """Check if a URL looks like a WFS service."""
    parsed = urlparse(url)
    lower_path = parsed.path.lower()
    lower_query = parsed.query.lower()
    return "/wfs" in lower_path or "service=wfs" in lower_query


class ServiceNotRecognized(Exception):
    """Raised when the URL doesn't match any known service type."""

    def __init__(
        self,
        message: str = "Couldn't detect service type. Supported: WFS, ArcGIS Feature Service, and OGC API Features",
    ):
        super().__init__(message)


def _build_probe_response(
    result: dict, layers: list[dict], url: str
) -> ProbeResponse:
    """Build a ProbeResponse from WFS or OGC API Features detection results.

    After Phase 1057 D-05: layers arrive with geometry_type=None, feature_count=None,
    and a pre-classified kind field (set by the adapter at probe_ogcapi / probe_wfs).
    """
    layer_infos = [
        LayerInfo(
            name=layer["name"],
            title=layer.get("title"),
            geometry_type=layer.get("geometry_type"),
            feature_count=layer.get("feature_count"),
            layer_id=layer["name"],
            kind=layer.get("kind", "vector"),
        )
        for layer in layers
    ]
    return ProbeResponse(
        service_type=result["service_type"],
        url=url,
        layers=layer_infos,
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
            kind=classify_layer_kind(layer, adapter_type="arcgis"),
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
    """Detect whether a URL is a WFS, ArcGIS, or OGC API Features service.

    Strategy:
    1. Fast path: URL pattern matching (_looks_like_arcgis / _looks_like_wfs)
    2. Slow path: OGC API probe first, then WFS, then ArcGIS

    Raises ServiceNotRecognized if no probe succeeds.
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
        # Fast-path failed — fall through to slow path

    # Fast path: WFS URL pattern
    if not _looks_like_arcgis(url) and _looks_like_wfs(url):
        logger.info("URL pattern matches WFS", url=url)
        result = await probe_wfs(url, client, token=token)
        if result is not None:
            # D-05: no enrichment — layers already have geometry_type=None,
            # feature_count=None, kind='vector' from probe_wfs.
            return _build_probe_response(result, result["layers"], url)
        # Fast-path failed — fall through to slow path

    # Slow path: OGC API probe first, then WFS, then ArcGIS
    logger.info("Trying all probes", url=url)

    # Try OGC API Features landing page probe
    ogcapi_result = await probe_ogcapi(url, client, token=token)
    if ogcapi_result is not None:
        # D-05: no enrichment — layers already have geometry_type=None,
        # feature_count=None, kind classified by classify_layer_kind from probe_ogcapi.
        return _build_probe_response(ogcapi_result, ogcapi_result["layers"], url)

    # Try WFS
    wfs_result = await probe_wfs(url, client, token=token)
    if wfs_result is not None:
        # D-05: no enrichment — same as fast-path WFS branch above.
        return _build_probe_response(wfs_result, wfs_result["layers"], url)

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
