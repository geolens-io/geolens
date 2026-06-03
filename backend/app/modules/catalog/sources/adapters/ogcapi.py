"""OGC API -- Features landing page probe.

Implements the probe adapter contract shared with wfs.py and arcgis.py:
- probe_ogcapi(): fetch landing page, detect conformance, list collections

# Phase 1057 PROBE-05 + D-05 (ogrinfo enrichment dropped from probe phase)
# -------------------------------------------------------------------------
# enrich_ogcapi_layers() was removed in Phase 1057. The per-layer ogrinfo
# subprocess (Semaphore(5) x N collections x ~3-4s) was the real latency
# bottleneck — not the probe orchestrator logic. Dropping it makes the ≤5s
# probe target trivially achievable.
#
# geometry_type and feature_count now return None for all OGC API layers at
# probe time. When the user selects a specific layer, the preview path at
# backend/app/modules/catalog/sources/preview.py already runs ogrinfo for
# that single layer, supplying concrete geometry type at interaction time.
#
# D-09 kind classification is performed inline at layer-dict construction
# (see classify_layer_kind in classify.py). OGC API Features collections
# default to 'vector' unless explicit raster signals (coverage_format/
# bands/image/* mediaType) are present in the collection JSON.
#
# Safety notes
# ------------
# The user-supplied base URL is SSRF-validated upstream by the probe router.
# Secondary URLs extracted from the JSON response (e.g. /conformance href) are
# re-validated via validate_url_for_ssrf() before fetching to prevent a
# malicious landing page from redirecting to internal addresses.
"""

from urllib.parse import urljoin

import httpx
import structlog

from app.modules.catalog.sources.classify import classify_layer_kind
from app.modules.catalog.sources.security import SSRFError, validate_url_for_ssrf

logger = structlog.stdlib.get_logger(__name__)


async def probe_ogcapi(
    url: str, client: httpx.AsyncClient, token: str | None = None
) -> dict | None:
    """Probe a URL as an OGC API -- Features service.

    Fetches the landing page with Accept: application/json, checks conformance
    via the ``conformsTo`` array or ``/conformance`` link, then fetches
    ``/collections`` to build the layer list.

    Returns a dict with ``service_type`` and ``layers`` on success, or None
    if the URL does not appear to be an OGC API Features service.
    """
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Step 1: Fetch landing page
    try:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        logger.debug(
            "OGC API probe: landing page request failed", url=url, error=str(exc)
        )
        return None

    try:
        data = response.json()
    except Exception as exc:  # broad: httpx response.json() can throw varied parser/decoder errors; degrade to None
        logger.debug(
            "OGC API probe: landing page JSON parse failed", url=url, error=str(exc)
        )
        return None

    if not isinstance(data, dict):
        return None

    # Step 2: Resolve conformsTo — may be at landing page level or at /conformance
    conforms_to: list[str] = data.get("conformsTo", [])
    has_data_link = False

    if not conforms_to:
        links = data.get("links", [])
        has_data_link = any(
            isinstance(lnk, dict) and lnk.get("rel") == "data" for lnk in links
        )
        conformance_link = next(
            (
                lnk
                for lnk in links
                if isinstance(lnk, dict) and lnk.get("rel") == "conformance"
            ),
            None,
        )
        if conformance_link:
            conformance_href = conformance_link.get("href", "")
            if conformance_href:
                abs_href = urljoin(url, conformance_href)
                try:
                    await validate_url_for_ssrf(abs_href)
                    conf_resp = await client.get(abs_href, headers=headers)
                    conf_resp.raise_for_status()
                    conf_data = conf_resp.json()
                    conforms_to = conf_data.get("conformsTo", [])
                except SSRFError:
                    logger.warning(
                        "OGC API probe: conformance link blocked by SSRF check",
                        href=abs_href,
                    )
                except Exception as exc:  # broad: conformance fetch — httpx/JSON parse can throw varied errors; degrade gracefully
                    logger.debug(
                        "OGC API probe: conformance fetch failed",
                        href=abs_href,
                        error=str(exc),
                    )

        if not conforms_to and not has_data_link:
            return None

    # Step 3: Validate OGC API Features conformance
    is_ogc_features = any(
        isinstance(uri, str) and "ogcapi-features" in uri for uri in conforms_to
    )
    if not is_ogc_features and not has_data_link:
        return None

    # Step 4: Fetch /collections
    collections_url = url.rstrip("/") + "/collections"
    try:
        await validate_url_for_ssrf(collections_url)
        col_resp = await client.get(collections_url, headers=headers)
        col_resp.raise_for_status()
        col_data = col_resp.json()
    except SSRFError:
        logger.warning(
            "OGC API probe: collections URL blocked by SSRF check", url=collections_url
        )
        return None
    except Exception as exc:  # broad: collections fetch — httpx/JSON parse can throw varied errors; degrade to None
        logger.debug(
            "OGC API probe: collections fetch failed",
            collections_url=collections_url,
            error=str(exc),
        )
        return None

    collections = col_data.get("collections", [])
    if not isinstance(collections, list):
        return None

    # D-09: classify each collection dict at build time. geometry_type is None
    # (D-05: ogrinfo enrichment dropped from probe phase). Raster signals such
    # as coverage_format/bands/image/* mediaType are detected from the raw
    # collection JSON c — most OGC API Features collections will be 'vector'.
    layers = [
        {
            "name": c["id"],
            "title": c.get("title", c["id"]),
            "crs": None,
            "geometry_type": None,
            "feature_count": None,
            "kind": classify_layer_kind(c, adapter_type="ogcapi"),
        }
        for c in collections
        if isinstance(c, dict) and c.get("id")
    ]

    logger.info(
        "OGC API probe succeeded",
        url=url,
        collection_count=len(layers),
    )
    return {"service_type": "OGC API Features", "layers": layers}
