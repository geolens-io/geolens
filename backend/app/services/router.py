"""Service probing and preview API endpoints."""

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.dependencies import require_permission
from app.auth.models import User
from app.datasets.models import Dataset, Record
from app.dependencies import get_db
from app.ingest.ogr import IngestionError
from app.ingest.tasks import resolve_service_type
from app.jobs.models import IngestJob
from app.services.arcgis import ArcGISTokenError, normalize_arcgis_url
from app.services.preview import build_gdal_source, run_service_preview
from app.services.probe import ServiceNotRecognized, detect_service_type
from app.services.schemas import (
    ProbeRequest,
    ProbeResponse,
    ServicePreviewRequest,
    ServicePreviewResponse,
)
from app.services.security import PROBE_TIMEOUT, SSRFError, validate_url_for_ssrf

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/services", tags=["Datasets"])


async def _fail_preview(db: AsyncSession, user_id, url: str, layer: str) -> None:
    """Log audit and raise 502 for a failed service preview."""
    await log_action(
        session=db,
        user_id=user_id,
        action="preview_service_layer",
        resource_type="service_url",
        details={"url": url, "layer": layer, "result": "ogrinfo_failed"},
    )
    await db.commit()
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to preview remote layer. The service may be unavailable or the layer format is unsupported.",
    )


@router.post("/probe/", response_model=ProbeResponse)
async def probe_service_url(
    request: ProbeRequest,
    user: User = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ProbeResponse:
    """Probe a remote service URL to detect its type and list available layers.

    Validates the URL against SSRF, detects whether it is a WFS or ArcGIS
    service, and returns a unified layer list. All attempts are audit-logged.
    """
    # Step 1: SSRF validation
    try:
        validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        logger.warning("SSRF blocked", url=request.url, reason=str(exc))
        await log_action(
            session=db,
            user_id=user.id,
            action="probe_service",
            resource_type="service_url",
            details={"url": request.url, "result": "ssrf_blocked", "reason": str(exc)},
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

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
        await log_action(
            session=db,
            user_id=user.id,
            action="probe_service",
            resource_type="service_url",
            details={"url": request.url, "result": "timeout"},
        )
        await db.commit()
        raise HTTPException(
            status_code=504,
            detail="Service didn't respond in time. Check the URL and try again.",
        )

    except ArcGISTokenError as exc:
        logger.warning("ArcGIS token error", url=request.url, error=str(exc))
        await log_action(
            session=db,
            user_id=user.id,
            action="probe_service",
            resource_type="service_url",
            details={
                "url": request.url,
                "result": "auth_required",
                "arcgis_code": exc.code,
            },
        )
        await db.commit()
        raise HTTPException(
            status_code=403,
            detail="This service requires authentication. Provide a valid ArcGIS token and try again.",
        )

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code in (401, 403):
            logger.warning("Probe auth required", url=request.url, status=status_code)
            await log_action(
                session=db,
                user_id=user.id,
                action="probe_service",
                resource_type="service_url",
                details={
                    "url": request.url,
                    "result": "auth_required",
                    "status": status_code,
                },
            )
            await db.commit()
            raise HTTPException(
                status_code=403,
                detail="This service requires authentication. Provide an access token and try again.",
            )
        else:
            logger.warning("Probe remote error", url=request.url, status=status_code)
            await log_action(
                session=db,
                user_id=user.id,
                action="probe_service",
                resource_type="service_url",
                details={
                    "url": request.url,
                    "result": "remote_error",
                    "status": status_code,
                },
            )
            await db.commit()
            raise HTTPException(
                status_code=502,
                detail="Remote service returned an error",
            )

    except httpx.TransportError:
        logger.warning("Probe unreachable", url=request.url)
        await log_action(
            session=db,
            user_id=user.id,
            action="probe_service",
            resource_type="service_url",
            details={"url": request.url, "result": "unreachable"},
        )
        await db.commit()
        raise HTTPException(
            status_code=502,
            detail="Could not reach the service. Check the URL and try again.",
        )

    except ServiceNotRecognized as exc:
        logger.info("Probe unrecognized", url=request.url)
        await log_action(
            session=db,
            user_id=user.id,
            action="probe_service",
            resource_type="service_url",
            details={"url": request.url, "result": "unrecognized"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )

    # Step 3: Audit log on success
    logger.info(
        "Probe success",
        url=request.url,
        service_type=response.service_type,
        layer_count=len(response.layers),
    )
    await log_action(
        session=db,
        user_id=user.id,
        action="probe_service",
        resource_type="service_url",
        details={
            "url": request.url,
            "result": "success",
            "service_type": response.service_type,
            "layer_count": len(response.layers),
        },
    )
    await db.commit()

    return response


@router.post("/preview/", response_model=ServicePreviewResponse)
async def preview_service_layer(
    request: ServicePreviewRequest,
    user: User = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ServicePreviewResponse:
    """Preview a selected remote layer via ogrinfo and create a pending IngestJob.

    Validates the URL against SSRF, builds the GDAL driver source string,
    runs ogrinfo to extract metadata and sample rows, then creates an IngestJob
    ready for the existing commit flow.
    """
    # Step 1: SSRF validation
    try:
        validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        logger.warning("SSRF blocked for preview", url=request.url, reason=str(exc))
        await log_action(
            session=db,
            user_id=user.id,
            action="preview_service_layer",
            resource_type="service_url",
            details={
                "url": request.url,
                "layer": request.layer_name,
                "result": "ssrf_blocked",
                "reason": str(exc),
            },
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Step 1b: Duplicate source detection (ArcGIS and WFS only)
    # Detect if (source_url, source_format, created_by) already exists.
    # The stored URL includes the layer suffix (via enrich_source_url), so
    # we reconstruct the enriched form before querying.
    try:
        _, source_format = resolve_service_type(request.service_type)
        # Normalize then re-enrich to match the stored URL form.
        # normalize_arcgis_url extracts the layer_id from the URL if already embedded.
        try:
            base_url, url_layer_id = normalize_arcgis_url(request.url)
        except Exception:
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
    except Exception:
        # If service_type is not ArcGIS/WFS, resolve_service_type raises —
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
        await log_action(
            session=db,
            user_id=user.id,
            action="preview_service_layer",
            resource_type="service_url",
            details={
                "url": request.url,
                "layer": request.layer_name,
                "result": "invalid_request",
                "reason": str(exc),
            },
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
    except Exception:
        logger.exception(
            "Unexpected error during service preview",
            url=request.url,
            layer=request.layer_name,
        )
        await log_action(
            session=db,
            user_id=user.id,
            action="preview_service_layer",
            resource_type="service_url",
            details={
                "url": request.url,
                "layer": request.layer_name,
                "result": "unexpected_error",
            },
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while previewing the layer.",
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
    await log_action(
        session=db,
        user_id=user.id,
        action="preview_service_layer",
        resource_type="service_url",
        details={
            "url": request.url,
            "layer": request.layer_name,
            "job_id": str(job.id),
            "result": "success",
        },
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
