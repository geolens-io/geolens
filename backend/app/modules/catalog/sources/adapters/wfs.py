"""WFS GetCapabilities fetching and parsing with safe XML handling.

# XML safety
# ----------
# All parsing uses `defusedxml.ElementTree`, NOT stdlib `xml.etree`. defusedxml
# blocks the well-known XML attacks (billion laughs, XXE, external entity
# expansion, decompression bombs). Never replace this import — the WFS service
# probe accepts user-supplied URLs, so the response is always untrusted.
#
# Namespace handling
# ------------------
# WFS 1.0, 1.1, and 2.0 each use slightly different XML namespaces and element
# names for FeatureType discovery. The parser walks the tree namespace-agnostic
# (matching by local-name) so the same code path supports all three versions.
#
# Phase 1057 PROBE-05 + D-05 (ogrinfo enrichment dropped from probe phase)
# -------------------------------------------------------------------------
# enrich_wfs_layers() was removed in Phase 1057. The per-layer ogrinfo
# subprocess (Semaphore(5) x N layers x ~3-4s each) was the latency
# bottleneck. Dropping it makes the ≤5s probe target trivially achievable.
#
# geometry_type and feature_count now return None at probe time. When the user
# selects a specific layer, the preview path at preview.py runs ogrinfo for
# that single layer. WFS layers always have kind='vector' (WFS is a vector
# feature service by OGC spec — raster sources use STAC instead).
"""

import asyncio
from dataclasses import replace
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import defusedxml.ElementTree as ET
import httpx
import structlog

from app.core.service_tokens import ServiceCredential, build_credential_header
from app.core.url_redaction import redact_exception_text
from app.platform.probe_bounds import bounded_probe_read
from app.platform.service_endpoints import (
    DEFAULT_CHECK_TIMEOUT,
    WFS_XML_ACCEPT,
    EndpointCheckFailedError,
)

logger = structlog.stdlib.get_logger(__name__)

# What this adapter is, in the vocabulary ``build_credential_header`` reads.
# The probe has no stored ``source_format`` to consult — it is what the probe
# is trying to find out — so the adapter names its own.
WFS_SERVICE_FORMAT = "wfs"


def parse_wfs_capabilities(xml_text: str | bytes) -> tuple[str, list[dict]]:
    """Parse WFS GetCapabilities XML.

    Uses defusedxml for safe parsing (blocks XXE, billion laughs, etc.).
    Handles namespace variations across WFS 1.0, 1.1, and 2.0.

    Returns (version_string, layers_list) where each layer dict has
    keys: name, title, crs.

    fix(#1770 round 41 P1): accepts `bytes` too, since `probe_wfs` now hands
    the bounded read's raw bytes straight through -- `ET.fromstring` honours
    an embedded `<?xml encoding="..."?>` declaration on bytes and would
    otherwise see it fight a decode this function already did.
    """
    root = ET.fromstring(xml_text)

    # Extract WFS version from root element
    version = root.get("version", "unknown")

    layers = []

    # Namespace-agnostic iteration
    for element in root.iter():
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "FeatureType":
            name = None
            title = None
            crs = None

            for child in element:
                child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_tag == "Name":
                    name = child.text
                elif child_tag == "Title":
                    title = child.text
                elif child_tag in ("DefaultCRS", "DefaultSRS", "SRS"):
                    crs = child.text

            if name:
                layers.append(
                    {
                        "name": name,
                        "title": title or name,
                        "crs": crs,
                        # D-09: WFS is a vector feature service by OGC spec.
                        # geometry_type and feature_count are None at probe time
                        # (D-05: ogrinfo enrichment dropped from probe phase).
                        "geometry_type": None,
                        "feature_count": None,
                        "kind": "vector",
                    }
                )

    return version, layers


