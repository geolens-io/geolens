"""Service probing, preview, and persistent-connector API endpoints."""

import asyncio
import hashlib
import uuid
from typing import NoReturn
from urllib.parse import urljoin

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from slowapi.util import get_remote_address
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_redaction import has_url_credentials, redact_url_credentials
from app.modules.audit.service import AuditEvent, audit_emit
from app.core.crs_uri import parse_crs_uri
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.core.dependencies import get_db
from app.platform.jobs.models import IngestJob
from app.platform.extensions import get_catalog_port, get_connector_extension
from app.core.service_tokens import (
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
)
from app.modules.catalog.sources.adapters.arcgis import (
    ARCGIS_SERVICE_FORMAT,
    ArcGISTokenError,
    _looks_like_arcgis,
    fetch_arcgis_layer_preview,
    normalize_arcgis_url,
)
from app.modules.catalog.sources.adapters.wfs import WFS_SERVICE_FORMAT
from app.modules.catalog.sources.arcgis_signin import (
    AUDIT_SUCCESS,
    ArcGISSignInError,
    open_portal_signin,
    portal_host,
)
from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview
from app.modules.catalog.sources.signin_guard import (
    _signin_audit,
    _signin_refusal,
    _signin_reserve,
    _signin_settle_cancelled,
    signin_target,
)
from app.modules.catalog.sources.probe import (
    ServiceCredentialUnusable,
    ServiceNotRecognized,
    detect_service_type,
)
from app.modules.catalog.sources.schemas import (
    ArcGISSignInRequest,
    ArcGISSignInResponse,
    ConnectorDefinitionResponse,
    ConnectorDiscoverRequest,
    ConnectorDiscoverResponse,
    ConnectorIngestRequest,
    ConnectorIngestResponse,
    ConnectorListResponse,
    ConnectorResourceResponse,
    ProbeRequest,
    ProbeResponse,
    ServicePreviewRequest,
    ServicePreviewResponse,
    service_credential_from_request,
)
from app.platform.ratelimit import limiter
from app.platform.service_auth import (
    credential_or_422,
    custom_credential_header_name,
    url_query_token,
)
from app.platform.service_endpoints import (
    CrossOriginEndpointError,
    assert_endpoints_stay_on_origin,
)
from app.platform.security import (
    PROBE_TIMEOUT,
    SSRFError,
    make_safe_client,
    validate_url_for_ssrf,
)
from app.platform.dataset_origin import service_layer_identity
from app.standards.ogc.errors import (
    ERROR_RESPONSES_WRITE,
    PROBLEM_RESPONSE,
    RATE_LIMIT_RESPONSE,
)

logger = structlog.stdlib.get_logger(__name__)
IngestionError = get_catalog_port().ingestion_error_class()

router = APIRouter(
    prefix="/services", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE
)

_CONNECTOR_OPERATION_TIMEOUT_SECONDS = 30.0
_CONNECTOR_OPERATION_RESPONSES = {
    502: {
        **PROBLEM_RESPONSE,
        "description": "Bad gateway — connector provider failed",
    },
    504: {
        **PROBLEM_RESPONSE,
        "description": "Gateway timeout — connector provider timed out",
    },
}
_SENSITIVE_CONNECTOR_KEY_SUFFIXES = frozenset(
    {
        "accesskey",
        "accesskeyid",
        "authorization",
        "authheader",
        "bearer",
        "credential",
        "credentials",
        "secret",
        "secretref",
        "password",
        "passphrase",
        "token",
        "accesstoken",
        "refreshtoken",
        "apikey",
        "clientsecret",
        "connectionstring",
        "dsn",
        "privatekey",
        "secretaccesskey",
        "subscriptionkey",
    }
)
_SENSITIVE_CONNECTOR_EXACT_KEYS = frozenset(
    {
        "auth",
        "credential",
        "credentials",
    }
)
_SENSITIVE_CONNECTOR_KEY_WORDS = frozenset({"password", "secret", "token"})


def _is_sensitive_connector_key(key: object) -> bool:
    raw = str(key)
    text = "".join(
        (" " if index and character.isupper() and raw[index - 1].islower() else "")
        + character
        for index, character in enumerate(raw)
    ).lower()
    normalized = "".join(character for character in text if character.isalnum())
    words = {
        word
        for word in "".join(
            character if character.isalnum() else " " for character in text
        ).split()
    }
    return bool(
        words & _SENSITIVE_CONNECTOR_KEY_WORDS
        or normalized in _SENSITIVE_CONNECTOR_EXACT_KEYS
        or any(
            normalized.endswith(marker) for marker in _SENSITIVE_CONNECTOR_KEY_SUFFIXES
        )
    )


def _connector_or_404(connector_name: str):  # type: ignore[no-untyped-def]
    extension = get_connector_extension()
    if connector_name not in {
        definition.name for definition in extension.list_connectors()
    }:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )
    return extension


async def _connector_credentials(
    db: AsyncSession,
    connector_name: str,
    credential_id: str | None,
):  # type: ignore[no-untyped-def]
    if credential_id is None:
        return None
    credential = await get_connector_extension().get_credential_ref(
        db, connector_name, credential_id
    )
    if credential is None or credential.connector_name != connector_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector credential not found",
        )
    return credential


def _metadata_contains_secret(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if _is_sensitive_connector_key(key):
                return True
            if _metadata_contains_secret(nested):
                return True
    elif isinstance(value, list):
        return any(_metadata_contains_secret(item) for item in value)
    elif isinstance(value, str):
        return has_url_credentials(value)
    return False


def _reject_inline_connector_secrets(config: dict[str, object]) -> None:
    """Require connector secrets to travel only through opaque credential refs."""
    if _metadata_contains_secret(config):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Connector config cannot contain inline secrets; use credential_id "
                "to reference stored credentials"
            ),
        )


