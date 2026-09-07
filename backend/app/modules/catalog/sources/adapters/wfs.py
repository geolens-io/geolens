"""WFS GetCapabilities fetching and parsing with safe XML handling.

All parsing uses ``defusedxml.ElementTree``, not stdlib ``xml.etree`` —
never replace this import. defusedxml blocks XXE, billion laughs, and
decompression-bomb attacks; the WFS probe accepts user-supplied URLs, so
the response is always untrusted.

WFS 1.0/1.1/2.0 use different namespaces and element names for
FeatureType discovery; the parser walks the tree namespace-agnostic
(matching by local name) to support all three with one code path.

geometry_type/feature_count are None at probe time (the preview path
fills them in per layer). WFS layers are always kind='vector' — WFS is a
vector feature service by OGC spec; raster sources use STAC instead.
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
# The probe has no stored ``source_format`` — it names its own.
WFS_SERVICE_FORMAT = "wfs"


def parse_wfs_capabilities(xml_text: str | bytes) -> tuple[str, list[dict]]:
    """Parse WFS GetCapabilities XML.

    Uses defusedxml for safe parsing (blocks XXE, billion laughs, etc.).
    Handles namespace variations across WFS 1.0, 1.1, and 2.0.

    Returns (version_string, layers_list); each layer dict has keys: name,
    title, crs.

    fix(#1770): accepts `bytes` too — `ET.fromstring` honours an embedded
    `<?xml encoding="..."?>` declaration on bytes, avoiding a fight with a
    decode this function already did.
    """
    root = ET.fromstring(xml_text)
    version = root.get("version", "unknown")

    layers = []

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
                        "geometry_type": None,
                        "feature_count": None,
                        "kind": "vector",
                    }
                )

    return version, layers


def build_capabilities_url(url: str) -> str:
    """Build a GetCapabilities URL, preserving existing query params.

    fix(#1770): every caller reaches this with `url` capped upstream, never
    a value read from a third-party response — the periodic health check
    passes `origin_ref["url"]`, JSONB persisted from a probe/preview
    submission already capped at 2048 chars (~350 fields of `a=1&`). That is
    what makes `# parse_qs: unbounded` correct here, matching
    `preview.py::_encode_url_for_gdal`'s exemption for the same reason — a
    `max_num_fields` bound was tried once and wrongly assumed
    `_header_auth_probe` was the only caller, letting a `ValueError` reach
    the health-check route as a bare 500.
    """
    parsed = urlparse(url)
    existing_params = parse_qs(parsed.query)  # parse_qs: unbounded

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
    service_type and layers, or None if not a WFS service.

    fix(#1746): the credential becomes a header HERE, keeping
    ``build_credential_header`` the tree's only producer of one. A
    ValueError from the builder is unreachable over HTTP (the probe door
    already judged the inputs) and is caught here for the in-process caller
    that skipped it.

    fix(#1770): the whole function runs under ``DEFAULT_CHECK_TIMEOUT``,
    same reasoning as ``probe_ogcapi``.
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
    capabilities_url = build_capabilities_url(url)
    request_headers = {}
    if credential is not None:
        # fix(#1746): a ValueError from the builder propagates rather than
        # becoming "not a WFS service" — another adapter may claim the same
        # URL and carry the value a different way (e.g. an ArcGIS token,
        # percent-encoded into a query, legitimately outside the header
        # charset), so whether it's fatal is the CALLER's decision.
        pair = build_credential_header(
            replace(credential, service_format=WFS_SERVICE_FORMAT)
        )
        if pair is not None:
            request_headers[pair[0]] = pair[1]

    try:
        # fix(#1770): bounded read; `EndpointCheckFailedError` joins the
        # two httpx types already caught — whatever the cause, this
        # degrades to "not a WFS service" the same way.
        body, response_headers = await bounded_probe_read(
            client, capabilities_url, headers=request_headers, accept=WFS_XML_ACCEPT
        )
    except (
        httpx.HTTPStatusError,
        httpx.TransportError,
        EndpointCheckFailedError,
    ) as exc:
        # fix(#1770): this request can carry a credential header; the
        # exception text quotes the full request URL, so it must be
        # redacted before logging.
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
