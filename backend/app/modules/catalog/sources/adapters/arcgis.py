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

# Re-exported so every existing importer of ``ARCGIS_SERVICE_FORMAT`` from this
# module keeps working; the literal itself lives in ``core/service_tokens.py``
# now, beside the two sets that decide what a format's credential may become,
# because ``core/`` may not import ``app.modules.*`` (feat(C2)).
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

# feat(C2). ArcGIS Server started reading a bearer token from an HTTP header at
# 10.5.1; before that the ``token`` query parameter was the only transport it
# understood. Everything at or above this, and hosted ArcGIS Online whatever it
# reports, gets the header.
ARCGIS_HEADER_TOKEN_MIN_VERSION = (10, 5, 1)

# ArcGIS reports an auth refusal as an error envelope inside an HTTP 200 body.
# 499 means "Token Required": no usable token was seen at all, which is also
# exactly what a pre-10.5.1 server says when it ignores the credential header,
# and so is what triggers the query-form retry. 498 means a token WAS read and
# rejected, so the header transport worked and a retry would only resend a bad
# token. A deployment whose WEB TIER eats the header never reaches either code;
# `_WEB_TIER_AUTH_STATUSES` below is that case.
_ARCGIS_TOKEN_REQUIRED_CODE = 499
_ARCGIS_TOKEN_ERROR_CODES = frozenset({498, _ARCGIS_TOKEN_REQUIRED_CODE})


class ArcGISTokenError(Exception):
    """Raised when ArcGIS returns a token-related error (codes 498, 499)."""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"ArcGIS token error ({code}): {message}")


# Maps esri geometry type strings to simple geometry names
_ESRI_GEOM_TYPE_MAP = {
    "esriGeometryPoint": "Point",
    "esriGeometryMultipoint": "MultiPoint",
    "esriGeometryPolyline": "LineString",
    "esriGeometryPolygon": "Polygon",
    "esriGeometryEnvelope": "Envelope",
}


# Maps ESRI field types to the OGR field-type names the rest of the preview
# pipeline expects (matching the ``type`` strings ogrinfo -json emits for the
# WFS/OGC path). Unknown types fall back to "String".
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
    """Map an ESRI field type to an OGR field-type name (default "String")."""
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
    """Check if a URL looks like an ArcGIS service (FeatureServer or MapServer)."""
    lower = url.lower()
    return "featureserver" in lower or "mapserver" in lower


def normalize_arcgis_url(url: str) -> tuple[str, int | None]:
    """Normalize an ArcGIS URL to a canonical service root form.

    Strips query parameters, trailing slashes, /query suffix, and extracts
    layer number if present.

    Returns (normalized_base_url, optional_layer_id).
    """
    # Strip query parameters
    parsed = urlparse(url)
    clean_url = parsed._replace(query="", fragment="").geturl()

    # Strip trailing slash
    clean_url = clean_url.rstrip("/")

    # Strip /query suffix
    if clean_url.lower().endswith("/query"):
        clean_url = clean_url[: -len("/query")]
        clean_url = clean_url.rstrip("/")

    # Extract layer number if present (e.g., /FeatureServer/0 or /MapServer/3)
    layer_id = None
    match = re.search(r"/(FeatureServer|MapServer)/(\d+)$", clean_url, re.IGNORECASE)
    if match:
        layer_id = int(match.group(2))
        # Remove the layer number from the URL
        clean_url = clean_url[: match.start() + 1 + len(match.group(1))]

    return clean_url, layer_id