def _validate_connector_resources(resources: object) -> list[ConnectorResourceResponse]:
    """Turn overlay DTOs into the public contract before audit or commit.

    Overlay identifiers are untrusted provider output.  Only an API-safe opaque
    handle crosses the core boundary; provider URLs (especially signed URLs)
    must stay inside the overlay.
    """
    try:
        resource_list = list(resources)  # type: ignore[arg-type]
        if any(
            _metadata_contains_secret(
                {
                    "resource_id_value": resource.id,
                    "resource_name_value": resource.name,
                    "resource_kind_value": resource.kind,
                    "resource_metadata_value": resource.metadata,
                }
            )
            for resource in resource_list
        ):
            raise ValueError("secret-bearing connector resource")
        return [
            ConnectorResourceResponse(
                id=resource.id,
                name=resource.name,
                kind=resource.kind,
                metadata=resource.metadata,
            )
            for resource in resource_list
        ]
    except (AttributeError, TypeError, ValidationError, ValueError) as exc:
        logger.error("Connector returned an invalid discovery resource")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Connector returned invalid discovery metadata",
        ) from exc


def _validate_connector_job(job_id: object) -> ConnectorIngestResponse:
    """Validate provider output before writing its dispatch audit event."""
    try:
        if isinstance(job_id, str) and has_url_credentials(job_id):
            raise ValueError("secret-bearing connector job handle")
        return ConnectorIngestResponse(job_id=job_id)  # type: ignore[arg-type]
    except (TypeError, ValidationError, ValueError) as exc:
        logger.error("Connector returned an invalid ingest job handle")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Connector returned an invalid ingest job handle",
        ) from exc


@router.get(
    "/connectors", response_model=ConnectorListResponse, include_in_schema=False
)
@router.get("/connectors/", response_model=ConnectorListResponse)
async def list_connectors_endpoint(
    _user: Identity = Depends(require_permission("upload")),
) -> ConnectorListResponse:
    """List persistent connectors supplied by an installed overlay.

    Community's no-op extension returns an empty list; one-shot WFS, OGC API,
    ArcGIS, and STAC imports remain on their existing free endpoints.
    """
    return ConnectorListResponse(
        connectors=[
            ConnectorDefinitionResponse(
                name=item.name,
                display_name=item.display_name,
                config_schema=item.config_schema,
                supports_credentials=item.supports_credentials,
                supports_scheduled_sync=item.supports_scheduled_sync,
            )
            for item in get_connector_extension().list_connectors()
        ]
    )


@router.post(
    "/connectors/{connector_name}/discover",
    response_model=ConnectorDiscoverResponse,
    responses=_CONNECTOR_OPERATION_RESPONSES,
    include_in_schema=False,
)
@router.post(
    "/connectors/{connector_name}/discover/",
    response_model=ConnectorDiscoverResponse,
    responses=_CONNECTOR_OPERATION_RESPONSES,
)
async def discover_connector_resources_endpoint(
    connector_name: str,
    body: ConnectorDiscoverRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> ConnectorDiscoverResponse:
    """Validate connector config and discover non-secret source resources."""
    extension = _connector_or_404(connector_name)
    _reject_inline_connector_secrets(body.config)
    try:
        config = await extension.validate_config(connector_name, body.config)
        credential = await _connector_credentials(
            db, connector_name, body.credential_id
        )
        resources = await asyncio.wait_for(
            extension.discover_resources(db, connector_name, credential, config),
            timeout=_CONNECTOR_OPERATION_TIMEOUT_SECONDS,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connector configuration",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Connector discovery timed out",
        ) from exc
    except Exception as exc:  # broad: isolate untrusted connector extension failures
        logger.error(
            "Connector discovery failed",
            connector=connector_name,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Connector discovery failed",
        ) from exc

    public_resources = _validate_connector_resources(resources)

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="connector.discover",
            resource_type="connector",
            details={
                "connector": connector_name,
                "resource_count": len(public_resources),
                "used_stored_credential": body.credential_id is not None,
            },
        ),
    )
    await db.commit()
    return ConnectorDiscoverResponse(resources=public_resources)


@router.post(
    "/connectors/{connector_name}/ingest",
    response_model=ConnectorIngestResponse,
    responses=_CONNECTOR_OPERATION_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
@router.post(
    "/connectors/{connector_name}/ingest/",
    response_model=ConnectorIngestResponse,
    responses=_CONNECTOR_OPERATION_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_connector_ingest_endpoint(
    connector_name: str,
    body: ConnectorIngestRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> ConnectorIngestResponse:
    """Dispatch an overlay-owned ingest and return its opaque job id."""
    extension = _connector_or_404(connector_name)
    _reject_inline_connector_secrets(body.config)
    try:
        config = await extension.validate_config(connector_name, body.config)
        credential = await _connector_credentials(
            db, connector_name, body.credential_id
        )
        job_id = await asyncio.wait_for(
            extension.dispatch_ingest(
                db,
                connector_name,
                credential,
                body.resource_id,
                config,
                str(user.id),
            ),
            timeout=_CONNECTOR_OPERATION_TIMEOUT_SECONDS,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connector configuration",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Connector ingest dispatch timed out",
        ) from exc
    except Exception as exc:  # broad: isolate untrusted connector extension failures
        logger.error(
            "Connector ingest dispatch failed",
            connector=connector_name,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Connector ingest dispatch failed",
        ) from exc

    public_response = _validate_connector_job(job_id)

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="connector.ingest_dispatch",
            resource_type="connector",
            details={
                "connector": connector_name,
                # Resource handles are validated as API-safe and opaque. Keep a
                # deterministic correlation value without persisting even that
                # provider-controlled handle in the audit log.
                "resource_id_sha256": hashlib.sha256(
                    body.resource_id.encode("utf-8")
                ).hexdigest(),
                "used_stored_credential": body.credential_id is not None,
            },
        ),
    )
    await db.commit()
    return public_response


async def _probe_audit_fail(
    db: AsyncSession,
    user_id: uuid.UUID,
    url: str,
    result: str,
    status_code: int,
    detail: str | dict[str, str],
    **extra,
) -> None:
    """Audit-log a probe failure and raise HTTPException.

    ``detail`` is a plain string for every refusal this door has always made,
    and a coded object for the credential-policy one (fix(#1746 B2b review
    r7)), which reuses the shape and the code the preview and commit doors
    return so a client maps one thing rather than two.
    """
    safe_url = redact_url_credentials(url)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="probe_service",
            resource_type="service_url",
            details={"url": safe_url, "result": result, **extra},
        ),
    )
    await db.commit()
    raise HTTPException(status_code=status_code, detail=detail)


