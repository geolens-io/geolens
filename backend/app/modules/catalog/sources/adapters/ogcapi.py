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

    # Bound before the guard so the two log sites below always have something
    # to name: the resolved form when there is one, the raw href when
    # resolution is what failed. Never logged verbatim (fix(#1770 round 38
    # P2)): `abs_href` names a document THIS SERVICE chose, so a hostile or
    # compromised one can put a query string shaped like ours into it and get
    # the credential this function is about to send reflected straight into
    # our own logs -- the exact leak the GDAL-header-file design exists to
    # avoid elsewhere. `redact_url_credentials` is applied at each log call
    # below, never to `abs_href` itself: the unredacted value is what
    # `same_origin`, `validate_url_for_ssrf` and the actual GET must keep
    # using.
    #
    # fix(#1770 round 47b P1): truncated to `MAX_SERVICE_HREF_BYTES`
    # characters at the seed, not the full raw href. `bounded_service_url`
    # below can now fail BECAUSE `conformance_href` is huge (the round 47 P1
    # class), and this variable is what every log/exception site below
    # passes to `redact_url_credentials`, which itself calls the unbounded
    # `parse_qsl` this codebase deliberately keeps unbounded (a redactor must
    # never raise on the string it scrubs -- see that function's own
    # comment). A 20 MB query string reaching an unbounded `parse_qsl` from
    # a LOGGING call defeats the whole point of bounding the fetch path: the
    # cost this round exists to refuse would be paid anyway, on every
    # refused attempt, from a code path with no request in flight to time
    # out. Truncating here makes `abs_href` safe to redact/log at every
    # point in this function BY CONSTRUCTION, rather than trusting each
    # call site to shrink it again -- the same reasoning as `# broad:`
    # annotations existing at the catch site rather than being inferred.
    abs_href = conformance_href[:MAX_SERVICE_HREF_BYTES]
    try:
        # fix(#1746 B2b review r19): resolution itself is inside the guard now.
        # r6 moved the `same_origin` call in and left the `urljoin` outside,
        # which was enough for the invalid-port case it was reasoning about
        # (`urlparse` defers that until the attribute is read) but not for an
        # unclosed IPv6 bracket, which raises during resolution. The whole
        # answer degrades together or none of it does.
        # fix(#1770 round 47 P1): refused before `urljoin`, same as every
        # other service-advertised href -- see `bounded_service_url`'s own
        # docstring. The broad `except Exception` below already degrades a
        # `ValueError` from this the same way it degrades one from
        # `urljoin` itself, so no new except clause is needed here.
        abs_href = urljoin(
            url, bounded_service_url(conformance_href, what="conformance")
        )
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
                href=redact_url_credentials(abs_href),
            )
            return conforms_to, has_data_link
        await validate_url_for_ssrf(abs_href)
        # The href comes out of an untrusted landing page, so it is revalidated
        # on the line above rather than trusted because the base URL was.
        #
        # fix(#1770 round 43): this line used to carry a CodeQL full-SSRF
        # suppression marker, from when the line below was a direct
        # `client.get`/`client.stream` call and this was genuinely the sink.
        # Round 41 moved the actual sink into `bounded_probe_read`
        # (`platform/probe_bounds.py`), so a marker here bound to a call
        # site one hop away from the sink -- exactly the trap AGENTS.md
        # warns about, a marker that reads as a defense and does nothing.
        # The real marker now lives directly above the `stream` call in
        # `probe_bounds.py`; the `validate_url_for_ssrf` call above is still
        # real Rule 2 posture, just no longer this function's suppression
        # to carry.
        conf_body, _ = await bounded_probe_read(
            client, abs_href, headers=headers, accept=OGC_JSON_ACCEPT
        )
        conf_data = json.loads(conf_body)
        conforms_to = conf_data.get("conformsTo", [])
    except SSRFError:
        logger.warning(
            "OGC API probe: conformance link blocked by SSRF check",
            href=redact_url_credentials(abs_href),
        )
    # fix(#1770 round 41 P1): EndpointCheckFailedError joins the broad catch
    # below -- it is what `bounded_probe_read` raises for a body over the
    # byte cap, over the decoded-size cap, or carrying a Content-Encoding
    # other than identity, and this fetch degrades all three exactly like an
    # httpx/JSON failure: conformance stays unestablished, the `data` link
    # decides.
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

    Returns a dict with ``service_type`` and ``layers`` on success, or None
    if the URL does not appear to be an OGC API Features service.

    fix(#1746): the credential becomes a header HERE rather than arriving as
    one, which is what keeps ``build_credential_header`` the only producer of
    a credential header in the tree. The probe door has already judged the
    inputs, so a ValueError from the builder is unreachable over HTTP and is
    caught for the in-process caller that skipped the door; the message is a
    policy constant and carries no part of the credential.

    fix(#1770 round 41 P1): the whole function runs under
    ``DEFAULT_CHECK_TIMEOUT`` -- the same clock ``assert_endpoints_stay_on_
    origin`` runs its own reads under, reused rather than a new number
    invented here. That check only runs AFTER this one returns, so without
    its own bound a protected service a caller already holds a credential for
    could otherwise trickle a response for as long as the client's own
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
    """``probe_ogcapi``'s body, split out so the deadline wraps all of it."""
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
        col_body, _ = await bounded_probe_read(
            client, collections_url, headers=headers, accept=OGC_JSON_ACCEPT
        )
        col_data = json.loads(col_body)
    except SSRFError:
        logger.warning(
            "OGC API probe: collections URL blocked by SSRF check", url=collections_url
        )
        return None
    except Exception as exc:  # broad: collections fetch — httpx/JSON/bound failures can throw varied errors; degrade to None
        logger.debug(
            "OGC API probe: collections fetch failed",
            collections_url=collections_url,
            error=redact_exception_text(exc),
        )
        return None

    # fix(#1770 round 44 P2): a credentialed `/collections` answering `200
    # []`, `200 null`, or `200 "x"` is valid JSON but not a dict, and
    # `.get(...)` on a list/None/str raises `AttributeError` -- uncaught by
    # `_header_auth_probe` (`probe.py`, `ValueError` only) or the probe
    # route, so it reached the caller as a bare 500 rather than the
    # `ServiceNotRecognized`/`None` degrade every other unrecognised
    # response gets.
    if not isinstance(col_data, dict):
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