def parse_arcgis_current_version(value: object) -> tuple[int, int, int] | None:
    """Parse an ArcGIS ``currentVersion`` into a comparable triple.

    feat(C2). Esri does not spell this the way semver does. ``currentVersion``
    is a NUMBER, and a patch release is encoded as a second fractional digit:
    10.5.1 is reported as ``10.51``, 10.4.1 as ``10.41``, while 10.5 is
    ``10.5``. So ``10.5`` and ``10.51`` are two releases either side of the
    line this function exists to draw, and reading them as floats puts
    ``10.51`` above ``10.5`` for the wrong reason and ``10.5`` above ``10.41``
    for another wrong reason. Dotted three-part strings ("10.5.1") are read
    literally, because ArcGIS Enterprise's own documentation uses that spelling
    in prose.

    Returns ``None`` for anything unparseable, including ``None`` itself, and
    every caller treats that as "version unknown".

    The two-digit rule is ambiguous in principle for a hypothetical ``x.10``,
    which this reads as ``x.1.0`` rather than ``x.10.0``. Esri has shipped no
    such version, and the only comparison made here is against 10.5.1, where
    both readings of any ``11.x`` land on the same side.
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
        # Note: this reads a hypothetical "10.10" as 10.1.0 rather than
        # 10.10.0, which would fall to the query form. Esri has shipped no
        # such version, and above 10.9 the numbering went to 11.x.
        return (major, int(fraction[0]), int(fraction[1]))
    return (major, int(fraction), 0)


def arcgis_accepts_header_token(current_version: object = None) -> bool:
    """Whether this service reads a token from the Authorization header.

    feat(C2). True unless the service reported a version older than 10.5.1.
    An unknown or unparseable version is treated as new enough, because the
    only deployments that cannot read the header are ArcGIS Server releases
    from before 2017 and every one of those DOES report a version; hosted
    ArcGIS Online is the common case and it reports 11.x. A wrong guess in
    this direction is one extra request (the 499 retry below), and a wrong
    guess in the other direction would put the token back in the URL for
    everyone.
    """
    parsed = parse_arcgis_current_version(current_version)
    return parsed is None or parsed >= ARCGIS_HEADER_TOKEN_MIN_VERSION


def _arcgis_error_code(data: object) -> int | None:
    """The ArcGIS error code in an HTTP 200 envelope, if there is one."""
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, int) else None


def _query_form_credential(token: str) -> tuple[dict[str, str], str | None]:
    """The pre-10.5.1 fallback: no headers, the bare token for the query.

    fix(#1840 audit round 1): the ONE place the query form is chosen, and the
    reason it is a function rather than three ``return {}, token`` lines. On
    the header path ``build_credential_header`` registers the line it composes
    with ``register_credential_secret``, so ``redact_exception_text`` and the
    structlog ``_scrub_text`` processor can scrub the credential out of
    anything that echoes it back BY EXACT VALUE. Nothing registered the token
    on this branch, which is precisely the branch that puts it in a URL -- and
    ArcGIS answers an auth refusal with a server-chosen ``message`` that this
    module logs at WARNING. Redaction there fell back to pattern matching on a
    ``token=`` query key, the shape-dependent coverage #1770 round 43
    introduced the registry to replace. Registered here so both transports
    are covered by the same exact-value scrub.

    fix(#1840 audit round 2): with a floor, because exact-value scrubbing is
    a substring replacement over every log line in the request's context and
    a short value is a substring of ordinary text. ArcGIS is the one transport
    whose token is never held to ``HEADER_TOKEN_CHARSET`` -- ``credential_or_422``
    returns before that check for a URL-query format -- so nothing upstream
    rejects a four-character one. Measured: registering ``json`` rewrote
    ``https://json.example.com`` to ``https://***.example.com`` in that
    request's own logs, which corrupts the diagnostics the redactor exists to
    make safe rather than protecting anything (a real AGO token is a hundred
    characters of base64url). The same floor and charset the header transport
    already applies is what decides: a value that could not have been a header
    credential is not registered, and is not scrubbed. The credential still
    reaches the origin either way; only the log-scrub registration is gated.
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

    feat(C2). Exactly one half is ever populated. The header form is the
    default and the query form is the documented fallback for ArcGIS Server
    older than 10.5.1; ``build_credential_header`` composes the header, so this
    adapter is not a second producer of one (see
    ``tests/test_credential_producer_structural.py``).

    A token the builder refuses -- one holding whitespace or a non-ASCII
    character, which no ArcGIS token does -- degrades to the query form rather
    than failing the read, because the query form percent-encodes it and that
    is exactly what this path did before lane C2. Nothing about the refused
    value is logged: it is a credential.
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


# fix(#1840 codex round 1): the statuses a web tier answers BEFORE ArcGIS is
# reached. On ArcGIS Enterprise behind a Web Adaptor, or with web-tier
# authentication (IWA or PKI in IIS), the server in front consumes the
# credential header and refuses at the HTTP layer, so `bounded_probe_read`'s
# `raise_for_status()` fires and no JSON envelope is ever produced -- the 499
# fallback below cannot see such a deployment at all.
_WEB_TIER_AUTH_STATUSES = frozenset({401, 403})


def _is_web_tier_refusal(exc: httpx.HTTPStatusError, requested_url: str) -> bool:
    """Whether *exc* is a front-end refusal worth one query-form retry.

    Three bounds, all of them about not turning a real 401 into a credential
    replay somewhere else. The status has to be 401 or 403; the response must
    not have come through a redirect (``history`` empty), because a refusal
    from a host we were bounced to says nothing about the host we addressed;
    and the responding URL has to be the same origin as the one asked for.
    """
    response = exc.response
    if response is None or response.status_code not in _WEB_TIER_AUTH_STATUSES:
        return False
    if response.history:
        return False
    return same_origin(str(response.url), requested_url)


async def _read_with_query_token(
    client: httpx.AsyncClient,
    build_url: Callable[[str | None], str],
    token: str,
) -> object:
    """The query-form read both fallbacks land on. Never retried again.

    Composing through ``_query_form_credential`` rather than inline is what
    registers the token with the exact-value scrubber before it goes into a
    URL (fix(#1840 audit round 1)), and having exactly one of these is what
    bounds the whole fallback to a single extra request: nothing it calls can
    reach either fallback branch again.
    """
    retry_headers, retry_token = _query_form_credential(token)
    body, _ = await bounded_probe_read(
        client, build_url(retry_token), headers=retry_headers, accept=OGC_JSON_ACCEPT
    )
    return json.loads(body)


async def read_arcgis_json(
    client: httpx.AsyncClient,
    build_url: Callable[[str | None], str],
    token: str | None = None,
    *,
    current_version: object = None,
) -> object:
    """One bounded ArcGIS JSON read, with the token in a credential header.

    feat(C2). *build_url* is handed the token that belongs in the QUERY, which
    is ``None`` on the header path, so each caller keeps composing its own
    parameters while only one place decides where the credential goes.

    Two fallbacks to the query form, both bounded to exactly one extra request
    on the same validated URL, and both landing on ``_read_with_query_token``
    so neither can chain into the other:

    * An HTTP 200 whose JSON envelope carries error 499 "Token Required". That
      is what an ArcGIS Server older than 10.5.1 says when it ignores the
      header and therefore sees no token. 498 is NOT retried -- it means a
      token was read and rejected, so the header arrived.
    * fix(#1840 codex round 1): an HTTP 401 or 403 on the request itself. A
      Web Adaptor or web-tier authentication (IWA/PKI in IIS) in front of
      ArcGIS Enterprise consumes the credential header and refuses before
      ArcGIS runs, so there is no envelope for the first fallback to read, and
      an authenticated probe, preview or import would fail on a portal where
      ``?token=`` had always worked. Bounded by ``_is_web_tier_refusal``:
      same origin, no redirect in between, and only those two statuses. A
      second 401 propagates, because ``_read_with_query_token`` catches
      nothing.

    Raises whatever ``bounded_probe_read`` raises, plus ``ValueError`` from
    ``json.loads``; every caller already handles both.
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
    data = json.loads(body)
    if not headers or _arcgis_error_code(data) != _ARCGIS_TOKEN_REQUIRED_CODE:
        return data
    # `token` is truthy here: `headers` is non-empty, which only happens for a
    # token that composed a header.
    return await _read_with_query_token(client, build_url, token or "")


def _query_token_suffix(query_token: str | None) -> str:
    """``&token=<percent-encoded>``, or nothing at all.

    fix(#1746 codex r7): percent-encode the token before concatenating it into
    a URL -- a URL-reserved character in a raw token (``'``, ``#``, ``&``) can
    change what the request means and, in a log line, end the ``URL_LIKE_RE``
    match early enough to escape the redactor entirely. Only the pre-10.5.1
    fallback reaches this now.
    """
    return f"&token={quote(query_token, safe='')}" if query_token else ""


def build_arcgis_layer_info_url(
    base_url: str, layer_id: int | str, query_token: str | None = None
) -> str:
    """``<service>/<layer>?f=json``, the layer's own metadata document.

    feat(C2): one builder for the two callers that read it
    (``fetch_arcgis_pagination_info`` and ``fetch_arcgis_layer_preview``), on
    the same reasoning as ``build_arcgis_count_query_url`` -- and because the
    version this module gates on is read out of exactly this document.
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

    Returns a dict with service_type, version, and layers on success,
    or None if not an ArcGIS service.

    fix(#1770 round 41 P1): the whole function runs under
    ``DEFAULT_CHECK_TIMEOUT``, same reasoning as ``probe_ogcapi``.
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
    of it. ``ArcGISTokenError`` still propagates through the deadline
    unchanged: it is not a `TimeoutError`, so the wrapper's `except
    TimeoutError` does not intercept it.
    """

    def _service_info_url(query_token: str | None) -> str:
        return f"{base_url}?f=json{_query_token_suffix(query_token)}"

    try:
        # fix(#1770 round 41 P1): bounded read, not a plain `client.get` --
        # see `bounded_probe_read`'s docstring. `EndpointCheckFailedError`
        # joins the two httpx types this already caught: whatever the cause,
        # this degrades to "not an ArcGIS service" the same way.
        #
        # feat(C2): this is the FIRST request to the service, so no version is
        # known yet and the header form is what goes out. `read_arcgis_json`'s
        # 499 retry is what covers a pre-10.5.1 server here, since there is no
        # earlier document to have read `currentVersion` from.
        data = await read_arcgis_json(client, _service_info_url, token)
    except SSRFError:
        # fix(#1840 audit round 1): FIRST, because `SSRFError` subclasses
        # `ValueError` (`platform/security.py`) and the `except (ValueError,
        # TypeError)` below is the clause that catches `json.loads` failing.
        # Before lane C2 the network read and the parse sat in two separate
        # `try` blocks, so a refused redirect hop -- a blocked address, or a
        # cross-origin one that would have forwarded a credential header --
        # propagated to the `/probe` door and became its coded refusal.
        # Folding the parse into the request's `try` silently downgraded that
        # to "not an ArcGIS service", and the caller then went on trying the
        # remaining probes. The SSRF itself was still blocked; the ANSWER the
        # operator gets is what regressed.
        raise
    except (
        httpx.HTTPStatusError,
        httpx.TransportError,
        EndpointCheckFailedError,
    ) as exc:
        # fix(#1770 round 39): an HTTPStatusError's message quotes the whole
        # request URL back, so the caught exception's text must be redacted,
        # not just the href a response body carries. feat(C2) narrows what is
        # in that URL -- the token is a header now, except on the pre-10.5.1
        # fallback -- without removing the need: `build_credential_header`
        # registers the composed line for exact-value scrubbing, and the
        # fallback still puts `token=` in the query.
        logger.debug(
            "ArcGIS probe failed for %s: %s", base_url, redact_exception_text(exc)
        )
        return None
    except (ValueError, TypeError):
        return None

    # fix(#1770 round 44 P2): a `200 5`/`200 "x"` response is valid JSON but
    # not a dict, and `"error" in data` on an int raises `TypeError`
    # (a str would silently do a substring check instead, which is
    # misleading but not a crash) -- either way this is not an ArcGIS
    # service response, the same degrade `"layers" not in data` below
    # already gives.
    if not isinstance(data, dict):
        return None

    # ArcGIS returns HTTP 200 with error in JSON body
    if "error" in data:
        error_info = data["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        logger.warning(
            "ArcGIS error response: url=%s code=%s message=%s", base_url, code, message
        )
        if code in _ARCGIS_TOKEN_ERROR_CODES:  # Invalid/expired token
            raise ArcGISTokenError(code, message)
        return None

    # Validate this is an ArcGIS service
    if "layers" not in data and "tables" not in data:
        return None

    version = data.get("currentVersion")

    # Determine service type from URL
    lower_url = base_url.lower()
    if "featureserver" in lower_url:
        service_type = "ArcGIS FeatureServer"
    elif "mapserver" in lower_url:
        service_type = "ArcGIS MapServer"
    else:
        service_type = "ArcGIS FeatureServer"

    layers = []

    # Service-level objectIdField fallback
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

    Fetches returnCountOnly=true for each layer. Uses asyncio.Semaphore(5)
    for concurrency limiting. On failure, keeps feature_count=None.

    fix(#1755 item 14): the count query is composed by
    ``build_arcgis_count_query_url`` rather than hand-rolled here for a third
    time. Two behaviours change with the fold, both deliberate. The
    ``where`` parameter is now percent-encoded by ``urlencode`` (``1%3D1``
    either way) and the parameter ORDER follows the builder's, so a test
    pinning the old literal string sees a different URL for the same request.
    And on the pre-10.5.1 fallback the token is percent-encoded by
    ``urlencode`` rather than by a hand-written ``quote(token, safe='')``,
    which differs for a token containing reserved characters -- ``urlencode``
    leaves nothing dangerous unencoded, but a ``+`` in a token now renders as
    ``%2B`` where the old concatenation also produced ``%2B``, and a space
    renders as ``+`` rather than ``%20``. ArcGIS decodes both.

    fix(#1770 round 44 P1): the read is bounded (``bounded_probe_read`` under
    ``DEFAULT_CHECK_TIMEOUT``) because ``assert_endpoints_stay_on_origin``
    never runs a bound for ArcGIS at all -- it returns immediately for any
    ``service_format`` outside `HEADER_AUTH_SERVICE_FORMATS`
    (``requires_header_token_policy``), which ArcGIS is still not a member of.
    feat(C2) did not change that: the endpoint check exists for a service that
    DESCRIBES a foreign operation endpoint GDAL then follows, and this adapter
    composes every URL it reads from ``base_url`` itself, dereferencing no
    server-chosen href. A redirect away from that origin is the one remaining
    way the credential could travel, and httpx drops ``Authorization`` across
    a cross-origin redirect while ``make_safe_client`` re-validates every hop.
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
                # fix(#1770 round 45 P2): a `200 5`/`200 []` response is valid
                # JSON but not a dict, and `"error" in data`/`data.get(...)`
                # on either raises `TypeError`/`AttributeError` -- neither
                # caught below, so it escaped `asyncio.gather` and failed the
                # WHOLE probe/preview rather than degrading this one layer.
                if not isinstance(data, dict):
                    return {**layer, "feature_count": None}
                # ArcGIS may return HTTP 200 with error in JSON body
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
                return {**layer, "feature_count": None}

    enriched = await asyncio.gather(*[_fetch_count(layer) for layer in layers])
    return list(enriched)


def build_arcgis_count_query_url(layer_url: str, query_token: str | None = None) -> str:
    """The bounded count query for one FeatureServer layer.

    feat(C2): *query_token* is the pre-10.5.1 fallback only. On the header
    transport it is ``None`` and the returned URL carries no credential at all,
    which is the point -- it is the URL httpx logs at INFO as ``HTTP Request:
    GET ...``, the URL a proxy records, and the URL an origin quotes back in an
    error. ``arcgis_request_auth`` decides which of the two it is; nothing
    calls this with a raw token except through that decision.

    ``<layer>/query?where=1=1&returnCountOnly=true&f=json`` — the smallest
    request that exercises the QUERY operation, which is the operation
    ``build_gdal_source`` composes and the worker actually reads. It returns a
    single integer no matter how large the layer is, so it is safe to issue
    against anything.

    fix(#1746 codex r6): extracted so the health probe can ask the same
    question this function asks. A deployment that serves layer METADATA
    publicly while gating ``/query`` is ordinary, and a probe of the layer
    document would call it healthy and then fail in the worker. One builder,
    so the probe and the count fetcher cannot drift into probing one endpoint
    and depending on another.

    fix(#1755 item 14): ``enrich_arcgis_feature_counts`` was the third
    hand-rolled copy of this query and now calls this instead, so the builder
    is finally the only producer the name promises.
    """
    # A stored origin_uri is provenance, not a curated endpoint: it can carry
    # a query string, a fragment, or an already-appended /query. Strip all
    # three before composing, the same way `normalize_arcgis_url` does, so the
    # result is an endpoint rather than `.../0?f=html/query?...`.
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

    fix(#1770 round 44 P1): same reasoning as `enrich_arcgis_feature_counts`
    above -- `assert_endpoints_stay_on_origin` runs no bound for ArcGIS at
    all, so this reads through `bounded_probe_read` under
    `DEFAULT_CHECK_TIMEOUT`, matching the four service-type probes.
    `ArcGISTokenError`/`ValueError`/`httpx.HTTPError` propagate unchanged to
    the caller, which already handles them (`tasks_vector.py`'s ingest path,
    and `fetch_arcgis_layer_preview` below); `EndpointCheckFailedError`/
    `TimeoutError` join that same contract, since both mean the same thing
    to a caller as any other unreadable-response failure.

    feat(C2): the token is an ``Authorization: Bearer`` header now, so the URL
    this composes carries no credential (see ``build_arcgis_count_query_url``).
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
    # fix(#1770 round 45 P2): same reasoning as `_fetch_count` above -- a
    # `200 5`/`200 []` response is valid JSON but not a dict, and this
    # function has no local `except` at all around the checks below, so an
    # uncaught `TypeError`/`AttributeError` propagated straight to the
    # caller instead of the ordinary "no count" degrade.
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

    fix(#1770 round 44 P1): same reasoning as `enrich_arcgis_feature_counts`
    above -- `assert_endpoints_stay_on_origin` runs no bound for ArcGIS at
    all, so this reads through `bounded_probe_read` under
    `DEFAULT_CHECK_TIMEOUT`.

    feat(C2): the token is an ``Authorization: Bearer`` header now. This is
    also the document ``currentVersion`` is read from, so a caller that has
    already fetched it (``fetch_arcgis_layer_preview``) passes the version in
    and skips the retry; this one has not, so it relies on the 499 retry.
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
        return None, False, None

    # fix(#1770 round 49 P3): same reasoning as `_fetch_count`/`fetch_arcgis_
    # feature_count` above -- a `200 5`/`200 "x"` response is valid JSON but
    # not a dict, and this function has no local `except` around the checks
    # below, so an uncaught `TypeError`/`AttributeError` propagated straight
    # to the caller instead of the ordinary "no pagination info" degrade.
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
    *whole* layer to build an ogrinfo preview, which times out on large
    layers (millions of rows). The native ArcGIS ``?f=json`` layer metadata
    endpoint returns the field list, geometry type, and CRS in a single fast
    call; a second ``/query`` call with ``resultRecordCount`` fetches a small
    sample. This bypasses GDAL entirely for the preview path.

    Returns a dict with the same shape ``run_service_preview`` returns:
    keys ``srid``, ``geometry_type``, ``layer_name``, ``feature_count``,
    ``columns``, ``sample_rows``.

    Raises ``ArcGISTokenError`` on token errors so the router can surface a
    403. Other HTTP/parse failures raise ``httpx.HTTPError``/``ValueError``.

    fix(#1770 round 44 P1): (same reasoning as `enrich_arcgis_feature_counts`)
    `assert_endpoints_stay_on_origin` never bounds an ArcGIS-format read at
    all, so the metadata and sample-row reads below both go through
    `bounded_probe_read` under `DEFAULT_CHECK_TIMEOUT`; `EndpointCheckFailedError`/
    `TimeoutError` join the metadata read's propagation to the caller
    (`router.py`'s `except (httpx.HTTPError, ValueError, ...)`, widened to
    match) and the sample-row/feature-count reads' own local `except`
    clauses below (already best-effort, degrade to an empty/`None` result).

    feat(C2): the token travels as an ``Authorization: Bearer`` header. The
    metadata read is the one that discovers ``currentVersion``, so the two
    reads after it are told what this service is and a pre-10.5.1 server costs
    one retry rather than three.
    """
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")

    # --- Layer metadata: fields, geometry type, CRS, name ---
    # Query params are percent-encoded via urlencode so a token containing
    # URL-reserved characters (+, &, %) cannot corrupt the query string on the
    # pre-10.5.1 fallback.
    async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
        meta = await read_arcgis_json(
            client,
            lambda query_token: build_arcgis_layer_info_url(
                base, safe_layer_id, query_token
            ),
            token,
        )

    # fix(#1770 round 45 P2): a `200 5`/`200 []` response is valid JSON but
    # not a dict. `.get("fields", [])` below would raise `AttributeError`,
    # uncaught by this function's own body and by the router's except
    # clause around this call (`httpx.HTTPError, ValueError, ...` -- no
    # `AttributeError`/`TypeError`), so it reached the caller as a 500
    # instead of the ordinary "not readable" refusal every other
    # unparseable metadata response gets. `ValueError` matches this
    # function's own contract for a bad metadata response (see the `error`
    # branch just below) and the caller's existing `except ValueError`.
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
    # feat(C2): read once, from the document that was fetched anyway, and
    # handed to both reads below so they pick the transport directly instead
    # of discovering it from a 499.
    current_version = meta.get("currentVersion")

    # --- Sample rows: small bounded query ---
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
        # fix(#1770 round 45 P2): same reasoning as the metadata read above
        # -- a non-dict `sample_data` degrades to "no sample rows" here
        # (this read already treats its own failures as best-effort),
        # rather than raising `AttributeError`/`TypeError` uncaught.
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
        logger.debug(
            "ArcGIS sample-row fetch failed for %s/%s: %s",
            base,
            safe_layer_id,
            redact_exception_text(exc),
        )

    # fix(#1746): the preview previously always returned feature_count=None;
    # reuse the existing returnCountOnly=true helper (same safe client, one
    # extra request) so the preview matches the count the probe already shows.
    # A count failure degrades to None rather than failing the whole preview.
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
