"""ArcGIS REST API probing, URL normalization, and service type detection."""

import asyncio
import json
import re
from collections.abc import Callable
from urllib.parse import quote, urlencode, urlparse

import httpx
import structlog

from app.core.service_tokens import (
    ARCGIS_SERVICE_FORMAT,
    HEADER_TOKEN_MIN_LENGTH,
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
    credential_input_rejection_reason,
    register_credential_secret,
)
from app.core.url_redaction import redact_exception_text
from app.platform.probe_bounds import bounded_probe_read
from app.platform.security import SSRFError, same_origin
from app.platform.service_endpoints import (
    DEFAULT_CHECK_TIMEOUT,
    OGC_JSON_ACCEPT,
    EndpointCheckFailedError,
)

logger = structlog.stdlib.get_logger(__name__)

# feat(C2): ARCGIS_SERVICE_FORMAT is re-exported from core/service_tokens.py;
# core/ may not import app.modules.*.
__all__ = [
    "ARCGIS_SERVICE_FORMAT",
    "ArcGISTokenError",
    "arcgis_accepts_header_token",
    "arcgis_request_auth",
    "build_arcgis_count_query_url",
    "enrich_arcgis_feature_counts",
    "fetch_arcgis_feature_count",
    "fetch_arcgis_layer_preview",
    "fetch_arcgis_pagination_info",
    "normalize_arcgis_url",
    "parse_arcgis_current_version",
    "probe_arcgis_service",
]

# feat(C2): ArcGIS Server accepts a bearer token via header only at 10.5.1+;
# older servers need the query-token fallback.
ARCGIS_HEADER_TOKEN_MIN_VERSION = (10, 5, 1)

# ArcGIS reports auth refusal as an error envelope in an HTTP 200 body: 499
# "Token Required" (no header token seen) triggers the query-form retry; 498
# means the token WAS read and rejected, so retrying would just resend it.
_ARCGIS_TOKEN_REQUIRED_CODE = 499
_ARCGIS_TOKEN_ERROR_CODES = frozenset({498, _ARCGIS_TOKEN_REQUIRED_CODE})


class ArcGISTokenError(Exception):
    """Raised when ArcGIS returns a token-related error (codes 498, 499)."""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"ArcGIS token error ({code}): {message}")


_ESRI_GEOM_TYPE_MAP = {
    "esriGeometryPoint": "Point",
    "esriGeometryMultipoint": "MultiPoint",
    "esriGeometryPolyline": "LineString",
    "esriGeometryPolygon": "Polygon",
    "esriGeometryEnvelope": "Envelope",
}


# Matches the OGR field-type strings ogrinfo -json emits for the WFS/OGC
# path, so downstream preview code sees one vocabulary. Unknown -> "String".
_ESRI_FIELD_TYPE_MAP = {
    "esriFieldTypeOID": "Integer64",
    "esriFieldTypeInteger": "Integer",
    "esriFieldTypeSmallInteger": "Integer",
    "esriFieldTypeBigInteger": "Integer64",
    "esriFieldTypeDouble": "Real",
    "esriFieldTypeSingle": "Real",
    "esriFieldTypeString": "String",
    "esriFieldTypeDate": "DateTime",
    "esriFieldTypeGUID": "String",
    "esriFieldTypeGlobalID": "String",
}


def _normalize_esri_field_type(esri_type: str | None) -> str:
    if not esri_type:
        return "String"
    return _ESRI_FIELD_TYPE_MAP.get(esri_type, "String")


def _normalize_esri_geom_type(esri_type: str | None) -> str | None:
    """Convert esriGeometryPoint -> Point, etc.

    Returns the original value if not found in the mapping.
    """
    if not esri_type:
        return None
    return _ESRI_GEOM_TYPE_MAP.get(esri_type, esri_type)