def _preview_service_format(service_type: str) -> str | None:
    """The canonical format a preview's human service label resolves to.

    fix(#1746): the credential policy is chosen by the format, not the label,
    because that is what says whether the credential becomes a header or a
    query parameter. An unrecognized label answers None, which composes no
    header and leaves the "Unsupported service type" refusal where it already
    lives, in ``build_gdal_source``.
    """
    try:
        _, source_format = get_catalog_port().resolve_service_type(service_type)
    except (ValueError, KeyError, IngestionError):
        return None
    return source_format


async def _fetch_ogcapi_collection_srid(
    base_url: str, layer_name: str, credential: ServiceCredential | None
) -> int | None:
    """Fetch OGC API collection metadata and parse URI-form CRS to EPSG.

    SMOKE-v1013-F2: ogrinfo on an OGC API collection often returns no
    coordinateSystem because GeoJSON feature responses don't carry a CRS
    (assumed CRS84). The collection metadata DOES expose URI-form CRS via
    its ``crs`` array (e.g. ``http://www.opengis.net/def/crs/OGC/1.3/CRS84``).
    Parse the first entry through ``parse_crs_uri`` so preview displays
    ``EPSG:4326`` rather than ``Unknown``.

    Returns None on any failure — the preview will fall back to the user
    seeing the CRS Override field (existing UX).

    SSRF: base_url has already been validated upstream as the probe URL.
    The collection URL is constructed by appending ``/collections/{name}``
    (no user-controlled path components other than layer_name from the
    probe's known_layer_names allowlist).

    fix(#1756 codex round 8): this carries the same service credential the two
    probe adapters carry and so composes it the same way, through the shared
    builder, and declares a service-chosen header name to the client so a
    cross-origin redirect cannot forward it.
    """
    collection_url = urljoin(
        base_url if base_url.endswith("/") else base_url + "/",
        f"collections/{layer_name}",
    )
    headers: dict[str, str] = {"Accept": "application/json"}
    try:
        pair = build_credential_header(credential)
        if pair is not None:
            headers[pair[0]] = pair[1]
        async with make_safe_client(
            timeout=PROBE_TIMEOUT,
            credential_header=custom_credential_header_name(credential),
        ) as client:
            response = await client.get(
                collection_url, headers=headers, params={"f": "json"}
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError, SSRFError) as exc:
        # SSRFError joins the two on the same reasoning as the rest of this
        # helper: the CRS fallback is best effort and its failure costs the
        # user the CRS Override field, not the preview. A refused redirect hop
        # — blocked address, or a cross-origin one that would have forwarded a
        # service-chosen credential header — is one more way not to answer.
        logger.debug(
            "OGC API collection CRS fallback fetch failed",
            url=collection_url,
            error=str(exc),
        )
        return None

    if not isinstance(data, dict):
        return None

    # Try ``storageCrs`` (recommended) then ``crs`` array (advertised CRS list).
    storage_crs = data.get("storageCrs")
    if isinstance(storage_crs, str):
        srid = parse_crs_uri(storage_crs)
        if srid is not None:
            return srid

    crs_list = data.get("crs")
    if isinstance(crs_list, list):
        for entry in crs_list:
            if isinstance(entry, str):
                srid = parse_crs_uri(entry)
                if srid is not None:
                    return srid
    return None


async def _fail_preview(
    db: AsyncSession, user_id: uuid.UUID, url: str, layer: str
) -> NoReturn:
    """Log audit and raise 502 for a failed service preview."""
    safe_url = redact_url_credentials(url)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="preview_service_layer",
            resource_type="service_url",
            details={"url": safe_url, "layer": layer, "result": "ogrinfo_failed"},
        ),
    )
    await db.commit()
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to preview remote layer. The service may be unavailable or the layer format is unsupported.",
    )


async def _create_preview_job(
    db: AsyncSession,
    request: ServicePreviewRequest,
    preview_data: dict,
    user_id: uuid.UUID,
    *,
    source_url: str | None = None,
    layer_id: int | None = None,
) -> IngestJob:
    """Create the pending IngestJob for a successful preview, audit, and commit.

    Stores source_columns and geometry_type from preview so that ingest_service
    can (a) skip geometry flags for non-spatial tables, and (b) use them as a
    column_info fallback when the data table has no attribute columns.

    ``source_url``/``layer_id`` override the request values so the commit step
    ingests the exact resource that was previewed. This matters for ArcGIS:
    the preview normalizes an embedded-layer URL (".../FeatureServer/0") into a
    base URL + effective layer id, so persisting the original request would make
    the ingest worker rebuild a wrong ".../FeatureServer/0/0/query" (or a None
    layer when the id came only from the URL) — a preview that imports cleanly.
    """
    effective_url = source_url if source_url is not None else request.url
    effective_layer_id = layer_id if layer_id is not None else request.layer_id
    safe_request_url = redact_url_credentials(request.url)
    job = IngestJob(
        source_filename=request.layer_title or request.layer_name,
        source_url=effective_url,
        source_layer=request.layer_name,
        created_by=user_id,
        status="pending",
        user_metadata={
            "service_type": request.service_type,
            "layer_id": effective_layer_id,
            "object_id_field": request.object_id_field,
            "geometry_type": preview_data.get("geometry_type"),
            "source_columns": preview_data.get("columns") or [],
        },
    )
    db.add(job)
    await db.flush()

    logger.info(
        "Service preview success",
        url=safe_request_url,
        layer=request.layer_name,
        job_id=str(job.id),
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="preview_service_layer",
            resource_type="service_url",
            details={
                "url": safe_request_url,
                "layer": request.layer_name,
                "job_id": str(job.id),
                "result": "success",
            },
        ),
    )
    await db.commit()
    return job


