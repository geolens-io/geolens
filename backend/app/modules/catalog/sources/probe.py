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

from app.core.service_tokens import ServiceCredential
from app.platform.service_auth import url_query_token
from app.core.url_redaction import redact_url_credentials
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


class ServiceCredentialUnusable(Exception):
    """A header-auth adapter could not compose the credential it was given.

    fix(#1746 B2b review r7): raised only after every adapter has had its turn,
    which is the whole point of it. The probe is what DETERMINES the service
    type, so a credential policy chosen from the URL alone gets it wrong for
    the services this function exists to find: ``probe_arcgis_service``
    classifies an endpoint that names neither FeatureServer nor MapServer by
    what its response contains, and an ArcGIS token is percent-encoded into a
    query, so it legitimately holds characters the header charset refuses.
    Refusing such a token up front rejected a working ArcGIS import.

    So a token an adapter cannot turn into a header stops THAT adapter and
    nothing else. If another one claims the URL, the probe succeeds and the
    token was fine. If none does, this carries the policy the caller needs to
    read, which is better advice than "service not recognized" for a URL whose
    only problem was the credential.
    """

    def __init__(self, policy: str):
        self.policy = policy
        super().__init__(policy)


class ServiceNotRecognized(Exception):
    """Raised when the URL doesn't match any known service type."""

    def __init__(
        self,
        message: str = "Couldn't detect service type. Supported: WFS, ArcGIS Feature Service, and OGC API Features",
    ):
        super().__init__(message)


def _build_probe_response(result: dict, layers: list[dict], url: str) -> ProbeResponse:
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
    url: str,
    client: httpx.AsyncClient,
    credential: ServiceCredential | None = None,
) -> ProbeResponse:
    """Detect whether a URL is a WFS, ArcGIS, or OGC API Features service.

    Strategy:
    1. Fast path: URL pattern matching (_looks_like_arcgis / _looks_like_wfs)
    2. Slow path: OGC API probe first, then WFS, then ArcGIS

    Raises ServiceNotRecognized if no probe succeeds.

    fix(#1746): one credential reaches all three adapters, and each presents
    it the way its own service takes one. The two header-auth adapters compose
    a header from it; the ArcGIS branch takes the bare token and nothing else.
    """
    # fix(#1746) plan D9: an ArcGIS credential is percent-encoded into a URL
    # query, so a bearer token is the only method that fits. The probe door
    # refuses the other two for an ArcGIS-shaped URL; on this fallback path,
    # where the URL said nothing, they simply cannot be presented and the
    # origin's 401 is the honest answer.
    token = url_query_token(credential)
    looks_arcgis = _looks_like_arcgis(url)
    looks_wfs = _looks_like_wfs(url)

    # fix(#1746 B2b review r7): a credential the header-auth transports cannot
    # compose ends those probes and no others. Recorded rather than raised, so
    # the ArcGIS branch below still gets its turn with the same value carried
    # the way that transport carries one.
    refusals: list[str] = []

    async def _header_auth_probe(probe) -> dict | None:
        try:
            return await probe(url, client, credential=credential)
        except ValueError as exc:
            refusals.append(str(exc))
            logger.debug(
                "probe adapter refused the credential",
                adapter=probe.__name__,
                reason=str(exc),
            )
            return None

    # Fast path: ArcGIS URL pattern
    if looks_arcgis:
        logger.info(
            "URL pattern matches ArcGIS", url=redact_url_credentials(url)
        )  # fix(#430 BA-27)
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
    if not looks_arcgis and looks_wfs:
        logger.info(
            "URL pattern matches WFS", url=redact_url_credentials(url)
        )  # fix(#430 BA-27)
        result = await _header_auth_probe(probe_wfs)
        if result is not None:
            # D-05: no enrichment — layers already have geometry_type=None,
            # feature_count=None, kind='vector' from probe_wfs.
            return _build_probe_response(result, result["layers"], url)
        # Fast-path failed — fall through to slow path

    # Slow path: OGC API probe first, then WFS, then ArcGIS
    logger.info("Trying all probes", url=redact_url_credentials(url))  # fix(#430 BA-27)

    # Try OGC API Features landing page probe
    ogcapi_result = await _header_auth_probe(probe_ogcapi)
    if ogcapi_result is not None:
        # D-05: no enrichment — layers already have geometry_type=None,
        # feature_count=None, kind classified by classify_layer_kind from probe_ogcapi.
        return _build_probe_response(ogcapi_result, ogcapi_result["layers"], url)

    # Try WFS
    wfs_result = await _header_auth_probe(probe_wfs)
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

    if refusals:
        # Nothing claimed this URL, and a header-auth adapter never got to ask
        # because the credential could not become a header. That policy is the
        # actionable half of the answer, so it is what the caller gets.
        raise ServiceCredentialUnusable(refusals[0])

    raise ServiceNotRecognized()