def _extract_arcgis_object_id_field(data: dict) -> str | None:
    value = data.get("objectIdField")
    if isinstance(value, str) and value.strip():
        return value.strip()

    fields = data.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if not isinstance(field, dict):
                continue
            if field.get("type") != "esriFieldTypeOID":
                continue
            name = field.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()

    unique_id_field = data.get("uniqueIdField")
    if isinstance(unique_id_field, dict):
        name = unique_id_field.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()

    return None


def _looks_like_arcgis(url: str) -> bool:
    lower = url.lower()
    return "featureserver" in lower or "mapserver" in lower


def normalize_arcgis_url(url: str) -> tuple[str, int | None]:
    """Normalize an ArcGIS URL to a canonical service root form.

    Strips query, trailing slash, /query suffix; extracts a trailing layer id.
    Returns (normalized_base_url, optional_layer_id).
    """
    parsed = urlparse(url)
    clean_url = parsed._replace(query="", fragment="").geturl()
    clean_url = clean_url.rstrip("/")

    if clean_url.lower().endswith("/query"):
        clean_url = clean_url[: -len("/query")]
        clean_url = clean_url.rstrip("/")

    layer_id = None
    match = re.search(r"/(FeatureServer|MapServer)/(\d+)$", clean_url, re.IGNORECASE)
    if match:
        layer_id = int(match.group(2))
        clean_url = clean_url[: match.start() + 1 + len(match.group(1))]

    return clean_url, layer_id