def _build_preview_response(
    request: ServicePreviewRequest, preview_data: dict, job: IngestJob
) -> ServicePreviewResponse:
    """Assemble the ServicePreviewResponse from preview data and the job."""
    return ServicePreviewResponse(
        job_id=job.id,
        source_filename=request.layer_title or request.layer_name,
        columns=preview_data["columns"],
        crs=preview_data["srid"],
        geometry_type=preview_data["geometry_type"],
        feature_count=preview_data["feature_count"],
        sample_rows=preview_data["sample_rows"],
        layer_name=request.layer_name
        if request.service_type.startswith("ArcGIS")
        else preview_data["layer_name"],
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
@router.post("/probe", response_model=ProbeResponse, include_in_schema=False)
@router.post("/probe/", response_model=ProbeResponse)
async def probe_service_url(
    request: ProbeRequest,
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ProbeResponse:
    """Probe a remote service URL to detect its type and list available layers.

    Validates the URL against SSRF, detects whether it is a WFS or ArcGIS
    service, and returns a unified layer list. All attempts are audit-logged.
    """
    # feat(#1746): the structured credential is what the layers below take;
    # the flat `token` is its deprecated bearer spelling. Judged first, so a
    # method this service cannot carry, or a value that cannot become a
    # header, never reaches the network or the audit log.
    #
    # fix(#1755 item 2): the probe used to judge nothing, so a WFS token
    # outside the header-token charset probed cleanly and was refused at
    # preview.
    #
    # fix(#1746 B2b review r7): but only what is true whatever gets detected.
    # The first cut selected the policy from the URL shape, and that regressed
    # a working import: `detect_service_type`'s slow path deliberately probes
    # ArcGIS for a URL naming neither FeatureServer nor MapServer, and
    # `probe_arcgis_service` classifies such an endpoint by what its response
    # contains, so a vanity or rewritten ArcGIS URL is ordinary. Its token is
    # percent-encoded into a query and legitimately holds `+` or `/`, which
    # the header charset refuses.
    #
    # So a bearer token is bound to the query-parameter transport here and
    # keeps that wider vocabulary; the header-line policy is applied once an
    # adapter has said the service is a header-auth one, and reaches the
    # caller as the same 422 through `ServiceCredentialUnusable` below. The
    # two methods that exist only as a header are judged now, because no
    # detection outcome makes them sendable to ArcGIS and their inputs must be
    # usable whatever is found.
    credential = service_credential_from_request(request.auth, request.token)
    sends_a_header = (
        credential is not None and credential.method != CredentialMethod.BEARER
    )
    service_credential = credential_or_422(
        credential,
        service_format=(
            WFS_SERVICE_FORMAT
            if sends_a_header and not _looks_like_arcgis(request.url)
            else ARCGIS_SERVICE_FORMAT
        ),
    )
    safe_url = redact_url_credentials(request.url)
    # Step 1: SSRF validation
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        logger.warning("SSRF blocked", url=safe_url, reason=str(exc))
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            "ssrf_blocked",
            status.HTTP_400_BAD_REQUEST,
            str(exc),
            reason=str(exc),
        )

    # Step 2: Probe with httpx client
    # NOTE: No default Authorization header on the client. Each probe function
    # handles auth its own way (ArcGIS via &token= query param, WFS via
    # per-request header). Sending Bearer headers to ArcGIS breaks auth.
    try:
        async with make_safe_client(
            timeout=PROBE_TIMEOUT,
            credential_header=custom_credential_header_name(service_credential),
        ) as client:
            response = await detect_service_type(
                request.url, client, credential=service_credential
            )
            # After detection, because the check is per service type and the
            # probe is what determines it (the round-7 rule).
            await assert_endpoints_stay_on_origin(
                request.url,
                service_format=_preview_service_format(response.service_type),
                has_credential=service_credential is not None,
                credential_header=custom_credential_header_name(service_credential),
            )

    except CrossOriginEndpointError as exc:
        # fix(#1746 B2b review r13): the service describes its own operation
        # endpoints, GDAL follows that description with the credential
        # attached, and no redirect rule can see those requests. Refused here
        # so the caller learns at the step they are on rather than at preview,
        # and refused again in the worker because the document can change.
        logger.warning("Probe cross-origin endpoint", url=safe_url, origin=exc.origin)
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            exc.code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.policy, "field": exc.field},
        )

    except ServiceCredentialUnusable as exc:
        # fix(#1746 B2b review r7): every adapter has had its turn and none
        # claimed the URL, so the credential policy is now the answer rather
        # than a guess made before detection. Same code and same policy-only
        # message the preview and commit doors return, which the client
        # already maps.
        logger.warning("Probe credential unusable", url=safe_url, code=exc.code)
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            exc.code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.policy},
        )

    except SSRFError as exc:
        # fix(#1746): raised mid-probe rather than at the door — either a
        # redirect hop resolving to a blocked address, or a cross-origin hop
        # that would have forwarded a service-chosen credential header. Both
        # are the same answer the pre-flight check gives, and the message is a
        # policy string that carries no part of the credential. Without this
        # clause the broad handler below would rewrite it into a 500.
        logger.warning("SSRF blocked mid-probe", url=safe_url, reason=str(exc))
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            "ssrf_blocked",
            status.HTTP_400_BAD_REQUEST,
            str(exc),
            reason=str(exc),
        )

    except httpx.TimeoutException:
        logger.warning("Probe timeout", url=safe_url)
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            "timeout",
            504,
            "Service didn't respond in time. Check the URL and try again.",
        )

    except ArcGISTokenError as exc:
        logger.warning("ArcGIS token error", url=safe_url, error=str(exc))
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            "auth_required",
            403,
            "This service requires authentication. Provide a valid ArcGIS token and try again.",
            arcgis_code=exc.code,
        )

    except httpx.HTTPStatusError as exc:
        resp_status = exc.response.status_code
        if resp_status in (401, 403):
            logger.warning("Probe auth required", url=safe_url, status=resp_status)
            await _probe_audit_fail(
                db,
                user.id,
                request.url,
                "auth_required",
                403,
                "This service requires authentication. Provide an access token and try again.",
                status=resp_status,
            )
        else:
            logger.warning("Probe remote error", url=safe_url, status=resp_status)
            await _probe_audit_fail(
                db,
                user.id,
                request.url,
                "remote_error",
                502,
                "Remote service returned an error",
                status=resp_status,
            )

    except httpx.TransportError:
        logger.warning("Probe unreachable", url=safe_url)
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            "unreachable",
            502,
            "Could not reach the service. Check the URL and try again.",
        )

    except ServiceNotRecognized as exc:
        logger.info("Probe unrecognized", url=safe_url)
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            "unrecognized",
            status.HTTP_400_BAD_REQUEST,
            str(exc),
        )

    # Step 3: Audit log on success
    logger.info(
        "Probe success",
        url=safe_url,
        service_type=response.service_type,
        layer_count=len(response.layers),
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="probe_service",
            resource_type="service_url",
            details={
                "url": safe_url,
                "result": "success",
                "service_type": response.service_type,
                "layer_count": len(response.layers),
            },
        ),
    )
    await db.commit()

    return response


