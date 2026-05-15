"""Shared RasterAsset bulk-fetch helpers used by search, OGC, and STAC routers.

Centralizes the column list so adding/renaming RasterAsset columns happens in
one place instead of three near-identical SELECT clauses (post-impl-20260426
KISS-6).
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.raster.models import RasterAsset


def _row_to_meta(row: Any, *, include_vrt: bool, include_generation_id: bool) -> dict:
    """Convert a RasterAsset row to a dict with floats normalized."""
    meta: dict = {
        "band_count": row.band_count,
        "epsg": row.epsg,
        "res_x": float(row.res_x) if row.res_x is not None else None,
        "res_y": float(row.res_y) if row.res_y is not None else None,
        "width": row.width,
        "height": row.height,
        "dtype": row.dtype,
        "nodata": row.nodata,
        "band_info": row.band_info,
        "quicklook_256_uri": row.quicklook_256_uri,
    }
    if include_vrt:
        meta["vrt_type"] = row.vrt_type
        meta["resolution_strategy"] = row.resolution_strategy
    if include_generation_id:
        meta["current_generation_id"] = row.current_generation_id
    return meta


async def fetch_raster_meta_one(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    include_vrt: bool = True,
    include_generation_id: bool = True,
) -> dict | None:
    """Fetch raster metadata for a single dataset. Returns None if no asset row."""
    columns = [
        RasterAsset.band_count,
        RasterAsset.epsg,
        RasterAsset.res_x,
        RasterAsset.res_y,
        RasterAsset.width,
        RasterAsset.height,
        RasterAsset.dtype,
        RasterAsset.nodata,
        RasterAsset.band_info,
        RasterAsset.quicklook_256_uri,
    ]
    if include_vrt:
        columns.extend([RasterAsset.vrt_type, RasterAsset.resolution_strategy])
    if include_generation_id:
        columns.append(RasterAsset.current_generation_id)

    result = await db.execute(
        select(*columns).where(RasterAsset.dataset_id == dataset_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return _row_to_meta(
        row, include_vrt=include_vrt, include_generation_id=include_generation_id
    )


async def fetch_raster_meta_bulk(
    db: AsyncSession,
    dataset_ids: list[uuid.UUID],
    *,
    include_vrt: bool = True,
) -> dict[str, dict]:
    """Bulk-fetch raster metadata for multiple datasets, keyed by str(dataset_id)."""
    if not dataset_ids:
        return {}
    columns = [
        RasterAsset.dataset_id,
        RasterAsset.band_count,
        RasterAsset.epsg,
        RasterAsset.res_x,
        RasterAsset.res_y,
        RasterAsset.width,
        RasterAsset.height,
        RasterAsset.dtype,
        RasterAsset.nodata,
        RasterAsset.band_info,
        RasterAsset.quicklook_256_uri,
    ]
    if include_vrt:
        columns.extend([RasterAsset.vrt_type, RasterAsset.resolution_strategy])

    result = await db.execute(
        select(*columns).where(RasterAsset.dataset_id.in_(dataset_ids))
    )
    return {
        str(row.dataset_id): _row_to_meta(
            row, include_vrt=include_vrt, include_generation_id=False
        )
        for row in result.all()
    }
