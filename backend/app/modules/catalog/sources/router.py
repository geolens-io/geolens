"""Service probing, preview, and persistent-connector API endpoints."""

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import replace
from typing import NoReturn
from urllib.parse import urlencode, urljoin

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from slowapi.util import get_remote_address
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_redaction import (
    has_url_credentials,
    redact_exception_text,
    redact_url_credentials,
)
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
    credential_header_line,
    requires_header_token_policy,
)
from app.modules.catalog.sources.adapters.arcgis import (
    ARCGIS_SERVICE_FORMAT,
    ArcGISTokenError,
    fetch_arcgis_layer_preview,
    normalize_arcgis_url,
)
from app.modules.catalog.sources.adapters.wfs import WFS_SERVICE_FORMAT
from app.modules.catalog.sources.arcgis_signin import (
    AUDIT_CANCELLED,
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
    _signin_settle_shielded,
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
from app.platform.probe_bounds import bounded_probe_read
from app.platform.service_endpoints import (
    DEFAULT_CHECK_TIMEOUT,
    OGC_JSON_ACCEPT,
    CrossOriginEndpointError,
    EndpointCheckFailedError,
    HrefTooLongError,
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

    Overlay identifiers are untrusted provider output; only an opaque handle
    crosses the core boundary, and provider URLs (especially signed ones)
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
                # Hash, not raw handle: keeps a correlation value without
                # persisting the provider-controlled handle in the audit log.
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

    fix(#1746): ``detail`` is a plain string except for the credential-policy
    refusal, which uses the same coded-object shape as preview/commit so a
    client maps one thing, not two.
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


def _probe_credential_line(
    credential: ServiceCredential | None, service_format: str | None
) -> str | None:
    """The header line the endpoint check sends, or None for a public probe.

    fix(#1746): binds the credential to the just-detected format, not the
    URL's apparent transport.

    fix(#1840): gated on ``requires_header_token_policy``, not on the builder
    answering None — those diverged once ArcGIS gained its own
    ``X-Esri-Authorization`` header. This feeds
    ``assert_endpoints_stay_on_origin``, a WFS/OAPIF-only check about GDAL
    following a header file to a foreign endpoint.
    """
    if credential is None or not requires_header_token_policy(service_format):
        return None
    pair = build_credential_header(replace(credential, service_format=service_format))
    return None if pair is None else credential_header_line(pair)


def _preview_service_format(service_type: str) -> str | None:
    """The canonical format a preview's human service label resolves to.

    fix(#1746): credential policy is keyed by format, not label — that's
    what decides header vs. query param. An unrecognized label returns None,
    leaving the "Unsupported service type" refusal to ``build_gdal_source``.
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

    SMOKE-v1013-F2: ogrinfo often reports no CRS for an OGC API collection
    (GeoJSON responses don't carry one, assumed CRS84); collection metadata
    exposes URI-form CRS via ``crs``, parsed through ``parse_crs_uri``.
    Returns None on any failure — the preview falls back to the CRS
    Override field.

    SSRF: base_url is already validated upstream; the collection URL only
    appends ``/collections/{layer_name}``, drawn from the probe's
    known_layer_names allowlist.

    fix(#1756): carries the same service credential as the probe adapters,
    composed through the shared builder, with a service-chosen header name
    so a cross-origin redirect cannot forward it.

    fix(#1770): reads through ``bounded_probe_read`` under
    ``DEFAULT_CHECK_TIMEOUT``, like the probe adapters and
    ``assert_endpoints_stay_on_origin`` — this fetch has no deadline of its
    own to inherit since it runs after preview has already returned.
    """
    collection_url = urljoin(
        base_url if base_url.endswith("/") else base_url + "/",
        f"collections/{layer_name}",
    )
    # `bounded_probe_read` takes no `params=`; folded into the URL the same
    # way the adapters compose their own query strings.
    collection_url = f"{collection_url}?{urlencode({'f': 'json'})}"
    headers: dict[str, str] = {}
    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            pair = build_credential_header(credential)
            if pair is not None:
                headers[pair[0]] = pair[1]
            async with make_safe_client(
                timeout=PROBE_TIMEOUT,
                credential_header=custom_credential_header_name(credential),
            ) as client:
                body, _ = await bounded_probe_read(
                    client, collection_url, headers=headers, accept=OGC_JSON_ACCEPT
                )
                data = json.loads(body)
    except (
        httpx.HTTPError,
        ValueError,
        RecursionError,
        SSRFError,
        EndpointCheckFailedError,
        TimeoutError,
    ) as exc:
        # Best-effort fallback: any of these just costs the CRS Override
        # field, not the preview. SSRFError covers a refused redirect
        # (blocked address, or cross-origin credential-header leak);
        # EndpointCheckFailedError covers the byte/decoded-size cap.
        # fix(#1770): RecursionError joins them — a JSON depth bomb (900k
        # nested `[`) evades the byte/token caps and raises RecursionError,
        # not ValueError. See ``service_endpoints.py::_parsed_json``.
        logger.debug(
            "OGC API collection CRS fallback fetch failed",
            url=collection_url,
            error=redact_exception_text(exc),
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


# fix(#1755): every typed refusal `run_service_preview` and its callees can
# raise is mapped to a coded 4xx here. The preview pipeline already converts
# each one to an `HTTPException` at its own raise site, so today this map is
# never consulted — it exists so a future edit that breaks one of those
# internal contracts still gets a coded 4xx instead of a 500.
# `TestPreviewEndpoint` pins each branch by mocking `run_service_preview`
# directly, bypassing that internal wrapping.
#
# Ordered specific-to-general: `SSRFError` and `HrefTooLongError` are both
# `ValueError` subclasses, so a generic `ValueError` branch first would
# swallow both under the wrong message.
def _preview_refusal_response(exc: Exception) -> HTTPException | None:
    """Map a typed preview refusal to its coded 4xx, or None if unrecognized.

    None means the caller's own `except Exception` is the last resort for a
    genuine bug, not a guessed status code.

    No branch echoes `str(exc)`: policy strings are fixed per-class (the
    same ones `/probe` already returns), never httpx error text a
    provider's response could shape.
    """
    if isinstance(exc, (CrossOriginEndpointError, EndpointCheckFailedError)):
        # Covers `ItemFetchFailedError` too, a subclass of
        # `EndpointCheckFailedError`.
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": exc.policy, "field": exc.field},
        )
    if isinstance(exc, SSRFError):
        # fix(#1770): `str(exc)` can carry a redirect-chosen hostname
        # (`SSRFResolutionError`), so use the fixed policy phrase instead.
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect target refused by SSRF policy",
        )
    if isinstance(exc, HrefTooLongError):
        # Same "provider named an address this cannot act on" family; the
        # href itself is never in this exception's own message either.
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A service-advertised link exceeded the length limit.",
        )
    if isinstance(exc, ValueError):
        # Remaining source: `build_credential_header` raises `ValueError`
        # with a fixed policy string when a credential reaches it in a shape
        # the door in front should already have refused — never a
        # caller-submitted or provider-chosen value.
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The request could not be processed with the given credential.",
        )
    return None


