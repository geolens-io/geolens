"""OGC API -- Features landing page probe.

Implements the probe adapter contract shared with wfs.py and arcgis.py:
probe_ogcapi() fetches the landing page, detects conformance, and lists
collections. geometry_type/feature_count are None at probe time; the
preview path (sources/preview.py) fills them in per-layer on demand.

Safety: the base URL is SSRF-validated upstream by the probe router.
Secondary URLs from the response body (e.g. the /conformance href) are
re-validated via validate_url_for_ssrf() before fetching, since a landing
page could otherwise redirect to an internal address.
"""

import asyncio
import json
from dataclasses import replace
from urllib.parse import urljoin

import httpx
import structlog

from app.core.service_tokens import ServiceCredential, build_credential_header
from app.core.url_redaction import redact_exception_text, redact_url_credentials
from app.modules.catalog.sources.classify import classify_layer_kind
from app.platform.security import SSRFError, same_origin, validate_url_for_ssrf
from app.platform.probe_bounds import bounded_probe_read
from app.platform.service_endpoints import (
    DEFAULT_CHECK_TIMEOUT,
    MAX_SERVICE_HREF_BYTES,
    OGC_JSON_ACCEPT,
    EndpointCheckFailedError,
    bounded_service_url,
)

logger = structlog.stdlib.get_logger(__name__)

