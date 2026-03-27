"""Export API endpoint: download datasets in various formats."""

import os
import re
import shutil
import uuid
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.audit.service import log_action
from app.auth.dependencies import get_current_active_user
from app.auth.models import User
from app.auth.visibility import check_dataset_access
from app.datasets.service import get_dataset
from app.dependencies import get_db
from app.export.ogr import ExportError
from app.export.service import export_dataset

router = APIRouter(prefix="/datasets", tags=["Datasets"])


class ExportFormat(str, Enum):
    gpkg = "gpkg"
    geojson = "geojson"
    shp = "shp"
    csv = "csv"


def _cleanup_export(path: str) -> None:
    """Remove the temporary export directory after response is sent."""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


@router.get("/{dataset_id}/export")
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
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), and CSV formats.
    Optional CRS reprojection, spatial filtering, and attribute filtering.
    """
    # 1. Fetch dataset
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # 2. Visibility check
    await check_dataset_access(db, dataset, dataset_id, user)

    # 3. Parse bbox
    bbox_parsed: list[float] | None = None
    if bbox:
        try:
            parts = bbox.split(",")
            if len(parts) != 4:
                raise ValueError("need 4 values")
            bbox_parsed = [float(p) for p in parts]
            if bbox_parsed[0] >= bbox_parsed[2] or bbox_parsed[1] >= bbox_parsed[3]:
                raise ValueError("invalid bounds: minx must be < maxx and miny < maxy")
        except (ValueError, TypeError) as e:
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

    # 7. Audit log
    await log_action(
        db,
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
