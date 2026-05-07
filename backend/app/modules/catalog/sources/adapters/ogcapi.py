"""OGC API -- Features landing page probe and collection enrichment.

Implements the same adapter contract as wfs.py and arcgis.py:
- probe_ogcapi(): fetch landing page, detect conformance, list collections
- enrich_ogcapi_layers(): run ogrinfo per collection to get geometry_type/feature_count

# Safety notes
# ------------
# The user-supplied base URL is SSRF-validated upstream by the probe router.
# Secondary URLs extracted from the JSON response (e.g. /conformance href) are
# re-validated via validate_url_for_ssrf() before fetching to prevent a
# malicious landing page from redirecting to internal addresses.
#
# Bearer tokens are passed only via subprocess env (GDAL_HTTP_HEADERS), never
# logged, matching the WFS auth pattern (T-d1g-03).
#
# Concurrency is limited to Semaphore(5) + 30s per-layer timeout to guard
# against slow OGC API endpoints causing runaway enrichment (T-d1g-04).
"""

import asyncio
import json
import os
from urllib.parse import urljoin

import httpx
import structlog

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

    layers = [
        {
            "name": c["id"],
            "title": c.get("title", c["id"]),
            "crs": None,
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


async def enrich_ogcapi_layers(
    url: str,
    layers: list[dict],
    client: httpx.AsyncClient,
    token: str | None = None,
) -> list[dict]:
    """Enrich OGC API collection layers with geometry type and feature count via ogrinfo.

    Uses asyncio.Semaphore(5) to limit concurrency. On failure for a
    given layer, keeps the layer with geometry_type=None, feature_count=None.
    """
    semaphore = asyncio.Semaphore(5)

    async def _enrich_one(layer: dict) -> dict:
        async with semaphore:
            layer_name = layer["name"]
            try:
                env = None
                if token:
                    env = {
                        **os.environ,
                        "GDAL_HTTP_HEADERS": f"Authorization: Bearer {token}",
                    }
                proc = await asyncio.create_subprocess_exec(
                    "ogrinfo",
                    "-json",
                    "-so",
                    f"OAPIF:{url}",
                    layer_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=30.0
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise

                if proc.returncode != 0:
                    logger.debug(
                        "ogrinfo failed for OGC API layer %s: %s",
                        layer_name,
                        stderr.decode(errors="replace"),
                    )
                    return {**layer, "geometry_type": None, "feature_count": None}

                data = json.loads(stdout.decode())
                ogr_layers = data.get("layers", [])
                if not ogr_layers:
                    return {**layer, "geometry_type": None, "feature_count": None}

                ogr_layer = ogr_layers[0]
                geometry_type = None
                geom_fields = ogr_layer.get("geometryFields", [])
                if geom_fields:
                    geometry_type = geom_fields[0].get("type")

                feature_count = ogr_layer.get("featureCount")

                return {
                    **layer,
                    "geometry_type": geometry_type,
                    "feature_count": feature_count,
                }
            except (asyncio.TimeoutError, OSError, json.JSONDecodeError) as exc:
                logger.debug(
                    "ogrinfo enrichment failed for OGC API layer %s: %s",
                    layer_name,
                    exc,
                )
                return {**layer, "geometry_type": None, "feature_count": None}

    enriched = await asyncio.gather(*[_enrich_one(layer) for layer in layers])
    return list(enriched)