async def _refuse_preview(
    db: AsyncSession,
    user_id: uuid.UUID,
    url: str,
    layer: str,
    exc: Exception,
) -> None:
    """Audit a typed preview refusal and raise its coded 4xx, or return.

    fix(#1858): extracted so the ArcGIS preview branch (which skips
    ``_run_service_preview_or_refuse``) refuses the same way WFS/OGC API do.
    Returning for an unrecognized class leaves the bare ``raise`` with the
    caller.

    Nothing echoes ``str(exc)``; the audit row records the exception's
    CLASS NAME instead, since ``SSRFResolutionError``'s own message carries
    the redirect-chosen hostname.
    """
    http_exc = _preview_refusal_response(exc)
    if http_exc is None:
        return
    safe_url = redact_url_credentials(url)
    logger.warning(
        "Preview refused",
        url=safe_url,
        layer=layer,
        reason_class=type(exc).__name__,
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="preview_service_layer",
            resource_type="service_url",
            details={
                "url": safe_url,
                "layer": layer,
                "result": "refused",
                "reason_class": type(exc).__name__,
            },
        ),
    )
    await db.commit()
    raise http_exc from None


async def _run_service_preview_or_refuse(
    db: AsyncSession,
    user_id: uuid.UUID,
    url: str,
    layer: str,
    gdal_source: str,
    layer_arg: str,
    *,
    credential: ServiceCredential | None,
) -> dict:
    """`run_service_preview`, with every typed refusal mapped before it escapes.

    `IngestionError` and `HTTPException` pass through unchanged:
    `IngestionError` triggers the WFS namespace retry, and `HTTPException`
    (the header-token charset refusal `run_service_preview` itself raises,
    #1746) is already a finished answer. Anything else matched by
    `_preview_refusal_response` is audited and raised as the coded
    HTTPException; an unmatched exception is re-raised for the caller's
    broad `except Exception` to turn into a 500.
    """
    try:
        return await run_service_preview(gdal_source, layer_arg, credential=credential)
    except (IngestionError, HTTPException):
        raise
    except Exception as exc:  # broad: classifies every refusal so none falls through
        await _refuse_preview(db, user_id, url, layer, exc)
        raise


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

    Stores source_columns/geometry_type so ingest_service can skip geometry
    flags for non-spatial tables and fall back to column_info when needed.

    ``source_url``/``layer_id`` override the request values so commit ingests
    the exact previewed resource — matters for ArcGIS, where preview
    normalizes an embedded-layer URL into base URL + layer id; persisting
    the raw request would make the worker rebuild a wrong
    ".../FeatureServer/0/0/query".
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