# ROUTE-01 (Phase 1092): dual-shape decorator — see /probe above.
@router.post("/preview", response_model=ServicePreviewResponse, include_in_schema=False)
@router.post("/preview/", response_model=ServicePreviewResponse)
async def preview_service_layer(
    request: ServicePreviewRequest,
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ServicePreviewResponse:
    """Preview a selected remote layer via ogrinfo and create a pending IngestJob.

    Validates the URL against SSRF, builds the GDAL driver source string,
    runs ogrinfo to extract metadata and sample rows, then creates an IngestJob
    ready for the existing commit flow.
    """
    # feat(#1746): see `probe_service_url`. One conversion, before anything
    # else, so an unsupported method is answered without a preview job or an
    # audit row. Here the service type IS known, so the credential is judged
    # against the transport it is actually about to take: a header for WFS and
    # OGC API Features, a URL query parameter for ArcGIS.
    service_credential = credential_or_422(
        service_credential_from_request(request.auth, request.token),
        service_format=_preview_service_format(request.service_type),
    )
    # ArcGIS is the only branch that reads a bare token: `build_gdal_source`
    # percent-encodes it into the ESRIJSON query. For the header-auth formats
    # this is None and the credential travels as a header instead.
    service_token = url_query_token(service_credential)
    safe_url = redact_url_credentials(request.url)
    # Step 1: SSRF validation
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        logger.warning("SSRF blocked for preview", url=safe_url, reason=str(exc))
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="preview_service_layer",
                resource_type="service_url",
                details={
                    "url": safe_url,
                    "layer": request.layer_name,
                    "result": "ssrf_blocked",
                    "reason": str(exc),
                },
            ),
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Step 1b: Duplicate source detection (ArcGIS and WFS only)
    # Detect if (source_url, source_format, created_by) already exists.
    # The stored URL includes the layer suffix (via enrich_source_url), so
    # we reconstruct the enriched form before querying.
    try:
        _, source_format = get_catalog_port().resolve_service_type(request.service_type)
        # Normalize then re-enrich to match the stored URL form.
        # normalize_arcgis_url extracts the layer_id from the URL if already embedded.
        try:
            base_url, url_layer_id = normalize_arcgis_url(request.url)
        except Exception:  # broad: ArcGIS URL parser can throw varied errors on malformed input; degrade to raw URL
            base_url, url_layer_id = request.url, None
        effective_layer_id = (
            request.layer_id if request.layer_id is not None else url_layer_id
        )
        enriched_url = (
            f"{base_url}/{effective_layer_id}"
            if effective_layer_id is not None
            else base_url
        )
        # fix(#1286): keyed on the canonical structured identity in
        # `origin_ref` — the same (service_type, base url, layer identity)
        # triple that `service_layer_identity` folds a refresh's arguments
        # back into (router_refresh.py `_resolve_service_origin`) — rather
        # than on `origin_uri`'s string spelling. PR #1277's round-11 review
        # found that a writer producing a different spelling of the same
        # origin (a bare base URL instead of `base_url/typename`) silently
        # stopped an origin_uri-keyed guard from catching a duplicate.
        # `origin_ref` round-trips through the same helper on every writer,
        # so it cannot drift the way a hand-composed string can.
        # `source_url` is kept only as the fallback for rows whose structured
        # identity migration 0036 could not backfill. That is NOT simply
        # `origin_uri IS NULL`: for a WFS/OGC row with no surviving ingest
        # job, 0036's service backfill populates `origin_uri` from the old
        # enriched `source_url` while leaving `origin_ref` without `url` or
        # `layer_id` (it had no way to recover the typename). Gating the
        # fallback on origin_uri alone would leave such a row caught by
        # neither branch (codex review, PR #1320) — the fallback fires
        # whenever the structured identity itself is incomplete instead.
        # `source_url` is reachable through the metadata PATCH, so keying the
        # guard on it alone (rather than as this narrow fallback) let an
        # owner edit their way past it.
        canonical_layer_id = service_layer_identity(
            source_format, layer_id=effective_layer_id, layer_name=request.layer_name
        )
        origin_ref_url = Dataset.origin_ref["url"].astext
        origin_ref_layer_id = Dataset.origin_ref["layer_id"].astext
        existing_stmt = (
            select(Dataset.id, Record.title)
            .join(Record, Dataset.record_id == Record.id)
            .where(
                or_(
                    and_(
                        Dataset.origin_ref["service_type"].astext == source_format,
                        origin_ref_url == base_url,
                        origin_ref_layer_id.is_(None)
                        if canonical_layer_id is None
                        else origin_ref_layer_id == canonical_layer_id,
                    ),
                    and_(
                        or_(origin_ref_url.is_(None), origin_ref_layer_id.is_(None)),
                        Dataset.source_url == enriched_url,
                    ),
                ),
                Dataset.source_format == source_format,
                Record.created_by == user.id,
            )
            .limit(1)
        )
        existing = (await db.execute(existing_stmt)).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "duplicate_source",
                    "message": (
                        f"A dataset from this source URL is already registered "
                        f"(existing: '{existing.title}'). To pull the latest data "
                        f"into it, refresh that dataset instead of importing it "
                        f"again; to keep both, register a different layer."
                    ),
                    "existing_dataset_id": str(existing.id),
                    "existing_title": existing.title,
                },
            )
    except HTTPException:
        raise
    except (ValueError, KeyError, IngestionError):
        # resolve_service_type raises IngestionError for unknown service types —
        # skip the duplicate check and let Step 2 handle validation.
        pass

    # Step 2 (ArcGIS): derive the preview from FeatureServer/MapServer REST
    # metadata instead of running ogrinfo through GDAL's ESRIJSON driver. That
    # driver ignores resultRecordCount and paginates the ENTIRE layer (millions
    # of rows on big services), blowing past the subprocess timeout and
    # silently returning an empty preview. The native ?f=json metadata returns
    # all fields + CRS in a single fast call. (preview-fix / demo-bugbash)
    if request.service_type.startswith("ArcGIS"):
        try:
            arcgis_base, url_arcgis_layer_id = normalize_arcgis_url(request.url)
        except Exception:  # broad: malformed ArcGIS URL — degrade to raw URL
            arcgis_base, url_arcgis_layer_id = request.url, None
        arcgis_layer_id = (
            request.layer_id if request.layer_id is not None else url_arcgis_layer_id
        )
        if arcgis_layer_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ArcGIS layer preview requires a layer ID",
            )
        try:
            async with make_safe_client(timeout=15.0) as client:
                preview_data = await fetch_arcgis_layer_preview(
                    arcgis_base,
                    arcgis_layer_id,
                    client,
                    token=service_token,
                )
        except ArcGISTokenError as exc:
            logger.warning("ArcGIS preview token error", url=safe_url, error=str(exc))
            await audit_emit(
                db,
                AuditEvent(
                    user_id=user.id,
                    action="preview_service_layer",
                    resource_type="service_url",
                    details={
                        "url": safe_url,
                        "layer": request.layer_name,
                        "result": "auth_required",
                        "arcgis_code": exc.code,
                    },
                ),
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This service requires authentication. Provide a valid "
                    "ArcGIS token and try again."
                ),
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "ArcGIS preview failed",
                url=safe_url,
                layer=request.layer_name,
                error=str(exc),
            )
            await _fail_preview(db, user.id, request.url, request.layer_name)

        # Persist the normalized base URL + effective layer id (not the original
        # request) so the commit/ingest step targets the exact previewed layer.
        job = await _create_preview_job(
            db,
            request,
            preview_data,
            user.id,
            source_url=arcgis_base,
            layer_id=arcgis_layer_id,
        )
        return _build_preview_response(request, preview_data, job)

    # Step 2: Build GDAL source string (WFS / OGC API)
    try:
        gdal_source, layer_arg = build_gdal_source(
            request.service_type,
            request.url,
            request.layer_name,
            request.layer_id,
            token=service_token,
            order_field=None,
            result_limit=5,
        )
    except ValueError as exc:
        logger.warning(
            "Invalid preview request",
            url=safe_url,
            service_type=request.service_type,
            error=str(exc),
        )
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="preview_service_layer",
                resource_type="service_url",
                details={
                    "url": safe_url,
                    "layer": request.layer_name,
                    "result": "invalid_request",
                    "reason": str(exc),
                },
            ),
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Step 3: Run ogrinfo preview
    try:
        preview_data = await run_service_preview(
            gdal_source, layer_arg, credential=service_credential
        )
    except IngestionError:
        # Step 4: WFS namespace retry -- if layer_name has a colon prefix, retry without it
        if ":" in request.layer_name:
            unqualified = request.layer_name.split(":", 1)[1]
            logger.info(
                "Retrying preview with unqualified layer name",
                original=request.layer_name,
                unqualified=unqualified,
            )
            try:
                retry_source, retry_layer = build_gdal_source(
                    request.service_type,
                    request.url,
                    unqualified,
                    request.layer_id,
                    token=service_token,
                    order_field=None,
                    result_limit=5,
                )
                preview_data = await run_service_preview(
                    retry_source, retry_layer, credential=service_credential
                )
            except (IngestionError, ValueError):
                logger.warning(
                    "Preview failed after namespace retry",
                    url=safe_url,
                    layer=request.layer_name,
                )
                await _fail_preview(db, user.id, request.url, request.layer_name)
        else:
            logger.warning(
                "Preview ogrinfo failed",
                url=safe_url,
                layer=request.layer_name,
            )
            await _fail_preview(db, user.id, request.url, request.layer_name)
    except HTTPException:
        # fix(#1746): run_service_preview now refuses a header-auth token that
        # is outside the base64url charset with a 422, which is an answer and
        # not a pipeline failure. Without this clause the broad handler below
        # would rewrite it into a 500 and lose the policy message.
        raise
    except Exception:  # broad: preview pipeline involves GDAL/OGR/HTTP probes; record failure without aborting the request
        logger.exception(
            "Unexpected error during service preview",
            url=safe_url,
            layer=request.layer_name,
        )
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="preview_service_layer",
                resource_type="service_url",
                details={
                    "url": safe_url,
                    "layer": request.layer_name,
                    "result": "unexpected_error",
                },
            ),
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while previewing the layer.",
        )

    # SMOKE-v1013-F2: OGC API URI-form CRS fallback. ogrinfo against an
    # OGC API collection often returns no coordinateSystem (GeoJSON features
    # don't carry CRS; CRS84 assumed). The COLLECTION METADATA does expose
    # the URI-form CRS — fetch and parse it so preview displays the right
    # EPSG code instead of "Unknown + required override".
    if preview_data.get("srid") is None and request.service_type == "OGC API Features":
        fallback_srid = await _fetch_ogcapi_collection_srid(
            request.url, request.layer_name, service_credential
        )
        if fallback_srid is not None:
            preview_data["srid"] = fallback_srid
            logger.info(
                "OGC API preview CRS resolved via collection metadata",
                url=safe_url,
                layer=request.layer_name,
                srid=fallback_srid,
            )

    # Step 5/6: Create IngestJob, audit-log, and build the response.
    job = await _create_preview_job(db, request, preview_data, user.id)
    return _build_preview_response(request, preview_data, job)


