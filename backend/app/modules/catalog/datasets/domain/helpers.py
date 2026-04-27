"""Shared helpers for dataset routers."""

import uuid
from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.schemas import (
    DatasetResponse,
    RasterBandInfo,
    RasterConnect,
    RasterMetadata,
)
from app.modules.catalog.sources.provenance import (
    UNKNOWN_ACTOR_LABEL,
    derive_last_edited,
    resolve_actor,
)
from app.core.geo import extent_to_bbox


async def _load_actor_identities(
    db: AsyncSession,
    actor_ids: Iterable[uuid.UUID | None],
) -> dict[uuid.UUID, Identity]:
    ids = {actor_id for actor_id in actor_ids if actor_id is not None}
    if not ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(ids)))
    users = result.scalars().all()
    return {u.id: u for u in users}


def _build_raster_metadata(
    dataset,
    raster_asset,
    is_admin: bool = False,
    source_count: int | None = None,
    base_url: str | None = None,
) -> RasterMetadata | None:
    """Build RasterMetadata from a RasterAsset ORM object."""
    if raster_asset is None:
        return None

    # Build bands list from band_info JSONB
    bands = []
    if raster_asset.band_info:
        for b in raster_asset.band_info:
            bands.append(
                RasterBandInfo(
                    index=b.get("index", 0),
                    dtype=b.get("dtype", ""),
                    nodata=b.get("nodata"),
                    color_interp=b.get("color_interp"),
                )
            )

    # s3_uri exposed only to admins when storage backend is S3
    s3_uri = None
    if raster_asset.storage_backend == "s3" and is_admin:
        s3_uri = raster_asset.asset_uri

    # Build tile and download URLs
    # tile_url_meta stays relative (used by map rendering in the browser)
    # connect URLs are absolute with api_key placeholder (for external GIS tools)
    tile_url_path = f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png"
    tile_url_meta = tile_url_path

    if base_url:
        tile_url_connect = f"{base_url}{tile_url_path}?api_key={{your_key}}"
    else:
        tile_url_connect = tile_url_path

    # VRT datasets don't have a single COG download
    record_type = getattr(dataset, "record_type", None) or getattr(
        dataset.record, "record_type", None
    )
    is_vrt = record_type == "vrt_dataset"
    if is_vrt:
        download_url = None
    else:
        download_url = f"/api/datasets/{dataset.id}/download/cog"

    connect = RasterConnect(
        download_url=download_url,
        tile_url=tile_url_connect,
        s3_uri=s3_uri,
    )

    return RasterMetadata(
        epsg=raster_asset.epsg,
        res_x=raster_asset.res_x,
        res_y=raster_asset.res_y,
        band_count=raster_asset.band_count,
        nodata=raster_asset.nodata,
        compression=raster_asset.compression,
        width=raster_asset.width,
        height=raster_asset.height,
        size_bytes=raster_asset.size_bytes,
        tile_url=tile_url_meta,
        bands=bands,
        connect=connect,
        status=raster_asset.status,
        vrt_type=raster_asset.vrt_type,
        source_count=source_count,
        resolution_strategy=raster_asset.resolution_strategy,
    )


def dataset_to_response(
    dataset,
    *,
    collections=None,
    actors_by_id: Mapping[uuid.UUID, Identity] | None = None,
    raster_asset=None,
    is_admin: bool = False,
    source_count: int | None = None,
    base_url: str | None = None,
    stac_assets=None,
) -> DatasetResponse:
    """Convert a Dataset ORM object to a DatasetResponse schema."""
    record = dataset.record
    actor_map = actors_by_id or {}

    created_user = actor_map.get(record.created_by) if record.created_by else None
    updated_user = actor_map.get(record.updated_by) if record.updated_by else None

    created_by_display = resolve_actor(
        record.created_by,
        created_user,
        missing_label=UNKNOWN_ACTOR_LABEL,
    )
    last_edited = derive_last_edited(
        created_at=record.created_at,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
        updated_user=updated_user,
    )

    # Build raster metadata for raster_dataset and vrt_dataset records
    raster_metadata = None
    record_type = getattr(record, "record_type", "vector_dataset") or "vector_dataset"
    if record_type in ("raster_dataset", "vrt_dataset") and raster_asset is not None:
        raster_metadata = _build_raster_metadata(
            dataset,
            raster_asset,
            is_admin=is_admin,
            source_count=source_count,
            base_url=base_url,
        )

    return DatasetResponse(
        id=dataset.id,
        record_id=dataset.record_id,
        table_name=dataset.table_name,
        title=record.title,
        summary=record.summary,
        srid=dataset.srid,
        geometry_type=dataset.geometry_type,
        feature_count=dataset.feature_count,
        extent_bbox=extent_to_bbox(record.spatial_extent),
        column_info=dataset.column_info,
        quality_detail=dataset.quality_detail,
        license=record.license,
        source_organization=record.source_organization,
        data_vintage_start=record.temporal_start,
        data_vintage_end=record.temporal_end,
        source_format=dataset.source_format,
        source_filename=dataset.source_filename,
        original_srid=dataset.original_srid,
        current_version=dataset.current_version,
        source_url=dataset.source_url,
        quality_statement=dataset.quality_statement,
        visibility=record.visibility,
        created_by=record.created_by,
        created_by_display=created_by_display,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_edited_by_display=last_edited.display,
        last_edited_at=last_edited.timestamp,
        collections=collections,
        record_status=record.record_status,
        lineage_summary=record.lineage_summary,
        update_frequency=record.update_frequency,
        usage_constraints=record.usage_constraints,
        access_constraints=record.access_constraints,
        sensitivity_classification=record.sensitivity_classification,
        theme_category=record.theme_category,
        owner_org=record.owner_org,
        published_at=record.published_at,
        updated_by=record.updated_by,
        record_type=record_type,
        raster=raster_metadata,
        stac_assets=stac_assets,
        language=getattr(record, "language", None),
    )
