"""Service probing, preview, and persistent-connector API endpoints."""

import asyncio
import hashlib
import uuid
from typing import NoReturn
from urllib.parse import urljoin

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
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
from app.modules.catalog.sources.adapters.arcgis import (
    ArcGISTokenError,
    fetch_arcgis_layer_preview,
    normalize_arcgis_url,
)
from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview
from app.modules.catalog.sources.probe import ServiceNotRecognized, detect_service_type
from app.modules.catalog.sources.schemas import (
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
)
from app.modules.catalog.sources.security import (
    PROBE_TIMEOUT,
    SSRFError,
    make_safe_client,
    validate_url_for_ssrf,
)
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE, PROBLEM_RESPONSE

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
    detail: str,
    **extra,
) -> None:
    """Audit-log a probe failure and raise HTTPException."""
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


async def _fetch_ogcapi_collection_srid(
    base_url: str, layer_name: str, token: str | None
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
    """
    collection_url = urljoin(
        base_url if base_url.endswith("/") else base_url + "/",
        f"collections/{layer_name}",
    )
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with make_safe_client(timeout=PROBE_TIMEOUT) as client:
            response = await client.get(
                collection_url, headers=headers, params={"f": "json"}
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
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
        async with make_safe_client(timeout=PROBE_TIMEOUT) as client:
            response = await detect_service_type(
                request.url, client, token=request.token
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
        existing_stmt = (
            select(Dataset.id, Record.title)
            .join(Record, Dataset.record_id == Record.id)
            .where(
                Dataset.source_url == enriched_url,
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
                        f"(existing: '{existing.title}'). If you intended to re-import, "
                        f"delete the existing dataset first or register a different layer."
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
                    token=request.token,
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
            token=request.token,
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
            gdal_source, layer_arg, token=request.token
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
                    token=request.token,
                    order_field=None,
                    result_limit=5,
                )
                preview_data = await run_service_preview(
                    retry_source, retry_layer, token=request.token
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
            request.url, request.layer_name, request.token
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