# --------------------------------------------------------------------------
# ArcGIS sign in
# --------------------------------------------------------------------------
#
# This endpoint sends a password to a third party on an authenticated user's
# say-so, which makes it a lockout amplifier and a username oracle before it
# is anything else. ArcGIS locks a built-in account after five failed
# sign-ins in fifteen minutes, so without a limit a GeoLens user who knows a
# colleague's ArcGIS username can lock that colleague out of ArcGIS from
# inside GeoLens, with GeoLens as the proximate cause.
#
# Five controls, in the order they apply:
#
# 1. `create_layers`, the same permission `probe_service_url` requires. A
#    read-only account has no reason to reach this.
# 2. Two slowapi limits, three attempts per fifteen minutes keyed on the user
#    and on (user, portal host). PER PROCESS, and that is the whole reason
#    they are not the enforcement: slowapi's storage is in-memory per uvicorn
#    worker and `docker-compose.prod.yml:294` starts two, so on a stock
#    install these three are three per worker. They are the cheap first layer
#    that keeps a flood off the database.
#
#    fix(#1778): three per worker is now the real number. slowapi scopes a
#    limit by the request PATH unless the limiter is built with
#    key_style="endpoint", and this route is dual-shape, so before that a
#    caller alternating `/signin` with `/signin/` drew on two buckets and put
#    six requests per worker onto control 4 instead of three. Measured, with
#    control 4 raised out of the way: six 200s under the old keying, three
#    200s then three 429s under the new. The key functions below were never
#    the leak; they carry the user id in both.
# 3. Two PostgreSQL advisory locks, per (user, token service) and per ArcGIS
#    account, so the count below cannot be read by two workers at once.
# 4. The same three attempts per fifteen minutes, counted from the ledger rows
#    this endpoint writes, which is shared state on a stock install. Valkey is
#    not: `REDIS_URL` is unset by default, so a Valkey-backed limiter would be
#    no enforcement at all on the installs that most need it. Strictly below
#    Esri's five failed sign-ins in fifteen minutes, so GeoLens can never be
#    what locks an account and the user keeps two attempts of their own.
# 5. One POST per attempt and never a retry, in `arcgis_signin.py`.
#
# fix(#1775): controls 3 and 4 apply in ONE short transaction that commits
# before the credential POST, rather than across it. See `_signin_reserve`.
#
# fix(#1758 codex r1): controls 3 and 4 replaced a process-local set and a
# pair of process-local counters that a two-worker install multiplied by two.
#
# Two names for one slowapi number, because they are two limits rather than
# one. Both keys carry the user id, so while the numbers are equal the
# per-user limit is always the one that binds; the per-portal limit is what
# still holds if the per-user number is ever raised, and naming them apart is
# also what lets each be exercised on its own.
_ARCGIS_SIGNIN_USER_LIMIT = "3/15minutes"
_ARCGIS_SIGNIN_PORTAL_LIMIT = "3/15minutes"


