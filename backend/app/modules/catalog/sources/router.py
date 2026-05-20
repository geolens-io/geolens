"""Service probing and preview API endpoints."""

import uuid
from typing import NoReturn
from urllib.parse import urljoin

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.crs_uri import parse_crs_uri
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.core.dependencies import get_db
from app.platform.jobs.models import IngestJob
from app.platform.extensions import get_catalog_port
from app.modules.catalog.sources.adapters.arcgis import (
    ArcGISTokenError,
    normalize_arcgis_url,
)
from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview
from app.modules.catalog.sources.probe import ServiceNotRecognized, detect_service_type
from app.modules.catalog.sources.schemas import (
    ProbeRequest,
    ProbeResponse,
    ServicePreviewRequest,
    ServicePreviewResponse,
)
from app.modules.catalog.sources.security import (
    PROBE_TIMEOUT,
    SSRFError,
    validate_url_for_ssrf,
)
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

logger = structlog.stdlib.get_logger(__name__)
IngestionError = get_catalog_port().ingestion_error_class()

router = APIRouter(
    prefix="/services", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE
)


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
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="probe_service",
            resource_type="service_url",
            details={"url": url, "result": result, **extra},
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
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
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
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="preview_service_layer",
            resource_type="service_url",
            details={"url": url, "layer": layer, "result": "ogrinfo_failed"},
        ),
    )
    await db.commit()
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to preview remote layer. The service may be unavailable or the layer format is unsupported.",
    )


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
    # Step 1: SSRF validation
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        logger.warning("SSRF blocked", url=request.url, reason=str(exc))
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
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            response = await detect_service_type(
                request.url, client, token=request.token
            )

    except httpx.TimeoutException:
        logger.warning("Probe timeout", url=request.url)
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            "timeout",
            504,
            "Service didn't respond in time. Check the URL and try again.",
        )

    except ArcGISTokenError as exc:
        logger.warning("ArcGIS token error", url=request.url, error=str(exc))
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
            logger.warning("Probe auth required", url=request.url, status=resp_status)
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
            logger.warning("Probe remote error", url=request.url, status=resp_status)
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
        logger.warning("Probe unreachable", url=request.url)
        await _probe_audit_fail(
            db,
            user.id,
            request.url,
            "unreachable",
            502,
            "Could not reach the service. Check the URL and try again.",
        )

    except ServiceNotRecognized as exc:
        logger.info("Probe unrecognized", url=request.url)
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
        url=request.url,
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
                "url": request.url,
                "result": "success",
                "service_type": response.service_type,
                "layer_count": len(response.layers),
            },
        ),
    )
    await db.commit()

    return response


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
    # Step 1: SSRF validation
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        logger.warning("SSRF blocked for preview", url=request.url, reason=str(exc))
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="preview_service_layer",
                resource_type="service_url",
                details={
                    "url": request.url,
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

    # Step 2: Build GDAL source string
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
            url=request.url,
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
                    "url": request.url,
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
                    url=request.url,
                    layer=request.layer_name,
                )
                await _fail_preview(db, user.id, request.url, request.layer_name)
        else:
            logger.warning(
                "Preview ogrinfo failed",
                url=request.url,
                layer=request.layer_name,
            )
            await _fail_preview(db, user.id, request.url, request.layer_name)
    except Exception:  # broad: preview pipeline involves GDAL/OGR/HTTP probes; record failure without aborting the request
        logger.exception(
            "Unexpected error during service preview",
            url=request.url,
            layer=request.layer_name,
        )
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="preview_service_layer",
                resource_type="service_url",
                details={
                    "url": request.url,
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
    if (
        preview_data.get("srid") is None
        and request.service_type == "OGC API Features"
    ):
        fallback_srid = await _fetch_ogcapi_collection_srid(
            request.url, request.layer_name, request.token
        )
        if fallback_srid is not None:
            preview_data["srid"] = fallback_srid
            logger.info(
                "OGC API preview CRS resolved via collection metadata",
                url=request.url,
                layer=request.layer_name,
                srid=fallback_srid,
            )

    # Step 5: Create IngestJob
    # Store source_columns and geometry_type from preview so that ingest_service
    # can (a) skip geometry flags for non-spatial tables, and (b) use as a
    # column_info fallback when the data table has no attribute columns.
    _preview_cols = preview_data.get("columns") or []
    _preview_geom_type = preview_data.get("geometry_type")
    job = IngestJob(
        source_filename=request.layer_title or request.layer_name,
        source_url=request.url,
        source_layer=request.layer_name,
        created_by=user.id,
        status="pending",
        user_metadata={
            "service_type": request.service_type,
            "layer_id": request.layer_id,
            "object_id_field": request.object_id_field,
            "geometry_type": _preview_geom_type,
            "source_columns": _preview_cols,
        },
    )
    db.add(job)
    await db.flush()

    # Step 6: Audit log on success
    logger.info(
        "Service preview success",
        url=request.url,
        layer=request.layer_name,
        job_id=str(job.id),
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="preview_service_layer",
            resource_type="service_url",
            details={
                "url": request.url,
                "layer": request.layer_name,
                "job_id": str(job.id),
                "result": "success",
            },
        ),
    )
    await db.commit()

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