def parse_arcgis_current_version(value: object) -> tuple[int, int, int] | None:
    """Parse an ArcGIS ``currentVersion`` into a comparable triple.

    feat(C2): Esri encodes a patch release as a second fractional digit, not
    semver: 10.5.1 is reported as ``10.51``, 10.4.1 as ``10.41``, 10.5 as
    ``10.5``. Reading these as floats misorders ``10.51``/``10.5``/``10.41``.
    Dotted three-part strings ("10.5.1") are read literally, matching Esri's
    own docs.

    Returns ``None`` for anything unparseable (including ``None`` itself);
    every caller treats that as "version unknown". A hypothetical ``x.10``
    would read as ``x.1.0``; Esri has shipped no such version, and every
    comparison here is against 10.5.1, where both readings agree above 11.x.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"\d+(\.\d+)*", text):
        return None
    parts = text.split(".")
    major = int(parts[0])
    if len(parts) == 1:
        return (major, 0, 0)
    if len(parts) >= 3:
        return (major, int(parts[1]), int(parts[2]))
    fraction = parts[1]
    if len(fraction) == 2:
        return (major, int(fraction[0]), int(fraction[1]))
    return (major, int(fraction), 0)


def arcgis_accepts_header_token(current_version: object = None) -> bool:
    """Whether this service reads a token from the Authorization header.

    feat(C2): true unless the version is older than 10.5.1. An unknown or
    unparseable version is treated as new enough — the only servers that
    can't read the header predate 2017 and always report a version, while
    hosted ArcGIS Online reports 11.x. A wrong guess here costs one retry
    (the 499 fallback below); the other direction would put the token back
    in the URL for everyone.
    """
    parsed = parse_arcgis_current_version(current_version)
    return parsed is None or parsed >= ARCGIS_HEADER_TOKEN_MIN_VERSION


def _arcgis_error_code(data: object) -> int | None:
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, int) else None


def _query_form_credential(token: str) -> tuple[dict[str, str], str | None]:
    """The pre-10.5.1 fallback: no headers, the bare token for the query.

    fix(#1840): registers the token for exact-value log scrubbing before it
    goes into a URL, gated by the same length/charset floor the header
    transport uses — unregistered, a short value would scrub as a substring
    of ordinary log text (e.g. registering "json" rewrote
    ``https://json.example.com`` to ``https://***.example.com``). The
    credential still reaches the origin either way; only the log-scrub
    registration is gated.
    """
    if (
        credential_input_rejection_reason(token) is None
        and len(token) >= HEADER_TOKEN_MIN_LENGTH
    ):
        register_credential_secret(token)
    return {}, token


def arcgis_request_auth(
    token: str | None, *, current_version: object = None
) -> tuple[dict[str, str], str | None]:
    """How one ArcGIS request presents *token*: headers, and a query token.

    feat(C2): exactly one half is ever populated. The header form is the
    default and the query form is the fallback for ArcGIS Server older than
    10.5.1; ``build_credential_header`` composes the header, so this adapter
    is not a second producer of one (see
    ``tests/test_credential_producer_structural.py``). A token the builder
    refuses (whitespace or non-ASCII, which no ArcGIS token has) degrades to
    the query form rather than failing the read. The refused value is never
    logged: it is a credential.
    """
    if not token:
        return {}, None
    if not arcgis_accepts_header_token(current_version):
        return _query_form_credential(token)
    try:
        pair = build_credential_header(
            ServiceCredential(
                method=CredentialMethod.BEARER,
                service_format=ARCGIS_SERVICE_FORMAT,
                token=token,
            )
        )
    except ValueError:
        return _query_form_credential(token)
    if pair is None:
        return _query_form_credential(token)
    return {pair[0]: pair[1]}, None


# fix(#1840): statuses a web tier (Web Adaptor, IWA/PKI in IIS) answers
# BEFORE ArcGIS is reached — it consumes the credential header and refuses
# at the HTTP layer, so the 499 JSON-envelope retry below never sees it.
_WEB_TIER_AUTH_STATUSES = frozenset({401, 403})


def _is_web_tier_refusal(exc: httpx.HTTPStatusError, requested_url: str) -> bool:
    """Whether *exc* is a front-end refusal worth one query-form retry.

    Three bounds against turning a real 401 into a credential replay: status
    must be 401/403, the response must not be a redirect result (non-empty
    ``history`` means the refusal came from a different host), and the
    responding URL must be same-origin as the one requested.
    """
    response = exc.response
    if response is None or response.status_code not in _WEB_TIER_AUTH_STATUSES:
        return False
    if response.history:
        return False
    return same_origin(str(response.url), requested_url)


def _arcgis_parsed_json(body: bytes) -> object:
    """``json.loads(body)``, with a depth bomb turned into a typed refusal.

    fix(#1858): a JSON depth bomb (300k nested ``[``) is small enough to pass
    ``bounded_probe_read``'s byte/structural-token caps, and ``json.loads``
    then raises ``RecursionError`` — a ``RuntimeError``, uncaught by this
    module's ``except (ValueError, TypeError)`` clauses. Converted here to
    ``EndpointCheckFailedError``, the type ``bounded_probe_read`` already
    raises for an over-bound body, so every caller's existing handler covers
    it. Ordinary ``ValueError`` (unparseable JSON) is left alone — it is
    already part of ``read_arcgis_json``'s contract.
    """
    try:
        return json.loads(body)
    except RecursionError as exc:
        raise EndpointCheckFailedError(str(exc)) from None


async def _read_with_query_token(
    client: httpx.AsyncClient,
    build_url: Callable[[str | None], str],
    token: str,
) -> object:
    """The query-form read both fallbacks land on. Never retried again.

    Routes through ``_query_form_credential`` so the token is registered for
    log scrubbing before it enters the URL, and bounds the whole fallback to
    a single extra request.
    """
    retry_headers, retry_token = _query_form_credential(token)
    body, _ = await bounded_probe_read(
        client, build_url(retry_token), headers=retry_headers, accept=OGC_JSON_ACCEPT
    )
    return _arcgis_parsed_json(body)


async def read_arcgis_json(
    client: httpx.AsyncClient,
    build_url: Callable[[str | None], str],
    token: str | None = None,
    *,
    current_version: object = None,
) -> object:
    """One bounded ArcGIS JSON read, with the token in a credential header.

    feat(C2): *build_url* receives the query-form token (``None`` on the
    header path), so one place decides where the credential goes while each
    caller composes its own other parameters.

    Two fallbacks to the query form, each bounded to one extra request and
    both landing on ``_read_with_query_token`` so neither chains into the
    other:

    * HTTP 200 with JSON error 499 "Token Required" — a pre-10.5.1 server
      ignoring the header. 498 (token read and rejected) is NOT retried.
    * fix(#1840): HTTP 401/403 on the request itself — a web tier in front of
      ArcGIS Enterprise consuming the header before ArcGIS runs, so there is
      no envelope for the first fallback to read. Bounded by
      ``_is_web_tier_refusal`` (same origin, no redirect, only those two
      statuses); a second 401 propagates.

    Raises whatever ``bounded_probe_read`` raises, plus ``ValueError`` from
    ``json.loads``; every caller already handles both. fix(#1858): a
    depth-bomb ``RecursionError`` surfaces as ``EndpointCheckFailedError`` via
    ``_arcgis_parsed_json``, a type every caller already handles.
    """
    headers, query_token = arcgis_request_auth(token, current_version=current_version)
    requested_url = build_url(query_token)
    try:
        body, _ = await bounded_probe_read(
            client, requested_url, headers=headers, accept=OGC_JSON_ACCEPT
        )
    except httpx.HTTPStatusError as exc:
        if not headers or not token or not _is_web_tier_refusal(exc, requested_url):
            raise
        return await _read_with_query_token(client, build_url, token)
    data = _arcgis_parsed_json(body)
    if not headers or _arcgis_error_code(data) != _ARCGIS_TOKEN_REQUIRED_CODE:
        return data
    # `token` is truthy here: non-empty `headers` only happens when a token
    # composed a header.
    return await _read_with_query_token(client, build_url, token or "")


def _query_token_suffix(query_token: str | None) -> str:
    """``&token=<percent-encoded>``, or nothing at all.

    fix(#1746): percent-encoding matters — a URL-reserved character in a raw
    token (``'``, ``#``, ``&``) can change the request or truncate the
    redactor's ``URL_LIKE_RE`` match, letting the token escape redaction in a
    log line. Only the pre-10.5.1 fallback reaches this now.
    """
    return f"&token={quote(query_token, safe='')}" if query_token else ""


def build_arcgis_layer_info_url(
    base_url: str, layer_id: int | str, query_token: str | None = None
) -> str:
    """``<service>/<layer>?f=json``, the layer's own metadata document.

    feat(C2): one builder shared by ``fetch_arcgis_pagination_info`` and
    ``fetch_arcgis_layer_preview`` — also the document ``currentVersion`` is
    read from for the version gate.
    """
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")
    params: dict[str, str] = {"f": "json"}
    if query_token:
        params["token"] = query_token
    return f"{base}/{safe_layer_id}?{urlencode(params)}"


async def probe_arcgis_service(
    base_url: str, client: httpx.AsyncClient, token: str | None = None
) -> dict | None:
    """Probe an ArcGIS FeatureServer/MapServer root and extract layer list.

    Returns a dict with service_type, version, and layers, or None if not an
    ArcGIS service.

    fix(#1770): the whole function runs under ``DEFAULT_CHECK_TIMEOUT``, same
    reasoning as ``probe_ogcapi``.
    """
    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            return await _probe_arcgis_service_within_deadline(base_url, client, token)
    except TimeoutError:
        logger.debug("ArcGIS probe: deadline exceeded for %s", base_url)
        return None


async def _probe_arcgis_service_within_deadline(
    base_url: str, client: httpx.AsyncClient, token: str | None
) -> dict | None:
    """``probe_arcgis_service``'s body, split out so the deadline wraps all
    of it. ``ArcGISTokenError`` still propagates through unchanged — it is
    not a ``TimeoutError``.
    """

    def _service_info_url(query_token: str | None) -> str:
        return f"{base_url}?f=json{_query_token_suffix(query_token)}"

    try:
        # fix(#1770): bounded read; `EndpointCheckFailedError` degrades to
        # "not an ArcGIS service" like the two httpx exceptions below.
        # feat(C2): first request to the service, so no version is known yet
        # — the header form goes out, and the 499 retry covers a pre-10.5.1
        # server.
        data = await read_arcgis_json(client, _service_info_url, token)
    except SSRFError:
        # fix(#1840): must be caught FIRST — `SSRFError` subclasses
        # `ValueError`, and the broader `except (ValueError, TypeError)`
        # below would otherwise swallow it as "not an ArcGIS service".
        raise
    except (
        httpx.HTTPStatusError,
        httpx.TransportError,
        EndpointCheckFailedError,
    ) as exc:
        # fix(#1770): the exception text quotes the full request URL, so it
        # must be redacted here too — the query fallback still puts
        # `token=` in the URL even though the header path does not.
        logger.debug(
            "ArcGIS probe failed for %s: %s", base_url, redact_exception_text(exc)
        )
        return None
    except (ValueError, TypeError):
        return None

    # fix(#1770): a non-dict 200 response (e.g. `200 5`) makes `"error" in
    # data` raise `TypeError` on an int, or silently substring-match on a
    # str — guard first so it degrades like the "not ArcGIS" check below.
    if not isinstance(data, dict):
        return None

    # ArcGIS reports refusals as HTTP 200 with an error envelope.
    if "error" in data:
        error_info = data["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        logger.warning(
            "ArcGIS error response: url=%s code=%s message=%s", base_url, code, message
        )
        if code in _ARCGIS_TOKEN_ERROR_CODES:
            raise ArcGISTokenError(code, message)
        return None

    if "layers" not in data and "tables" not in data:
        return None

    version = data.get("currentVersion")

    lower_url = base_url.lower()
    if "featureserver" in lower_url:
        service_type = "ArcGIS FeatureServer"
    elif "mapserver" in lower_url:
        service_type = "ArcGIS MapServer"
    else:
        service_type = "ArcGIS FeatureServer"

    layers = []

    service_oid = data.get("objectIdField")

    for layer in data.get("layers", []):
        layers.append(
            {
                "id": layer["id"],
                "name": layer["name"],
                "title": layer.get("title"),
                "geometry_type": _normalize_esri_geom_type(layer.get("geometryType")),
                "type": "layer",
                "object_id_field": layer.get("objectIdField")
                or service_oid
                or "OBJECTID",
            }
        )

    for table in data.get("tables", []):
        layers.append(
            {
                "id": table["id"],
                "name": table["name"],
                "title": table.get("title"),
                "geometry_type": None,
                "type": "table",
            }
        )

    return {
        "service_type": service_type,
        "version": str(version) if version else None,
        "layers": layers,
    }


async def enrich_arcgis_feature_counts(
    base_url: str,
    layers: list[dict],
    client: httpx.AsyncClient,
    token: str | None = None,
    *,
    current_version: object = None,
) -> list[dict]:
    """Enrich ArcGIS layers with feature counts.

    Fetches returnCountOnly=true for each layer via
    ``build_arcgis_count_query_url``, concurrency-limited by
    ``asyncio.Semaphore(5)``. A failure keeps feature_count=None.

    fix(#1770): bounded manually (``bounded_probe_read`` under
    ``DEFAULT_CHECK_TIMEOUT``) because ``assert_endpoints_stay_on_origin``
    never bounds ArcGIS reads — every URL here is composed from ``base_url``
    itself, dereferencing no server-chosen href. A cross-origin redirect is
    the only way the credential could travel; httpx drops ``Authorization``
    across one, and ``make_safe_client`` re-validates every hop.
    """
    semaphore = asyncio.Semaphore(5)

    async def _fetch_count(layer: dict) -> dict:
        async with semaphore:
            layer_id = layer.get("id")
            if layer_id is None:
                return {**layer, "feature_count": None}
            layer_url = f"{base_url.rstrip('/')}/{layer_id}"
            try:
                async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
                    data = await read_arcgis_json(
                        client,
                        lambda query_token: build_arcgis_count_query_url(
                            layer_url, query_token
                        ),
                        token,
                        current_version=current_version,
                    )
                # fix(#1770): a non-dict response makes `"error" in data` /
                # `data.get(...)` raise, uncaught, escaping `asyncio.gather`
                # and failing the WHOLE probe/preview instead of this layer.
                if not isinstance(data, dict):
                    return {**layer, "feature_count": None}
                if "error" in data:
                    return {**layer, "feature_count": None}
                return {**layer, "feature_count": data.get("count")}
            except (
                httpx.HTTPStatusError,
                httpx.TransportError,
                EndpointCheckFailedError,
                TimeoutError,
                ValueError,
                KeyError,
            ):
                # fix(#1858): `SSRFError` is a `ValueError`, so a refused
                # redirect lands here on purpose — this read establishes one
                # OPTIONAL fact about one layer; raising would let a single
                # layer's redirect end a probe of a service with fifty of
                # them. Rule shared with the sibling clauses below and with
                # `adapters/ogcapi.py`: an optional-fact read degrades, a
                # read whose failure ends the adapter raises (see
                # `probe_arcgis_service`).
                return {**layer, "feature_count": None}

    enriched = await asyncio.gather(*[_fetch_count(layer) for layer in layers])
    return list(enriched)


def build_arcgis_count_query_url(layer_url: str, query_token: str | None = None) -> str:
    """The bounded count query for one FeatureServer layer.

    feat(C2): *query_token* is the pre-10.5.1 fallback only — on the header
    transport it is ``None``, so the returned URL carries no credential (it
    is logged at INFO by httpx, recorded by proxies, and echoed in error
    bodies).

    ``<layer>/query?where=1=1&returnCountOnly=true&f=json`` exercises the
    same QUERY operation ``build_gdal_source`` uses, so a probe that
    succeeds here means the worker's own read will too — a deployment can
    serve layer metadata while gating ``/query``. This is the one producer
    of that URL; ``enrich_arcgis_feature_counts`` and the health probe both
    call it.
    """
    # A stored origin_uri is provenance, not a curated endpoint — it may carry
    # a query, fragment, or trailing /query. Strip all three first (like
    # `normalize_arcgis_url`) so this doesn't compose `.../0?f=html/query?...`.
    clean = urlparse(layer_url)._replace(query="", fragment="").geturl().rstrip("/")
    if clean.lower().endswith("/query"):
        clean = clean[: -len("/query")].rstrip("/")
    params: dict[str, str] = {
        "where": "1=1",
        "returnCountOnly": "true",
        "f": "json",
    }
    if query_token:
        params["token"] = query_token
    return f"{clean}/query?{urlencode(params)}"


async def fetch_arcgis_feature_count(
    base_url: str,
    layer_id: int | str,
    client: httpx.AsyncClient,
    token: str | None = None,
    *,
    current_version: object = None,
) -> int | None:
    """Fetch a layer feature count from ArcGIS REST query metadata.

    fix(#1770): bounded like `enrich_arcgis_feature_counts` above, for the
    same reason. `ArcGISTokenError`/`ValueError`/`httpx.HTTPError` propagate
    to the caller unchanged (`tasks_vector.py`'s ingest path,
    `fetch_arcgis_layer_preview` below); `EndpointCheckFailedError`/
    `TimeoutError` join that same contract as any other unreadable-response
    failure.
    """
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")
    layer_url = f"{base}/{safe_layer_id}"

    async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
        data = await read_arcgis_json(
            client,
            lambda query_token: build_arcgis_count_query_url(layer_url, query_token),
            token,
            current_version=current_version,
        )
    # fix(#1770): same as `_fetch_count` above — a non-dict response makes
    # the checks below raise `TypeError`/`AttributeError` uncaught, instead
    # of the ordinary "no count" degrade.
    if not isinstance(data, dict):
        return None
    if "error" in data:
        error_info = data["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        if code in _ARCGIS_TOKEN_ERROR_CODES:
            raise ArcGISTokenError(code, message)
        return None

    count = data.get("count")
    if isinstance(count, int) and count >= 0:
        return count
    return None


async def fetch_arcgis_pagination_info(
    base_url: str,
    layer_id: int | str,
    client: httpx.AsyncClient,
    token: str | None = None,
    *,
    current_version: object = None,
) -> tuple[int | None, bool, str | None]:
    """Fetch ArcGIS pagination support, page size, and stable order field.

    fix(#1770): bounded like `enrich_arcgis_feature_counts` above, for the
    same reason. This is also where ``currentVersion`` lives — a caller that
    already has it (``fetch_arcgis_layer_preview``) passes it in and skips
    the 499 retry this function relies on.
    """
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")

    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            data = await read_arcgis_json(
                client,
                lambda query_token: build_arcgis_layer_info_url(
                    base, safe_layer_id, query_token
                ),
                token,
                current_version=current_version,
            )
    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
        EndpointCheckFailedError,
        TimeoutError,
    ):
        # fix(#1858): degrades here for the reason given at `_fetch_count`
        # above — the optional fact is pagination support, and the worker's
        # own handler degrades identically either way.
        return None, False, None

    # fix(#1770): same as `_fetch_count`/`fetch_arcgis_feature_count` above
    # — a non-dict response makes the checks below raise uncaught, instead
    # of the ordinary "no pagination info" degrade.
    if not isinstance(data, dict):
        return None, False, None

    if "error" in data:
        error_info = data["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        if code in _ARCGIS_TOKEN_ERROR_CODES:
            raise ArcGISTokenError(code, message)
        return None, False, None

    value = data.get("maxRecordCount")
    max_record_count = value if isinstance(value, int) and value > 0 else None
    advanced = data.get("advancedQueryCapabilities") or {}
    supports_pagination = (
        isinstance(advanced, dict) and advanced.get("supportsPagination") is True
    )
    return max_record_count, supports_pagination, _extract_arcgis_object_id_field(data)


async def fetch_arcgis_layer_preview(
    base_url: str,
    layer_id: int | str,
    client: httpx.AsyncClient,
    token: str | None = None,
    sample_limit: int = 5,
) -> dict:
    """Preview an ArcGIS FeatureServer/MapServer layer from REST metadata.

    GDAL's ESRIJSON driver ignores ``resultRecordCount`` and paginates the
    *whole* layer to build an ogrinfo preview, timing out on large layers.
    The native ``?f=json`` layer metadata endpoint returns fields, geometry
    type, and CRS in one fast call; a second ``/query`` with
    ``resultRecordCount`` fetches a small sample — this bypasses GDAL
    entirely for the preview path.

    Returns the same shape ``run_service_preview`` returns: ``srid``,
    ``geometry_type``, ``layer_name``, ``feature_count``, ``columns``,
    ``sample_rows``. Raises ``ArcGISTokenError`` on token errors (the router
    surfaces a 403); other failures raise ``httpx.HTTPError``/``ValueError``.

    fix(#1770): both reads below are bounded like `enrich_arcgis_feature_counts`
    above. feat(C2): the metadata read discovers ``currentVersion`` first, so
    the two reads after it skip straight to the right transport.
    """
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")

    # Params are percent-encoded via urlencode so a URL-reserved character
    # in the token (+, &, %) cannot corrupt the query on the pre-10.5.1 path.
    async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
        meta = await read_arcgis_json(
            client,
            lambda query_token: build_arcgis_layer_info_url(
                base, safe_layer_id, query_token
            ),
            token,
        )

    # fix(#1770): a non-dict response makes `.get("fields", [])` raise
    # `AttributeError`, uncaught by this function or the router's `except
    # (httpx.HTTPError, ValueError, ...)`, reaching the caller as a 500
    # instead of the ordinary refusal. Raise `ValueError` to match that.
    if not isinstance(meta, dict):
        raise ValueError("ArcGIS layer metadata is not an object")

    if "error" in meta:
        error_info = meta["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        if code in _ARCGIS_TOKEN_ERROR_CODES:
            raise ArcGISTokenError(code, message)
        raise ValueError(f"ArcGIS layer metadata error ({code}): {message}")

    columns = [
        {
            "name": field.get("name"),
            "type": _normalize_esri_field_type(field.get("type")),
        }
        for field in meta.get("fields", [])
        if field.get("type") != "esriFieldTypeGeometry" and field.get("name")
    ]

    geometry_type = _normalize_esri_geom_type(meta.get("geometryType"))

    # CRS: prefer extent.spatialReference (latestWkid wins over wkid).
    srid: int | None = None
    spatial_ref = (meta.get("extent") or {}).get("spatialReference") or {}
    if isinstance(spatial_ref, dict):
        srid = spatial_ref.get("latestWkid") or spatial_ref.get("wkid")
    if not isinstance(srid, int):
        srid = None

    layer_name = meta.get("name")
    # feat(C2): read once from the metadata already fetched, and passed to
    # the reads below so they pick the transport directly, not via a 499.
    current_version = meta.get("currentVersion")

    sample_rows: list[dict] = []

    def _sample_url(query_token: str | None) -> str:
        query_params: dict[str, str] = {
            "where": "1=1",
            "outFields": "*",
            "resultRecordCount": str(sample_limit),
            "f": "json",
        }
        if query_token:
            query_params["token"] = query_token
        return f"{base}/{safe_layer_id}/query?{urlencode(query_params)}"

    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            sample_data = await read_arcgis_json(
                client, _sample_url, token, current_version=current_version
            )
        # fix(#1770): a non-dict `sample_data` degrades to "no sample rows"
        # here (best-effort already) rather than raising uncaught.
        if isinstance(sample_data, dict) and "error" not in sample_data:
            # ArcGIS query responses carry attributes under ``attributes``.
            sample_rows = [
                feat.get("attributes", {}) for feat in sample_data.get("features", [])
            ]
    except (
        httpx.HTTPError,
        ValueError,
        EndpointCheckFailedError,
        TimeoutError,
    ) as exc:
        # fix(#1858): degrades here for the reason given at `_fetch_count`
        # above — the optional fact is the sample rows; the metadata read
        # that gates previewability has no local handler, so it still raises.
        logger.debug(
            "ArcGIS sample-row fetch failed for %s/%s: %s",
            base,
            safe_layer_id,
            redact_exception_text(exc),
        )

    # fix(#1746): reuses the returnCountOnly=true helper so the preview
    # count matches what the probe already shows; a failure degrades to
    # None rather than failing the whole preview.
    feature_count: int | None = None
    try:
        feature_count = await fetch_arcgis_feature_count(
            base, safe_layer_id, client, token=token, current_version=current_version
        )
    except (
        httpx.HTTPError,
        ValueError,
        ArcGISTokenError,
        EndpointCheckFailedError,
        TimeoutError,
    ) as exc:
        # fix(#1858): degrades here for the reason given at `_fetch_count`
        # above — the optional fact is the row count shown beside the preview.
        logger.debug(
            "ArcGIS feature-count fetch failed for %s/%s: %s",
            base,
            safe_layer_id,
            redact_exception_text(exc),
        )

    return {
        "srid": srid,
        "geometry_type": geometry_type,
        "layer_name": layer_name,
        "feature_count": feature_count,
        "columns": columns,
        "sample_rows": sample_rows,
    }