# ROUTE-01: dual-shape decorator — both trailing-slash and no-trailing-slash
# variants register against the same handler. Slash form stays canonical
# (already in OpenAPI); no-slash is a hidden alias closing the 404
# regression from redirect_slashes=False (api/main.py).
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
    # fix(#1746): the structured credential (`request.auth`, `token` is its
    # deprecated bearer spelling) is judged first, ahead of detection, so an
    # unusable method or a header-incompatible value never reaches the
    # network or the audit log. A bearer token stays bound to the wider
    # query-parameter charset (ArcGIS tokens legitimately hold `+`/`/`)
    # because ArcGIS is classified by response content, not URL shape, so a
    # vanity/rewritten ArcGIS URL looks ordinary and its token must still
    # work; the header-line policy applies only once an adapter says the
    # service is header-auth, surfacing as the same 422 via
    # `ServiceCredentialUnusable`.
    credential = service_credential_from_request(request.auth, request.token)
    sends_a_header = (
        credential is not None and credential.method != CredentialMethod.BEARER
    )
    # fix(#1746): bound by METHOD alone, not URL shape — matching
    # `FeatureServer`/`MapServer` anywhere in the URL wrongly refused a WFS
    # at `/FeatureServer/wfs` before detection ran. A header-only method's
    # SHAPE is validated here; whether the detected service can carry that
    # method is answered later by `service_carries_method`.
    service_credential = credential_or_422(
        credential,
        service_format=(
            WFS_SERVICE_FORMAT if sends_a_header else ARCGIS_SERVICE_FORMAT
        ),
    )
    safe_url = redact_url_credentials(request.url)
    # fix(#1848): read off `user` before the release below expires it.
    user_id = user.id
    # fix(#1848): released ABOVE the SSRF check, not below — it awaits
    # `getaddrinfo` in a thread, so an unresponsive resolver would otherwise
    # pin the connection before any probe ran.
    await db.rollback()

    # Step 1: SSRF validation
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        logger.warning("SSRF blocked", url=safe_url, reason=str(exc))
        await _probe_audit_fail(
            db,
            user_id,
            request.url,
            "ssrf_blocked",
            status.HTTP_400_BAD_REQUEST,
            str(exc),
            reason=str(exc),
        )

    # No default Authorization header on the client: each probe function
    # handles auth its own way (ArcGIS via &token=, WFS via per-request
    # header); a default Bearer header would break ArcGIS auth.
    try:
        async with make_safe_client(
            timeout=PROBE_TIMEOUT,
            credential_header=custom_credential_header_name(service_credential),
        ) as client:
            response = await detect_service_type(
                request.url, client, credential=service_credential
            )
            # Checked per service type, after detection determines it.
            detected_format = _preview_service_format(response.service_type)
            await assert_endpoints_stay_on_origin(
                request.url,
                service_format=detected_format,
                # fix(#1746): read WITH the credential — a protected service
                # answers an anonymous read with a 401, telling us nothing
                # about the document GDAL will actually act on.
                credential_line=_probe_credential_line(
                    service_credential, detected_format
                ),
                # fix(#1746): the probe has no deadline of its own, so it
                # takes the shared one — otherwise the client only bounds
                # inactivity, and a description delivered slowly but steadily
                # across up to 20 listing pages holds the request open
                # indefinitely.
                deadline=time.monotonic() + DEFAULT_CHECK_TIMEOUT,
            )

    except (CrossOriginEndpointError, EndpointCheckFailedError) as exc:
        # fix(#1746): the service describes its own operation endpoints,
        # GDAL follows that description with the credential attached, and no
        # redirect rule can see those requests — refused here, and again in
        # the worker since the document can change. Neither the message nor
        # `origin` (cross-origin half only) carries any part of the credential.
        logger.warning(
            "Probe endpoint check refused",
            url=safe_url,
            code=exc.code,
            origin=getattr(exc, "origin", None),
        )
        await _probe_audit_fail(
            db,
            user_id,
            request.url,
            exc.code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.policy, "field": exc.field},
        )

    except ServiceCredentialUnusable as exc:
        # fix(#1746): raised only once every adapter has had its turn and
        # none claimed the URL. Same code/policy-only message the preview
        # and commit doors return, which the client already maps.
        logger.warning("Probe credential unusable", url=safe_url, code=exc.code)
        await _probe_audit_fail(
            db,
            user_id,
            request.url,
            exc.code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.policy},
        )

    except SSRFError as exc:
        # fix(#1746): raised mid-probe — a redirect hop resolving to a
        # blocked address, or a cross-origin hop that would forward a
        # service-chosen credential header. Without this the broad handler
        # below would rewrite it into a 500.
        #
        # fix(#1770): use a fixed message, never `str(exc)`: its
        # `SSRFResolutionError` subclass interpolates the raw, unresolved
        # hostname (provider-chosen, via a mid-probe redirect `Location`
        # header) into the message, and that must not reach the 400 body or
        # the persisted audit reason. The raw text stays only in the log
        # line below, which `_redact_sensitive_fields` already covers.
        ssrf_policy_message = "redirect target refused by SSRF policy"
        logger.warning("SSRF blocked mid-probe", url=safe_url, reason=str(exc))
        await _probe_audit_fail(
            db,
            user_id,
            request.url,
            "ssrf_blocked",
            status.HTTP_400_BAD_REQUEST,
            ssrf_policy_message,
            reason=ssrf_policy_message,
        )

    except httpx.TimeoutException:
        logger.warning("Probe timeout", url=safe_url)
        await _probe_audit_fail(
            db,
            user_id,
            request.url,
            "timeout",
            504,
            "Service didn't respond in time. Check the URL and try again.",
        )

    except ArcGISTokenError as exc:
        logger.warning("ArcGIS token error", url=safe_url, error=str(exc))
        await _probe_audit_fail(
            db,
            user_id,
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
                user_id,
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
                user_id,
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
            user_id,
            request.url,
            "unreachable",
            502,
            "Could not reach the service. Check the URL and try again.",
        )

    except ServiceNotRecognized as exc:
        logger.info("Probe unrecognized", url=safe_url)
        await _probe_audit_fail(
            db,
            user_id,
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
            user_id=user_id,
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
    # fix(#1746): converted before anything else, so an unsupported method is
    # answered without a preview job or audit row. Service type is already
    # known here, so judged against the actual transport: a header for
    # WFS/OGC API Features, a URL query parameter for ArcGIS.
    service_credential = credential_or_422(
        service_credential_from_request(request.auth, request.token),
        service_format=_preview_service_format(request.service_type),
    )
    # ArcGIS is the only branch reading a bare token (`build_gdal_source`
    # percent-encodes it into the ESRIJSON query); header-auth formats get
    # None here and travel as a header instead.
    service_token = url_query_token(service_credential)
    safe_url = redact_url_credentials(request.url)
    # fix(#1848): read off `user` before either release below expires it.
    user_id = user.id
    # fix(#1848): released ABOVE the SSRF check, not below — it awaits
    # `getaddrinfo` in a thread, so an unresponsive resolver would otherwise
    # pin the connection before any preview work.
    await db.rollback()

    # Step 1: SSRF validation
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        logger.warning("SSRF blocked for preview", url=safe_url, reason=str(exc))
        await audit_emit(
            db,
            AuditEvent(
                user_id=user_id,
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

    # Duplicate source detection (ArcGIS and WFS only): the stored URL
    # includes the layer suffix (via enrich_source_url), so reconstruct the
    # enriched form before querying (source_url, source_format, created_by).
    try:
        _, source_format = get_catalog_port().resolve_service_type(request.service_type)
        try:
            base_url, url_layer_id = normalize_arcgis_url(request.url)
        except Exception:  # broad: malformed input; degrade to raw URL
            base_url, url_layer_id = request.url, None
        effective_layer_id = (
            request.layer_id if request.layer_id is not None else url_layer_id
        )
        enriched_url = (
            f"{base_url}/{effective_layer_id}"
            if effective_layer_id is not None
            else base_url
        )
        # fix(#1286): keyed on the structured `origin_ref` (service_type,
        # base_url, layer identity), not `origin_uri`'s string spelling,
        # which can drift across writers and miss a duplicate. `source_url`
        # is kept only as a narrow fallback for rows whose structured
        # identity migration 0036 could not backfill (a WFS/OGC row whose
        # service backfill populated `origin_uri` but left `origin_ref`
        # without url/layer_id, having no typename to recover) — gated on
        # the structured identity being incomplete, not on `origin_uri IS
        # NULL` alone. `source_url` is reachable through the metadata PATCH,
        # so keying the guard on it alone would let an owner edit past it.
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
                Record.created_by == user_id,
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

    # fix(#1848): released again, because the duplicate-source query above
    # re-acquired. Every gate has run and nothing is written yet.
    await db.rollback()

    # ArcGIS: derive the preview from FeatureServer/MapServer REST metadata
    # instead of GDAL's ESRIJSON driver, which ignores resultRecordCount and
    # paginates the ENTIRE layer (millions of rows on big services), blowing
    # past the subprocess timeout and silently returning an empty preview.
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
                    user_id=user_id,
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
        except SSRFError as exc:
            # fix(#1858): caught FIRST — `SSRFError` subclasses `ValueError`,
            # and the tuple below would otherwise misreport a refused
            # redirect hop as `_fail_preview`'s 502 `ogrinfo_failed` (naming
            # a tool that never ran) instead of the correct 400 via
            # `_preview_refusal_response`, matching WFS/OGC API branches.
            await _refuse_preview(db, user_id, request.url, request.layer_name, exc)
            raise  # unreachable: `_preview_refusal_response` maps every `SSRFError`
        except (
            httpx.HTTPError,
            ValueError,
            EndpointCheckFailedError,
            TimeoutError,
        ) as exc:
            # fix(#1770): `bounded_probe_read` can raise
            # EndpointCheckFailedError (bound violation) and TimeoutError
            # (its own asyncio.timeout); both join the pre-existing
            # httpx.HTTPError/ValueError this path already degrades on.
            logger.warning(
                "ArcGIS preview failed",
                url=safe_url,
                layer=request.layer_name,
                error=redact_exception_text(exc),
            )
            await _fail_preview(db, user_id, request.url, request.layer_name)

        # Persist the normalized base URL + effective layer id (not the original
        # request) so the commit/ingest step targets the exact previewed layer.
        job = await _create_preview_job(
            db,
            request,
            preview_data,
            user_id,
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
                user_id=user_id,
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
        preview_data = await _run_service_preview_or_refuse(
            db,
            user_id,
            request.url,
            request.layer_name,
            gdal_source,
            layer_arg,
            credential=service_credential,
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
                preview_data = await _run_service_preview_or_refuse(
                    db,
                    user_id,
                    request.url,
                    request.layer_name,
                    retry_source,
                    retry_layer,
                    credential=service_credential,
                )
            except (IngestionError, ValueError):
                logger.warning(
                    "Preview failed after namespace retry",
                    url=safe_url,
                    layer=request.layer_name,
                )
                await _fail_preview(db, user_id, request.url, request.layer_name)
        else:
            logger.warning(
                "Preview ogrinfo failed",
                url=safe_url,
                layer=request.layer_name,
            )
            await _fail_preview(db, user_id, request.url, request.layer_name)
    except HTTPException:
        # fix(#1746): run_service_preview refuses a header-auth token
        # outside the base64url charset with a 422 — an answer, not a
        # failure. Without this the broad handler below would rewrite it
        # into a 500 and lose the policy message.
        raise
    except Exception:  # broad: GDAL/OGR/HTTP pipeline; record failure, don't abort
        logger.exception(
            "Unexpected error during service preview",
            url=safe_url,
            layer=request.layer_name,
        )
        await audit_emit(
            db,
            AuditEvent(
                user_id=user_id,
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

    # SMOKE-v1013-F2: OGC API URI-form CRS fallback — see
    # _fetch_ogcapi_collection_srid's docstring for why.
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
    job = await _create_preview_job(db, request, preview_data, user_id)
    return _build_preview_response(request, preview_data, job)


# --------------------------------------------------------------------------
# ArcGIS sign in
# --------------------------------------------------------------------------
# This endpoint sends a password to a third party on a user's say-so: a
# lockout amplifier and a username oracle. Esri locks an account after 5
# failed sign-ins in 15 minutes, so without a limit a GeoLens user who knows
# a colleague's ArcGIS username could lock that colleague out from inside
# GeoLens.
#
# Five controls, in order:
# 1. `create_layers` permission (same as `probe_service_url`).
# 2. Two slowapi limits, 3/15min keyed on user and on (user, portal host).
#    PER PROCESS only — slowapi's storage is in-memory per uvicorn worker
#    and prod runs two — so this is a cheap first layer, not enforcement.
#    fix(#1778): a dual-shape route needs key_style="endpoint" or the path
#    joins the key; `/signin` vs `/signin/` drew separate buckets before
#    this fix, doubling the effective rate to 6/worker.
# 3. Two PostgreSQL advisory locks (user+token-service, and ArcGIS account)
#    so the count below can't be read by two workers at once.
# 4. The same 3/15min, counted from the ledger rows this endpoint writes —
#    real, shared enforcement. Not Valkey: `REDIS_URL` is unset by default,
#    so a Valkey-backed limiter would enforce nothing on most installs.
#    Strictly below Esri's 5/15min so GeoLens never causes the lockout.
# 5. One POST per attempt, never a retry (arcgis_signin.py).
#
# fix(#1775): controls 3 and 4 run in ONE short transaction that commits
# before the credential POST, not across it — see `_signin_reserve`.
# fix(#1758): controls 3 and 4 replaced process-local counters that a
# two-worker install multiplied by two.
#
# Two names for one slowapi number: both keys carry the user id, so the
# per-user limit always binds first; the per-portal limit still holds if
# the per-user number is later raised.
_ARCGIS_SIGNIN_USER_LIMIT = "3/15minutes"
_ARCGIS_SIGNIN_PORTAL_LIMIT = "3/15minutes"


# fix(#1775): the worker-wide `asyncio.Semaphore(4)` here is GONE, on
# purpose. It existed (#1758) because a sign-in held its pooled connection
# across discovery and the mint for up to 45s, so 13 concurrent sign-ins
# could occupy a 10+3 pool and time out unrelated requests. The handler
# below now holds no connection across any network phase, so nothing is
# left to protect. What still bounds outbound credential POSTs: 3 attempts
# per ArcGIS account and 3 per caller+token-service, both committed before
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

    FastAPI resolves dependencies before invoking the slowapi-wrapped
    endpoint, so both key functions always see these values. The body is
    parsed once and shared with the handler, so reading the portal URL here
    costs nothing.
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


# fix(#1758): the router-level ERROR_RESPONSES_WRITE covers 4xx and
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
    # fix(#1775): scalars read off the ORM instance BEFORE the rollback
    # below — `AsyncSession.rollback()` expires every loaded instance, so a
    # later attribute read would raise MissingGreenlet.
    user_id = user.id
    # fix(#1775): return the pooled connection before any network I/O.
    # Previously this stayed checked out through discovery, both advisory
    # locks, and the mint (up to 45s), so 13 concurrent sign-ins could
    # occupy a 10+3 pool and time out unrelated requests. Nothing here is
    # uncommitted, so the rollback discards nothing; later phases each
    # check out a fresh connection for their own short transaction.
    await db.rollback()

    # fix(#1758): every limit below is keyed on WHERE the password would go
    # (host:port/webadaptor — two Enterprise portals can share a name and
    # differ only by port/adaptor path, and are separate account stores),
    # not on the address the caller typed. `authInfo.tokenServicesUrl` may
    # legitimately name another host, so without this a caller who owns a
    # wildcard domain could point a hundred portal hostnames at one
    # victim's token service and collect a hundred fresh three-attempt
    # buckets against a single ArcGIS account. Discovery is a
    # credential-free GET, run before any lock is taken (a portal that
    # can't be resolved costs nobody a lock) — also why the reservation
    # can't precede discovery: only discovery knows the scope.
    #
    # The resolved identity is held OUTSIDE the block so a cancellation
    # (converted to a failure at the context boundary, not where it fired)
    # still charges the right account instead of `unknown` — otherwise a
    # caller could repeat credential POSTs against a real account forever
    # without the ledger moving.
    target = signin_target(user_id, "unknown", body.username)
    note: str | None = None
    reserved = False
    try:
        async with open_portal_signin(body.portal_url) as portal:
            # fix(#1758): keyed on the ARCGIS account, not the GeoLens
            # caller — the username goes no further than this line; what's
            # stored, locked on, and counted is the digest.
            target = signin_target(user_id, portal.scope, body.username)
            note = portal.discovery_note

            # fix(#1775): RESERVE — one short transaction takes both locks,
            # reads both budgets, commits the counted attempt, and releases
            # the connection. Everything after runs with no session held;
            # the attempt is already spent, so a cancellation can't hand
            # ArcGIS a failed password GeoLens doesn't count.
            reservation_id = await _signin_reserve(db, user_id, target, note)
            reserved = True

            try:
                minted = await portal.mint(body.username, body.password)
            except ArcGISSignInError as exc:
                try:
                    await _signin_refusal(
                        db,
                        user_id,
                        target,
                        exc,
                        note,
                        reserved=True,
                        attempt_id=reservation_id,
                    )
                except asyncio.CancelledError:
                    # fix(#1825): the refusal's audit write is settlement
                    # too; CancelledError isn't an Exception, so the
                    # helper's rollback-and-retry clause never saw it.
                    await _signin_settle_shielded(
                        user_id,
                        target,
                        exc.audit_result,
                        note,
                        attempt_id=reservation_id,
                        release=db,
                    )
                    raise
            except asyncio.CancelledError:
                # fix(#1775): a cancelled task bypasses `mint`'s `except
                # Exception`. On the pinned Starlette the source is WORKER
                # SHUTDOWN only — a client hangup arrives as
                # `http.disconnect`, never a cancellation. The reservation
                # already counted the attempt, so this path is safe
                # regardless; this clause only recovers the operator-facing
                # row saying a password went out. Best effort, and
                # re-raises either way — see the helper.
                await _signin_settle_shielded(
                    user_id,
                    target,
                    AUDIT_CANCELLED,
                    note,
                    attempt_id=reservation_id,
                    release=db,
                )
                raise

            # fix(#1775): SETTLE. A second short transaction, and the only one
            # that runs after the network. The reservation already counted the
            # attempt, so `reserved=True` keeps this from counting it twice.
            logger.info("ArcGIS sign-in succeeded", token_service_host=target.host)
            try:
                await _signin_audit(
                    db,
                    user_id,
                    target,
                    AUDIT_SUCCESS,
                    note,
                    reserved=True,
                    attempt_id=reservation_id,
                )
            except asyncio.CancelledError:
                # fix(#1825): a shutdown cancellation here left the attempt
                # with no row at all. Re-run through the finaliser the mint
                # window already uses.
                await _signin_settle_shielded(
                    user_id,
                    target,
                    AUDIT_SUCCESS,
                    note,
                    attempt_id=reservation_id,
                    release=db,
                )
                raise
    except ArcGISSignInError as exc:
        # A mint failure already became an HTTPException above, so this is a
        # phase-one failure — `unknown` is only ever correct here.
        # `reserved` is carried, not assumed, so a later-added counted
        # outcome between reservation and mint can't count itself twice.
        await _signin_refusal(db, user_id, target, exc, note, reserved=reserved)
    return ArcGISSignInResponse(token=minted.token, expires_at=minted.expires_at)
