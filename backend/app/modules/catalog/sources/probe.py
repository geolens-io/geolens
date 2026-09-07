"""Service type detection orchestration logic.

Coordinates WFS, OGC API Features, and ArcGIS probing to detect what kind of
service a URL points to and return a unified layer list.

fix(Phase 1057 D-05): OGC API/WFS probe results carry geometry_type=None,
feature_count=None, and a backend-classified kind (D-09/CLASS-07) instead of
running per-layer ogrinfo enrichment; preview.py runs ogrinfo lazily for the
single layer the user selects. ArcGIS enrichment stays — it uses fast HTTP
returnCountOnly queries, not ogrinfo.
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
    parsed = urlparse(url)
    lower_path = parsed.path.lower()
    lower_query = parsed.query.lower()
    return "/wfs" in lower_path or "service=wfs" in lower_query


class ServiceCredentialUnusable(Exception):
    """A header-auth adapter could not compose the credential it was given.

    fix(#1746): raised only after every adapter has had its turn — the
    probe DETERMINES the service type, so judging the credential from the
    URL alone up front would reject a working ArcGIS token (percent-encoded
    into a query, legitimately holding characters the header charset
    refuses). A token one adapter can't use stops only that adapter; if
    another claims the URL the probe still succeeds, and if none does this
    carries the policy the caller needs instead of a bare "not recognized".
    """

    def __init__(self, policy: str, *, code: str = INVALID_SERVICE_TOKEN_CODE):
        self.policy = policy
        # fix(#1746): invalid_service_token = value can't become a
        # header; unsupported_auth_method = the service can't carry the
        # method at all (same code the doors return up front).
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

    Layers arrive with geometry_type=None, feature_count=None, and a
    pre-classified kind field set by probe_ogcapi/probe_wfs (D-05).
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

    fix(#1746): `url_query_token` answers None for basic/named-API-key
    credentials, since neither fits a query param. Unchecked, the fallback
    path silently became an ANONYMOUS ArcGIS probe that told the caller
    their credential worked, only for preview to then refuse it.

    fix(#1746): the ONLY place this is answered, and after detection —
    the door used to answer it from URL text alone, which wrongly refused a
    WFS at `/FeatureServer/wfs` a credential it does support. Module-level
    rather than nested in `detect_service_type` so that function stays
    inside its complexity budget.
    """
    if credential is None:
        return
    # Same question the door asks (about the method alone), asked again here
    # about the service actually found, so the two answers cannot drift apart.
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
    # fix(#1746): ArcGIS only fits a bearer token (percent-encoded
    # into the URL query); the other two methods simply can't be presented
    # here, and the origin's 401 is the honest answer.
    token = url_query_token(credential)
    looks_arcgis = _looks_like_arcgis(url)
    looks_wfs = _looks_like_wfs(url)

    # fix(#1746): recorded rather than raised, so the ArcGIS branch below
    # still gets its turn with the same credential.
    refusals: list[str] = []

    async def _header_auth_probe(probe) -> dict | None:
        try:
            return await probe(url, client, credential=credential)
        except SSRFError:
            # fix(#1858): caught FIRST — SSRFError subclasses ValueError, so
            # without this clause a refused redirect hop was recorded as a
            # credential refusal, leaking the redirect-chosen hostname into
            # the 422 body/audit reason and skipping probe_service_url's
            # ssrf_blocked handler. Same fix as #1840 in adapters/arcgis.py.
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

        fix(#1746): a 499/498 challenge in the response body proves this
        endpoint IS ArcGIS, so the credential's method must be judged
        against it before the challenge is reported — otherwise a
        keyword-free protected endpoint gave a basic/named-key caller a
        403 "provide a valid token" while other ArcGIS branches gave 422
        `unsupported_auth_method` for the same problem. Re-raised unchanged
        for bearer and credential-free probes, where it's the true answer.
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
        )  # fix(#430)
        base_url, layer_id = normalize_arcgis_url(url)
        result = await _arcgis_probe(base_url)
        if result is not None:
            _arcgis_carries(credential)
            # feat(C2): currentVersion came back with the service document,
            # so count queries know the token transport without rediscovering
            # it from a 499.
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
        )  # fix(#430)
        result = await _header_auth_probe(probe_wfs)
        if result is not None:
            # D-05: no enrichment — layers already have geometry_type=None,
            # feature_count=None, kind='vector' from probe_wfs.
            return _build_probe_response(result, result["layers"], url)
        # Fast-path failed — fall through to slow path

    # Slow path: OGC API probe first, then WFS, then ArcGIS
    logger.info("Trying all probes", url=redact_url_credentials(url))  # fix(#430)

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
        # feat(C2): same as the fast path above.
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
        # Nothing claimed this URL; a header-auth adapter never got to ask
        # because the credential couldn't become a header — that policy is
        # the actionable half of the answer, so it's what the caller gets.
        raise ServiceCredentialUnusable(refusals[0])

    raise ServiceNotRecognized()