# What this adapter is, in the vocabulary ``build_credential_header`` reads.
# The probe has no stored ``source_format`` — it names its own.
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

    fix(#1746): following the link is a fresh request, not a redirect, so
    ``make_safe_client``'s cross-origin hop protection does not apply — a
    landing page pointing its conformance link off-origin is not followed
    with the credential. ``credential_header`` is the name it travels under,
    or None for an anonymous probe.
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

    # fix(#1770): bound `abs_href` before use, not after. It names a
    # document THIS SERVICE chose, so a hostile one could reflect the
    # credential straight into our logs via a crafted query string —
    # `redact_url_credentials` is applied at each log call, never trusted to
    # already be safe. And it must be truncated to `MAX_SERVICE_HREF_BYTES`
    # at the seed: `redact_url_credentials` calls the deliberately-unbounded
    # `parse_qsl`, so an oversized href reaching it from a LOGGING call would
    # pay the cost bounding the fetch path exists to avoid.
    abs_href = conformance_href[:MAX_SERVICE_HREF_BYTES]
    try:
        # fix(#1746): resolution is inside the try — an unclosed IPv6
        # bracket in the href raises during `urljoin` itself, not just on
        # later attribute access, so the whole answer must degrade together.
        # fix(#1770): refused before `urljoin`, like every other
        # service-advertised href; the broad `except Exception` below
        # already covers a `ValueError` from either call.
        abs_href = urljoin(
            url, bounded_service_url(conformance_href, what="conformance")
        )
        # fix(#1746): cross-origin, not followed at all — not even
        # anonymously. An anonymous answer about a credentialed service is
        # evidence for a different request than the one the import will
        # make. Conformance stays unestablished; the `data` link decides.
        if credential_header is not None and not same_origin(url, abs_href):
            logger.warning(
                "OGC API probe: conformance link is on another origin, "
                "not following it with a credential",
                href=redact_url_credentials(abs_href),
            )
            return conforms_to, has_data_link
        await validate_url_for_ssrf(abs_href)
        # The href comes out of an untrusted landing page, revalidated above
        # rather than trusted because the base URL was.
        #
        # fix(#1770): no CodeQL suppression marker belongs on this line —
        # the actual sink is the `stream` call inside `bounded_probe_read`
        # (`platform/probe_bounds.py`), one hop away from here.
        conf_body, _ = await bounded_probe_read(
            client, abs_href, headers=headers, accept=OGC_JSON_ACCEPT
        )
        conf_data = json.loads(conf_body)
        conforms_to = conf_data.get("conformsTo", [])
    except SSRFError:
        # fix(#1858): swallowed ON PURPOSE, unlike the `/collections` fetch
        # below — this read establishes one optional fact, and ending the
        # probe here would let a service make itself undetectable by
        # advertising a blocked conformance href.
        logger.warning(
            "OGC API probe: conformance link blocked by SSRF check",
            href=redact_url_credentials(abs_href),
        )
    # fix(#1770): `EndpointCheckFailedError` (over-cap body/size, or a
    # non-identity Content-Encoding) degrades the same as an httpx/JSON
    # failure here — conformance stays unestablished.
    except Exception as exc:  # broad: conformance fetch — httpx/JSON/bound failures can throw varied errors; degrade gracefully
        logger.debug(
            "OGC API probe: conformance fetch failed",
            href=redact_url_credentials(abs_href),
            error=redact_exception_text(exc),
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

    Returns a dict with ``service_type`` and ``layers``, or None if the URL
    does not look like an OGC API Features service.

    fix(#1746): the credential becomes a header HERE, keeping
    ``build_credential_header`` the tree's only producer of one. A
    ValueError from the builder is unreachable over HTTP (the probe door
    already judged the inputs) and is caught here for the in-process caller
    that skipped it.

    fix(#1770): the whole function runs under ``DEFAULT_CHECK_TIMEOUT`` —
    without its own bound, a protected service the caller already holds a
    credential for could trickle a response for as long as the client's
    per-inactivity timeout tolerated, once per probe.
    """
    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            return await _probe_ogcapi_within_deadline(url, client, credential)
    except TimeoutError:
        logger.debug("OGC API probe: deadline exceeded", url=url)
        return None


async def _probe_ogcapi_within_deadline(
    url: str,
    client: httpx.AsyncClient,
    credential: ServiceCredential | None,
) -> dict | None:
    headers: dict[str, str] = {"Accept": "application/json"}
    # Bound before the branch, because the conformance fetch below has to know
    # whether this request carries a credential and under what name.
    pair: tuple[str, str] | None = None
    if credential is not None:
        # fix(#1746): ValueError propagates — see probe_wfs for why the
        # caller, not the adapter, decides what an uncomposable credential
        # means.
        pair = build_credential_header(
            replace(credential, service_format=OGCAPI_SERVICE_FORMAT)
        )
        if pair is not None:
            headers[pair[0]] = pair[1]

    try:
        body, _ = await bounded_probe_read(
            client, url, headers=headers, accept=OGC_JSON_ACCEPT
        )
    except (
        httpx.HTTPStatusError,
        httpx.TransportError,
        EndpointCheckFailedError,
    ) as exc:
        logger.debug(
            "OGC API probe: landing page request failed",
            url=url,
            error=redact_exception_text(exc),
        )
        return None

    try:
        data = json.loads(body)
    except (
        Exception
    ) as exc:  # broad: json.loads can throw varied decoder errors; degrade to None
        logger.debug(
            "OGC API probe: landing page JSON parse failed",
            url=url,
            error=redact_exception_text(exc),
        )
        return None

    if not isinstance(data, dict):
        return None

    # conformsTo may be at landing page level or via the /conformance link.
    conforms_to, has_data_link = await _resolve_conformance(
        url,
        client,
        headers,
        data,
        credential_header=None if pair is None else pair[0],
    )
    if not conforms_to and not has_data_link:
        return None

    is_ogc_features = any(
        isinstance(uri, str) and "ogcapi-features" in uri for uri in conforms_to
    )
    if not is_ogc_features and not has_data_link:
        return None

    collections_url = url.rstrip("/") + "/collections"
    try:
        await validate_url_for_ssrf(collections_url)
        col_body, _ = await bounded_probe_read(
            client, collections_url, headers=headers, accept=OGC_JSON_ACCEPT
        )
        col_data = json.loads(col_body)
    except SSRFError:
        # fix(#1858): re-raised, not degraded — this clause ENDS the
        # adapter either way, so swallowing it would cost the door its only
        # truthful answer. Rule: a read whose failure means "one optional
        # fact is unknown" degrades; a read whose failure ends the adapter
        # raises (see the arcgis.py/`_resolve_conformance` degrade clauses).
        logger.warning(
            "OGC API probe: collections URL blocked by SSRF check", url=collections_url
        )
        raise
    except Exception as exc:  # broad: collections fetch — httpx/JSON/bound failures can throw varied errors; degrade to None
        logger.debug(
            "OGC API probe: collections fetch failed",
            collections_url=collections_url,
            error=redact_exception_text(exc),
        )
        return None

    # fix(#1770): a non-dict `/collections` response (e.g. `200 []`) makes
    # `.get(...)` raise `AttributeError`, uncaught by `_header_auth_probe`
    # or the probe route, reaching the caller as a bare 500 instead of the
    # ordinary degrade.
    if not isinstance(col_data, dict):
        return None
    collections = col_data.get("collections", [])
    if not isinstance(collections, list):
        return None

    # geometry_type is None here (probe phase skips ogrinfo enrichment).
    # Raster signals (coverage_format/bands/image/* mediaType) are read from
    # the raw collection JSON; most OGC API Features collections are 'vector'.
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