# fix(#1775): the worker-wide `asyncio.Semaphore(4)` that used to stand here
# is GONE, and its removal is the point of this change rather than a
# side-effect. It existed (fix(#1758 codex r17)) because a sign-in held its
# pooled connection across discovery and the mint for up to the 45-second
# network budget, so 13 concurrent sign-ins for distinct scopes could occupy a
# 10+3 pool and time out unrelated API requests; four was a bound on that
# saturation, honestly documented as a bound rather than a fix. The handler
# below now holds no connection across any network phase, so there is nothing
# left for the ceiling to protect, and keeping it would refuse a fifth
# concurrent caller per worker for no remaining reason. What still bounds
# outbound credential POSTs is what always did the work: three attempts per
# ArcGIS account and three per caller and token service, both committed before
# the POST goes out.

_require_create_layers = require_permission("create_layers")


def _arcgis_signin_user_limit(_request: Request | None = None) -> str:
    return _ARCGIS_SIGNIN_USER_LIMIT


def _arcgis_signin_portal_limit(_request: Request | None = None) -> str:
    return _ARCGIS_SIGNIN_PORTAL_LIMIT


async def _rate_limit_scoped_signin(
    request: Request,
    body: ArcGISSignInRequest,
    user: Identity = Depends(_require_create_layers),
) -> Identity:
    """Resolve the caller and stash what the two rate-limit keys need.

    FastAPI resolves dependencies before invoking the (slowapi-wrapped)
    endpoint, so both key functions below always see these values for an
    authenticated request. The body is parsed once per request and shared
    with the handler, so reading the portal URL here costs nothing.
    """
    request.state.arcgis_signin_user_id = str(user.id)
    request.state.arcgis_signin_portal_host = portal_host(body.portal_url)
    return user


def _signin_user_key(request: Request) -> str:
    """Per-user rate-limit key; falls back to the remote address."""
    user_id = getattr(request.state, "arcgis_signin_user_id", None)
    return f"user:{user_id}" if user_id else get_remote_address(request)


def _signin_portal_key(request: Request) -> str:
    """Per-user-and-portal rate-limit key; falls back to the remote address."""
    user_id = getattr(request.state, "arcgis_signin_user_id", None)
    host = getattr(request.state, "arcgis_signin_portal_host", None)
    if user_id and host:
        return f"user:{user_id}:portal:{host}"
    return get_remote_address(request)


# fix(#1758 codex r3): the router-level ERROR_RESPONSES_WRITE covers 4xx and
# 500 only, so the 429 this route raises and the 502/504 mint_portal_token
# returns were undocumented. That is not cosmetic: the generated Python SDK
# returns None or raises UnexpectedStatus for a status the spec does not
# declare, and the TypeScript error union omits it, so a caller cannot
# distinguish "the portal is unreachable" from a bug in their own code.
_ARCGIS_SIGNIN_RESPONSES = {
    429: RATE_LIMIT_RESPONSE,
    502: {
        **PROBLEM_RESPONSE,
        "description": "Bad gateway — the ArcGIS portal could not be reached "
        "or did not answer with a sign-in response",
    },
    504: {
        **PROBLEM_RESPONSE,
        "description": "Gateway timeout — the ArcGIS portal did not respond in time",
    },
}


