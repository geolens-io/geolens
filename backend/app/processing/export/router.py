"""Export API endpoint: download datasets in various formats."""

import os
import re
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.core.dependencies import get_db
from app.platform.extensions import get_processing_port
from app.processing.export.ogr import ExportError
from app.processing.export.schemas import ExportFormat
from app.processing.export.service import export_dataset

router = APIRouter(prefix="/datasets", tags=["Datasets"])


def _cleanup_export(path: str) -> None:
    """Remove the temporary export directory after response is sent."""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


@router.get("/{dataset_id}/export", response_class=FileResponse)
async def export_dataset_endpoint(
    dataset_id: uuid.UUID,
    request: Request,
    format: ExportFormat = Query(ExportFormat.gpkg, description="Export format"),
    target_crs: str | None = Query(None, description="Target CRS, e.g. EPSG:3857"),
    bbox: str | None = Query(
        None, description="Bounding box: minx,miny,maxx,maxy (WGS84)"
    ),
    where: str | None = Query(
        None, description="Attribute filter expression, e.g. pop > 1000"
    ),
    # IA-P1-01 (Phase 1069): gate on the "export" capability instead of
    # bare authentication. Mirrors router_export.download_cog (:236-245)
    # which already consults the matrix. Closes the asymmetry where an
    # admin revoking "export" from "viewer" still allowed vector export.
    user: Identity = Depends(require_permission("export")),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), and CSV formats.
    Optional CRS reprojection, spatial filtering, and attribute filtering.
    """
    port = get_processing_port()
    # 1. Fetch dataset
    dataset = await port.get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # 2. Visibility check
    await port.check_dataset_access(db, dataset, dataset_id, user)

    # 3. Parse bbox
    from app.modules.catalog.features.service import parse_bbox

    bbox_parsed: list[float] | None = None
    if bbox:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )

    # 4. Validate target_crs
    if target_crs is not None:
        if not re.match(r"^EPSG:\d+$", target_crs, re.IGNORECASE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid target_crs: must match EPSG:<code> (e.g. EPSG:3857)",
            )

    # 5. Check geometry compatibility
    if dataset.geometry_type is None and format in ("gpkg", "geojson", "shp"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot export non-spatial dataset as {format}. Use csv format.",
        )

    # 6. Run export
    try:
        file_path, filename, media_type = await export_dataset(
            dataset.table_name,
            dataset.record.title,
            format,
            target_srs=target_crs,
            bbox=bbox_parsed,
            where=where,
            column_info=dataset.column_info,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ExportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Export failed",
        )
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export temporarily unavailable",
        )

    # 7. Audit log
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="dataset.export",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "format": format,
                "target_crs": target_crs,
                "bbox": bbox,
                "where": where,
            },
            ip_address=request.client.host if request.client else None,
        ),
    )
    await db.commit()

    # 8. Return file with background cleanup
    temp_dir = os.path.dirname(file_path)

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
        background=BackgroundTask(_cleanup_export, temp_dir),
    )