def build_capabilities_url(url: str) -> str:
    """Build a GetCapabilities URL, preserving existing query params.

    fix(#1770 round 47c): round 47b's `max_num_fields=MAX_QUERY_FIELDS` here
    was wrong -- `_header_auth_probe` (`probe.py`) is not the only caller.
    `origin_probe.py::service_probe_target` calls this for the periodic
    health check (`GET /datasets/{id}/health`, `router_health.py`) with NO
    surrounding `except ValueError` at all, so a `ValueError` past the
    field count reached that route as a bare 500 -- the exact class rounds
    44 and 47 both closed elsewhere, reintroduced by round 47b's own "costs
    nothing to close" reasoning, which checked one caller and assumed the
    rest. `url` here really is the caller's own submitted service URL
    (`SourceCreate`'s schema caps it at 2048 chars, ~350 fields of `a=1&` at
    that length), never a value read out of a THIRD-PARTY response, so
    `# parse_qs: unbounded` is the correct answer, matching
    `preview.py::_encode_url_for_gdal`'s existing exemption for the same
    reason.
    """
    parsed = urlparse(url)
    existing_params = parse_qs(parsed.query)  # parse_qs: unbounded

    # Merge required WFS params (overwrite if present)
    existing_params["service"] = ["WFS"]
    existing_params["request"] = ["GetCapabilities"]

    new_query = urlencode(
        {k: v[0] for k, v in existing_params.items()},
    )
    return urlunparse(parsed._replace(query=new_query))


async def probe_wfs(
    url: str,
    client: httpx.AsyncClient,
    credential: ServiceCredential | None = None,
) -> dict | None:
    """Probe a URL as a WFS service.

    Fetches GetCapabilities and parses the response. Returns a dict with
    service_type and layers on success, or None if not a WFS service.

    fix(#1746): the credential becomes a header HERE rather than arriving as
    one, which is what keeps ``build_credential_header`` the only producer of
    a credential header in the tree. The probe door has already judged the
    inputs, so a ValueError from the builder is unreachable over HTTP and is
    caught for the in-process caller that skipped the door; the message is a
    policy constant and carries no part of the credential.

    fix(#1770 round 41 P1): the whole function runs under
    ``DEFAULT_CHECK_TIMEOUT``, same reasoning as ``probe_ogcapi``.
    """
    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            return await _probe_wfs_within_deadline(url, client, credential)
    except TimeoutError:
        logger.debug("WFS probe: deadline exceeded for %s", url)
        return None


async def _probe_wfs_within_deadline(
    url: str,
    client: httpx.AsyncClient,
    credential: ServiceCredential | None,
) -> dict | None:
    """``probe_wfs``'s body, split out so the deadline wraps all of it."""
    capabilities_url = build_capabilities_url(url)
    request_headers = {}
    if credential is not None:
        # fix(#1746 B2b review r7): a ValueError from the builder propagates
        # rather than becoming "not a WFS service". Whether a credential this
        # transport cannot compose is fatal is the CALLER's decision, because
        # another adapter may claim the same URL and carry the same value a
        # different way -- an ArcGIS token is percent-encoded into a query and
        # is legitimately outside the header charset. Every message the builder
        # raises is a policy constant that names no part of the value.
        pair = build_credential_header(
            replace(credential, service_format=WFS_SERVICE_FORMAT)
        )
        if pair is not None:
            request_headers[pair[0]] = pair[1]

    try:
        # fix(#1770 round 41 P1): bounded read, not a plain `client.get` --
        # see `bounded_probe_read`'s docstring. `EndpointCheckFailedError`
        # joins the two httpx types this already caught, for the same reason
        # round 39's redaction fix applies to all three: whatever the cause,
        # this degrades to "not a WFS service" the same way.
        body, response_headers = await bounded_probe_read(
            client, capabilities_url, headers=request_headers, accept=WFS_XML_ACCEPT
        )
    except (
        httpx.HTTPStatusError,
        httpx.TransportError,
        EndpointCheckFailedError,
    ) as exc:
        # fix(#1770 round 39): this request can carry a credential header (see
        # build_credential_header above); an HTTPStatusError's message quotes
        # the whole request URL, so a reflected credential-shaped query
        # parameter on `capabilities_url` must be redacted before logging.
        logger.debug("WFS probe failed for %s: %s", url, redact_exception_text(exc))
        return None

    # Check Content-Type is XML (not HTML error page)
    content_type = response_headers.get("content-type", "")
    if "text/html" in content_type and "xml" not in content_type:
        return None

    try:
        version, layers = parse_wfs_capabilities(body)
    except ET.ParseError:
        logger.debug("WFS XML parse failed for %s", url)
        return None

    if not layers:
        return None

    return {
        "service_type": f"WFS {version}",
        "layers": layers,
    }
