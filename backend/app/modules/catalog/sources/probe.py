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
from app.platform.service_auth import (
    INVALID_SERVICE_TOKEN_CODE,
    UNSUPPORTED_AUTH_METHOD_CODE,
    UNSUPPORTED_AUTH_METHOD_POLICY,
    service_carries_method,
    url_query_token,
)
from app.core.url_redaction import redact_url_credentials
from app.modules.catalog.sources.adapters.arcgis import (
    ARCGIS_SERVICE_FORMAT,
    ArcGISTokenError,
    _looks_like_arcgis,
    enrich_arcgis_feature_counts,
    normalize_arcgis_url,
    probe_arcgis_service,
)
from app.modules.catalog.sources.adapters.ogcapi import probe_ogcapi
from app.modules.catalog.sources.adapters.wfs import probe_wfs
from app.modules.catalog.sources.classify import classify_layer_kind
from app.modules.catalog.sources.schemas import LayerInfo, ProbeResponse
from app.platform.security import SSRFError

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

    def __init__(self, policy: str, *, code: str = INVALID_SERVICE_TOKEN_CODE):
        self.policy = policy
        # fix(#1746 B2b review r9): which refusal this is. A credential whose
        # VALUE cannot become a header is `invalid_service_token`; a method
        # the detected service cannot carry at all is
        # `unsupported_auth_method`, the same code the doors return when they
        # know the format up front. Two outcomes, one exception, because both
        # are "detection finished and the credential cannot be sent".
        self.code = code
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


def _arcgis_carries(credential: ServiceCredential | None) -> None:
    """Refuse a method ArcGIS cannot present, once ArcGIS is what we found.

    fix(#1746 B2b review r9): `url_query_token` answers None for basic and for
    a named API key, because neither fits in a query parameter. On the fallback
    path that silently became an ANONYMOUS ArcGIS probe: a vanity endpoint
    identified only by its `f=json` response answered 200 and the caller was
    told their credential worked, and then preview refused the same credential
    with `unsupported_auth_method`. The probe has to give the answer preview
    will give.

    fix(#1746 B2b review r27): this is now the ONLY place the question is
    answered for a probe, and it is answered after detection. The door used to
    answer it too, from the URL text, which refused a WFS at
    `/FeatureServer/wfs` a credential it supports. All three ArcGIS outcomes
    reach here: the keyword-detected fast path, the fallback that identifies a
    vanity endpoint by its response, and the token challenge.

    Module-level rather than nested in `detect_service_type` so that function
    stays inside its complexity budget, and so the rule can be read without
    reading the detector.
    """
    if credential is None:
        return
    # Asked of the shared mapping rather than re-listed here. The door asks the
    # same question of the same function about the method alone, and this asks
    # it again about the service that was actually found, so the two cannot
    # drift apart.
    if service_carries_method(ARCGIS_SERVICE_FORMAT, credential.method):
        return
    raise ServiceCredentialUnusable(
        UNSUPPORTED_AUTH_METHOD_POLICY, code=UNSUPPORTED_AUTH_METHOD_CODE
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
        except SSRFError:
            # fix(#1858): FIRST, because `SSRFError` subclasses `ValueError`
            # (`platform/security.py`) and the clause below reads a
            # `ValueError` as "this credential cannot become a header". The
            # two header-auth adapters catch only
            # `(httpx.HTTPStatusError, httpx.TransportError,
            # EndpointCheckFailedError)`, so a refused redirect hop -- raised
            # by `_revalidate_redirect` from a response hook, or by the guard
            # transport at connect time -- landed here and was recorded as a
            # credential refusal. Three answers were wrong at once: a probe
            # carrying NO credential was told its token was invalid;
            # `SSRFResolutionError` interpolates the redirect-chosen hostname
            # into its message, and `refusals[0]` carried that into the 422
            # body and the persisted audit reason, which is exactly what
            # `router.py`'s fixed `ssrf_policy_message` exists to prevent; and
            # `probe_service_url`'s `except SSRFError` handler, which answers
            # 400 `ssrf_blocked` and writes the matching audit row, never ran
            # for these two adapters. `probe_arcgis_service` got the same
            # clause in #1840 (`adapters/arcgis.py`) for this reason.
            raise
        except ValueError as exc:
            refusals.append(str(exc))
            logger.debug(
                "probe adapter refused the credential",
                adapter=probe.__name__,
                reason=str(exc),
            )
            return None

    async def _arcgis_probe(base: str) -> dict | None:
        """Probe ArcGIS, and let a token challenge identify it too.

        fix(#1746 B2b review r10): ArcGIS answers 499 or 498 in the BODY of an
        otherwise successful response, and `probe_arcgis_service` turns that
        into `ArcGISTokenError`. The challenge is proof that this endpoint IS
        an ArcGIS service, exactly as a layer list would be, so the credential
        has to be judged against it before the challenge is reported. Without
        this, a keyword-free protected endpoint answered a basic or named-key
        caller with the generic 403 "provide a valid ArcGIS token" while the
        keyword-detected branch and the public-vanity fallback both answered
        422 `unsupported_auth_method` — three sub-branches of one question
        giving two different answers, and the 403 is advice the caller cannot
        act on, because the method is what is wrong rather than the token.

        The challenge is re-raised unchanged for bearer and for a
        credential-free probe, which are the callers it is true advice for.
        """
        try:
            return await probe_arcgis_service(base, client, token=token)
        except ArcGISTokenError:
            _arcgis_carries(credential)
            raise

    # Fast path: ArcGIS URL pattern
    if looks_arcgis:
        logger.info(
            "URL pattern matches ArcGIS", url=redact_url_credentials(url)
        )  # fix(#430 BA-27)
        base_url, layer_id = normalize_arcgis_url(url)
        result = await _arcgis_probe(base_url)
        if result is not None:
            _arcgis_carries(credential)
            # feat(C2): the probe just read `currentVersion` out of the
            # service document, so the count queries know which token
            # transport this deployment understands without discovering it
            # again from a 499.
            enriched = await enrich_arcgis_feature_counts(
                base_url,
                result["layers"],
                client,
                token=token,
                current_version=result.get("version"),
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
    arcgis_result = await _arcgis_probe(base_url)
    if arcgis_result is not None:
        _arcgis_carries(credential)
        # feat(C2): same as the fast path above -- the version came back with
        # the service document.
        enriched = await enrich_arcgis_feature_counts(
            base_url,
            arcgis_result["layers"],
            client,
            token=token,
            current_version=arcgis_result.get("version"),
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
