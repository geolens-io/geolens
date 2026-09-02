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

from dataclasses import replace
from urllib.parse import urljoin

import httpx
import structlog

from app.core.service_tokens import ServiceCredential, build_credential_header
from app.modules.catalog.sources.classify import classify_layer_kind
from app.platform.security import SSRFError, same_origin, validate_url_for_ssrf

logger = structlog.stdlib.get_logger(__name__)

# What this adapter is, in the vocabulary ``build_credential_header`` reads.
# The probe has no stored ``source_format`` to consult — it is what the probe
# is trying to find out — so the adapter names its own.
OGCAPI_SERVICE_FORMAT = "ogcapi_features"


async def _resolve_conformance(
    url: str,
    client: httpx.AsyncClient,
    headers: dict[str, str],
    data: dict,
    *,
    credential_header: str | None,
) -> tuple[list[str], bool]:
    """The landing page's conformance classes, and whether it advertises data.

    Reads ``conformsTo`` from the landing page, and where that is absent
    follows the ``conformance`` link, re-validating the resolved href against
    SSRF first because it comes out of an untrusted document. Every failure
    degrades to what was known before it, so a service that answers the
    landing page and nothing else is still classified by its ``data`` link.

    fix(#1746): extracted from ``probe_ogcapi`` unchanged. The credential
    branch added there pushed that function past ruff's C901 ceiling, and
    extraction is what this repo does about that rather than another
    exemption.

    fix(#1746 B2b review r5): the link is chosen by the RESPONSE DOCUMENT, and
    following it is a fresh request rather than a redirect, so nothing httpx
    does protects it: the cross-origin refusal in ``make_safe_client`` runs on
    a hop, and there is no hop here. A landing page that omits ``conformsTo``
    and points its conformance link at another origin would therefore have
    been handed the credential built for the service. It is not followed with
    one. ``credential_header`` is the name the credential travels under, or
    None for an anonymous probe, which is the only thing that distinguishes
    the two cases from in here.
    """
    conforms_to: list[str] = data.get("conformsTo", [])
    if conforms_to:
        return conforms_to, False

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
    if not conformance_link:
        return conforms_to, has_data_link
    conformance_href = conformance_link.get("href", "")
    if not conformance_href:
        return conforms_to, has_data_link

    abs_href = urljoin(url, conformance_href)
    try:
        # The same rule the redirect refusal applies, for a link the document
        # chose rather than a Location header. Not followed at all rather than
        # followed anonymously: an anonymous answer about a service the caller
        # holds a credential for is evidence about a different request than the
        # one the import will make, which is the disagreement class this wave
        # exists to end (plan D6). Conformance stays unestablished and the
        # `data` link decides, exactly as it does for a landing page that
        # advertises no conformance link at all.
        #
        # fix(#1746 B2b review r6): inside the guarded block. `same_origin` is
        # total on its own, and this is the second half of the same answer:
        # everything done with a URL this document chose degrades to "no
        # conformance" rather than escaping as a 500.
        if credential_header is not None and not same_origin(url, abs_href):
            logger.warning(
                "OGC API probe: conformance link is on another origin, "
                "not following it with a credential",
                href=abs_href,
            )
            return conforms_to, has_data_link
        await validate_url_for_ssrf(abs_href)
        # The href comes out of an untrusted landing page, so it is revalidated
        # on the line above rather than trusted because the base URL was.
        #
        # The marker below must stay the LAST line before the call: the
        # suppression query binds a marker to the line that follows it, so an
        # explanatory comment inserted between the two silently disarms it.
        # Prose goes above.
        # codeql[py/full-ssrf] fix(#1746): Rule 2 posture — validate_url_for_ssrf gates the resolved href immediately above, and this client comes from make_safe_client, whose transport re-resolves, validates and pins the IP at connect time and revalidates every redirect hop
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
    return conforms_to, has_data_link


async def probe_ogcapi(
    url: str,
    client: httpx.AsyncClient,
    credential: ServiceCredential | None = None,
) -> dict | None:
    """Probe a URL as an OGC API -- Features service.

    Fetches the landing page with Accept: application/json, checks conformance
    via the ``conformsTo`` array or ``/conformance`` link, then fetches
    ``/collections`` to build the layer list.

    Returns a dict with ``service_type`` and ``layers`` on success, or None
    if the URL does not appear to be an OGC API Features service.

    fix(#1746): the credential becomes a header HERE rather than arriving as
    one, which is what keeps ``build_credential_header`` the only producer of
    a credential header in the tree. The probe door has already judged the
    inputs, so a ValueError from the builder is unreachable over HTTP and is
    caught for the in-process caller that skipped the door; the message is a
    policy constant and carries no part of the credential.
    """
    headers: dict[str, str] = {"Accept": "application/json"}
    # Bound before the branch, because the conformance fetch below has to know
    # whether this request carries a credential and under what name.
    pair: tuple[str, str] | None = None
    if credential is not None:
        # fix(#1746 B2b review r7): the ValueError propagates. See probe_wfs
        # for why the caller and not the adapter decides what an uncomposable
        # credential means.
        pair = build_credential_header(
            replace(credential, service_format=OGCAPI_SERVICE_FORMAT)
        )
        if pair is not None:
            headers[pair[0]] = pair[1]

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
    conforms_to, has_data_link = await _resolve_conformance(
        url,
        client,
        headers,
        data,
        credential_header=None if pair is None else pair[0],
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