# ROUTE-01 (Phase 1092): dual-shape decorator, see /probe above.
@router.post(
    "/arcgis/signin",
    response_model=ArcGISSignInResponse,
    responses=_ARCGIS_SIGNIN_RESPONSES,
    include_in_schema=False,
)
@router.post(
    "/arcgis/signin/",
    response_model=ArcGISSignInResponse,
    responses=_ARCGIS_SIGNIN_RESPONSES,
)
@limiter.limit(_arcgis_signin_user_limit, key_func=_signin_user_key)
@limiter.limit(_arcgis_signin_portal_limit, key_func=_signin_portal_key)
async def arcgis_signin(
    request: Request,
    body: ArcGISSignInRequest,
    user: Identity = Depends(_rate_limit_scoped_signin),
    db: AsyncSession = Depends(get_db),
) -> ArcGISSignInResponse:
    """Sign in to an ArcGIS portal and return a short-lived token.

    Asks the portal's own token service for a token valid for 60 minutes and
    returns it. Put that token in the `token` field on probe, preview, commit
    and refresh; an import that runs longer than the token lives fails with a
    credential error and has to start over.

    An account that signs in through an identity provider, or that has
    multifactor authentication turned on, cannot use this. Paste a token or
    an API key instead. A portal on a private network is unreachable either
    way.
    """
    # fix(#1775): the scalars this handler needs, taken off the ORM instance
    # BEFORE the rollback below. `Identity` is the concrete `User` row, and
    # `AsyncSession.rollback()` expires every instance it loaded, so the next
    # attribute read would raise MissingGreenlet rather than reload.
    user_id = user.id
    # fix(#1775): return the pooled connection before any network I/O. The
    # `create_layers` check above left this session in an open transaction,
    # which used to stay checked out through discovery, both advisory locks
    # and the mint — up to the 45-second budget — so 13 concurrent sign-ins
    # for distinct scopes could occupy a 10+3 pool and time out unrelated API
    # requests. Nothing of ours is uncommitted here, so the rollback discards
    # nothing; the later phases reuse this same session object and each checks
    # out a fresh connection for as long as its own short transaction lasts.
    await db.rollback()

    # fix(#1758 codex r7): phase one resolves WHERE the password would go, and
    # every limit below is keyed on that rather than on the address the caller
    # typed. fix(#1758 codex r11): "where" is the installation, not just the
    # hostname, so the scope is host:port/webadaptor: two Enterprise portals
    # can share a name and differ only by port or adaptor path, and they are
    # separate account stores. `authInfo.tokenServicesUrl` may legitimately name another host,
    # so a caller who owns a wildcard domain could otherwise point a hundred
    # portal hostnames at one victim's token service and collect a hundred
    # fresh three-attempt buckets against a single ArcGIS account. Discovery
    # is a credential-free GET under the same deadline, and it runs before any
    # lock is taken so a portal that cannot be resolved costs nobody a lock.
    # It is also why the reservation cannot simply precede discovery: the
    # account scope IS the token-service destination, and only discovery knows
    # it.
    #
    # fix(#1758 codex r8): the resolved identity is held OUTSIDE the block, so
    # the handler below can charge a failure to it. A cancellation is the case
    # that makes this necessary: the deadline converts it at the context
    # boundary rather than where it fired, so a POST cut short by a
    # slow-dripping portal unwinds past the inner handler and lands there.
    # Charged to `unknown` that outcome spent nothing, and a caller could
    # repeat credential POSTs against a real account forever without the
    # ledger ever moving.
    target = signin_target(user_id, "unknown", body.username)
    note: str | None = None
    reserved = False
    try:
        async with open_portal_signin(body.portal_url) as portal:
            # fix(#1758 codex r3): the account lock and both budgets are keyed
            # on the ARCGIS account, not on the GeoLens caller. The username
            # reaches this line and goes no further: what is stored, locked on
            # and counted is the digest.
            target = signin_target(user_id, portal.scope, body.username)
            note = portal.discovery_note

            # fix(#1775): RESERVE. One short transaction takes both locks,
            # reads both budgets, commits the counted attempt and gives the
            # connection back. Everything after this line runs with no session
            # held, and the attempt is already spent, so a cancellation cannot
            # hand ArcGIS a failed password that GeoLens does not count.
            await _signin_reserve(db, user_id, target, note)
            reserved = True

            try:
                minted = await portal.mint(body.username, body.password)
            except ArcGISSignInError as exc:
                await _signin_refusal(db, user_id, target, exc, note, reserved=True)
            except asyncio.CancelledError:
                # fix(#1775): a cancelled task bypasses `mint`'s `except
                # Exception` and the clause above. fix(#1775 audit): on the
                # pinned Starlette the source is a WORKER SHUTDOWN and nothing
                # else — a client hanging up arrives as an `http.disconnect`
                # message a non-streaming route never reads, not as a
                # cancellation. The reservation is what keeps this path safe
                # regardless: the attempt was counted before the POST, so it
                # stands whatever cancelled the request. What this clause
                # recovers is the operator-facing row saying a password went
                # out. It takes a session of its own, is best effort, and
                # re-raises either way — see the helper.
                await _signin_settle_cancelled(user_id, target, note)
                raise

            # fix(#1775): SETTLE. A second short transaction, and the only one
            # that runs after the network. The reservation already counted the
            # attempt, so `reserved=True` keeps this from counting it twice.
            logger.info("ArcGIS sign-in succeeded", token_service_host=target.host)
            await _signin_audit(db, user_id, target, AUDIT_SUCCESS, note, reserved=True)
    except ArcGISSignInError as exc:
        # A mint failure was already turned into an HTTPException above, so
        # what reaches here is a phase-one failure. `unknown` is only ever
        # correct for that: once discovery has named a destination, every
        # outcome after it is charged to that account. `reserved` is carried
        # rather than assumed, so a counted outcome that a later change adds
        # between the reservation and the mint cannot count itself twice.
        await _signin_refusal(db, user_id, target, exc, note, reserved=reserved)
    return ArcGISSignInResponse(token=minted.token, expires_at=minted.expires_at)
