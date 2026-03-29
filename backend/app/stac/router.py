"""STAC API router: landing page, conformance, collections, items, search.

All endpoints are public (no auth required) -- STAC is for machine
consumption of published data only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.collections.models import Collection, CollectionDataset
from app.config import settings
from app.datasets.models import Dataset, Record
from app.dependencies import get_db
from app.public_urls import get_public_api_url
from app.raster.models import DatasetAsset, RasterAsset
from app.search.service import _build_assets, dataset_to_ogc_record
from app.stac.schemas import (
    StacCatalog,
    StacCollectionListResponse,
    StacConformance,
    StacItemCollection,
    StacLink,
)
from app.stac.serializer import (
    STAC_CONFORMANCE,
    ogc_collection_to_stac_collection,
    ogc_record_to_stac_item,
)
from app.storage import get_storage

stac_router = APIRouter(prefix="/stac", tags=["STAC"])

# Record types eligible for STAC
_STAC_RECORD_TYPES = ("raster_dataset", "vrt_dataset")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_stac_api_url(db: AsyncSession, request: Request) -> str:
    """Resolve the base STAC API URL (e.g. https://host/api/stac)."""
    public_api_url = await get_public_api_url(db, request=request)
    return f"{public_api_url.rstrip('/')}/stac"


async def _fetch_dataset_asset_rows(
    db: AsyncSession,
    dataset_ids: list[uuid.UUID],
) -> dict[str, list[dict]]:
    """Bulk-fetch DatasetAsset rows grouped by dataset ID."""
    if not dataset_ids:
        return {}
    da_stmt = select(DatasetAsset).where(DatasetAsset.dataset_id.in_(dataset_ids))
    da_result = await db.execute(da_stmt)
    by_dataset: dict[str, list[dict]] = {}
    for da in da_result.scalars().all():
        ds_key = str(da.dataset_id)
        by_dataset.setdefault(ds_key, []).append(
            {
                "key": da.key,
                "href": da.href,
                "media_type": da.media_type,
                "roles": da.roles,
                "title": da.title,
                "description": da.description,
            }
        )
    return by_dataset


async def _fetch_raster_meta(
    db: AsyncSession,
    dataset_ids: list[uuid.UUID],
) -> dict[str, dict]:
    """Bulk-fetch raster metadata for a set of dataset IDs."""
    if not dataset_ids:
        return {}
    ra_stmt = select(
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
    ).where(RasterAsset.dataset_id.in_(dataset_ids))
    ra_result = await db.execute(ra_stmt)
    meta: dict[str, dict] = {}
    for row in ra_result.all():
        meta[str(row.dataset_id)] = {
            "band_count": row.band_count,
            "epsg": row.epsg,
            "res_x": float(row.res_x) if row.res_x is not None else None,
            "res_y": float(row.res_y) if row.res_y is not None else None,
            "width": row.width,
            "height": row.height,
            "dtype": row.dtype,
            "nodata": row.nodata,
            "band_info": row.band_info,
        }
    return meta


async def _dataset_to_stac_item(
    db: AsyncSession,
    dataset: Dataset,
    public_api_url: str,
    stac_api_url: str,
    *,
    stac_asset_rows: list[dict] | None = None,
    raster_meta: dict | None = None,
    collection_id: str | None = None,
) -> dict:
    """Convert a Dataset ORM object to a STAC Item dict with presigned URLs."""
    record = dataset.record

    # Build OGC record (base representation)
    ogc_record = dataset_to_ogc_record(
        dataset,
        public_api_url,
        stac_asset_rows=stac_asset_rows,
        raster_meta=raster_meta,
    )

    # Re-build assets with storage_provider for presigned URLs
    try:
        storage = get_storage()
    except RuntimeError:
        storage = None

    ogc_record["assets"] = _build_assets(
        dataset,
        public_api_url,
        stac_asset_rows=stac_asset_rows,
        record_status=record.record_status or "draft",
        storage_backend=settings.storage_provider,
        storage_provider=storage,
    )

    # Look up collection membership if not provided
    if collection_id is None:
        cd_result = await db.execute(
            select(CollectionDataset.collection_id)
            .where(CollectionDataset.dataset_id == dataset.id)
            .limit(1)
        )
        cd_row = cd_result.scalar_one_or_none()
        if cd_row is not None:
            collection_id = str(cd_row)

    return ogc_record_to_stac_item(
        ogc_record,
        collection_id=collection_id,
        stac_api_url=stac_api_url,
    )


def _base_published_raster_query():
    """Base select for published raster/VRT datasets with eager-loaded record."""
    return (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(
            joinedload(Dataset.record).joinedload(Record.keywords),
            joinedload(Dataset.record).joinedload(Record.contacts),
            joinedload(Dataset.record).joinedload(Record.distributions),
        )
        .where(
            Record.record_type.in_(_STAC_RECORD_TYPES),
            Record.record_status == "published",
        )
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@stac_router.get("/", response_model=StacCatalog)
async def landing_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StacCatalog:
    """STAC Catalog landing page."""
    stac_api_url = await _resolve_stac_api_url(db, request)
    return StacCatalog(
        id="geolens-stac",
        title="GeoLens STAC API",
        description="Published raster datasets from GeoLens catalog",
        conformsTo=STAC_CONFORMANCE,
        links=[
            StacLink(rel="self", href=f"{stac_api_url}/", type="application/json"),
            StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
            StacLink(
                rel="data", href=f"{stac_api_url}/collections", type="application/json"
            ),
            StacLink(
                rel="conformance",
                href=f"{stac_api_url}/conformance",
                type="application/json",
            ),
            StacLink(
                rel="search",
                href=f"{stac_api_url}/search",
                type="application/json",
                method="GET",
            ),
        ],
    )


@stac_router.get("/conformance", response_model=StacConformance)
async def conformance() -> StacConformance:
    """STAC API conformance classes."""
    return StacConformance(conformsTo=STAC_CONFORMANCE)


@stac_router.get("/collections", response_model=StacCollectionListResponse)
async def get_collections(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StacCollectionListResponse:
    """List all STAC Collections."""
    stac_api_url = await _resolve_stac_api_url(db, request)

    # Fetch all collections
    coll_result = await db.execute(select(Collection))
    collections = coll_result.scalars().all()

    # Batch spatial + temporal extent for all collections in a single query
    extent_stmt = (
        select(
            CollectionDataset.collection_id,
            func.ST_XMin(func.ST_Extent(Record.spatial_extent)),
            func.ST_YMin(func.ST_Extent(Record.spatial_extent)),
            func.ST_XMax(func.ST_Extent(Record.spatial_extent)),
            func.ST_YMax(func.ST_Extent(Record.spatial_extent)),
            func.min(Record.temporal_start),
            func.max(Record.temporal_end),
        )
        .select_from(Record)
        .join(Dataset, Dataset.record_id == Record.id)
        .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
        .where(
            Record.record_type.in_(["raster_dataset", "vrt_dataset"]),
            Record.record_status == "published",
        )
        .group_by(CollectionDataset.collection_id)
    )
    ext_rows = await db.execute(extent_stmt)
    extent_map: dict[str, tuple] = {}
    for row in ext_rows.all():
        extent_map[str(row[0])] = row[1:]

    stac_collections = []
    for coll in collections:
        ext_row = extent_map.get(str(coll.id))

        spatial_extent = None
        temporal_extent = None
        if ext_row and ext_row[0] is not None:
            spatial_extent = [
                float(ext_row[0]),
                float(ext_row[1]),
                float(ext_row[2]),
                float(ext_row[3]),
            ]
        if ext_row and (ext_row[4] is not None or ext_row[5] is not None):
            t_start = ext_row[4].isoformat() + "T00:00:00Z" if ext_row[4] else None
            t_end = ext_row[5].isoformat() + "T00:00:00Z" if ext_row[5] else None
            temporal_extent = [t_start, t_end]

        stac_coll = ogc_collection_to_stac_collection(
            str(coll.id),
            coll.name,
            coll.description,
            spatial_extent=spatial_extent,
            temporal_extent=temporal_extent,
            stac_api_url=stac_api_url,
        )
        stac_collections.append(stac_coll)

    return StacCollectionListResponse(
        collections=stac_collections,
        links=[
            StacLink(
                rel="self", href=f"{stac_api_url}/collections", type="application/json"
            ),
            StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
        ],
    )


@stac_router.get("/collections/{collection_id}")
async def get_collection(
    collection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a single STAC Collection."""
    stac_api_url = await _resolve_stac_api_url(db, request)

    coll_result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    coll = coll_result.scalar_one_or_none()
    if coll is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
        )

    # Compute extent
    extent_stmt = text("""
        SELECT
            ST_XMin(ST_Extent(r.spatial_extent)),
            ST_YMin(ST_Extent(r.spatial_extent)),
            ST_XMax(ST_Extent(r.spatial_extent)),
            ST_YMax(ST_Extent(r.spatial_extent)),
            MIN(r.temporal_start),
            MAX(r.temporal_end)
        FROM catalog.records r
        JOIN catalog.datasets d ON d.record_id = r.id
        JOIN catalog.collection_datasets cd ON cd.dataset_id = d.id
        WHERE cd.collection_id = :cid
          AND r.record_type IN ('raster_dataset', 'vrt_dataset')
          AND r.record_status = 'published'
    """)
    ext_result = await db.execute(extent_stmt, {"cid": str(coll.id)})
    ext_row = ext_result.one_or_none()

    spatial_extent = None
    temporal_extent = None
    if ext_row and ext_row[0] is not None:
        spatial_extent = [
            float(ext_row[0]),
            float(ext_row[1]),
            float(ext_row[2]),
            float(ext_row[3]),
        ]
    if ext_row and (ext_row[4] is not None or ext_row[5] is not None):
        t_start = ext_row[4].isoformat() + "T00:00:00Z" if ext_row[4] else None
        t_end = ext_row[5].isoformat() + "T00:00:00Z" if ext_row[5] else None
        temporal_extent = [t_start, t_end]

    return ogc_collection_to_stac_collection(
        str(coll.id),
        coll.name,
        coll.description,
        spatial_extent=spatial_extent,
        temporal_extent=temporal_extent,
        stac_api_url=stac_api_url,
    )


@stac_router.get("/items/{item_id}")
async def get_item(
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a single STAC Item by dataset ID."""
    stac_api_url = await _resolve_stac_api_url(db, request)
    public_api_url = await get_public_api_url(db, request=request)

    # Fetch published raster/VRT dataset
    stmt = _base_published_raster_query().where(Dataset.id == item_id)
    result = await db.execute(stmt)
    dataset = result.unique().scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found",
        )

    # Fetch asset rows and raster metadata
    asset_rows = await _fetch_dataset_asset_rows(db, [dataset.id])
    raster_meta = await _fetch_raster_meta(db, [dataset.id])

    return await _dataset_to_stac_item(
        db,
        dataset,
        public_api_url,
        stac_api_url,
        stac_asset_rows=asset_rows.get(str(dataset.id)),
        raster_meta=raster_meta.get(str(dataset.id)),
    )


@stac_router.get("/search", response_model=StacItemCollection)
async def search(
    request: Request,
    db: AsyncSession = Depends(get_db),
    bbox: str | None = Query(None, description="Bounding box: west,south,east,north"),
    datetime: str | None = Query(
        None, alias="datetime", description="OGC datetime interval"
    ),
    collections: str | None = Query(None, description="Comma-separated collection IDs"),
    ids: str | None = Query(None, description="Comma-separated item IDs"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """STAC Item Search endpoint."""
    stac_api_url = await _resolve_stac_api_url(db, request)
    public_api_url = await get_public_api_url(db, request=request)

    # Start with base published raster/VRT query
    stmt = _base_published_raster_query()

    # Filter by ids
    if ids:
        parsed_ids = []
        for id_str in ids.split(","):
            id_str = id_str.strip()
            try:
                parsed_ids.append(uuid.UUID(id_str))
            except ValueError:
                continue
        if parsed_ids:
            stmt = stmt.where(Dataset.id.in_(parsed_ids))
        else:
            # No valid IDs -- return empty
            return StacItemCollection(
                features=[],
                links=[
                    StacLink(
                        rel="self",
                        href=f"{stac_api_url}/search",
                        type="application/json",
                    ),
                    StacLink(
                        rel="root", href=f"{stac_api_url}/", type="application/json"
                    ),
                ],
                numberMatched=0,
                numberReturned=0,
                context={"limit": limit, "returned": 0, "matched": 0},
            )

    # Filter by collections
    if collections:
        parsed_coll_ids = []
        for cid_str in collections.split(","):
            cid_str = cid_str.strip()
            try:
                parsed_coll_ids.append(uuid.UUID(cid_str))
            except ValueError:
                continue
        if parsed_coll_ids:
            stmt = stmt.where(
                Dataset.id.in_(
                    select(CollectionDataset.dataset_id).where(
                        CollectionDataset.collection_id.in_(parsed_coll_ids)
                    )
                )
            )

    # Filter by bbox
    if bbox:
        try:
            parts = bbox.split(",")
            if len(parts) != 4:
                raise ValueError("need 4 values")
            bbox_vals = [float(p) for p in parts]
            if bbox_vals[0] >= bbox_vals[2] or bbox_vals[1] >= bbox_vals[3]:
                raise ValueError("invalid bounds")
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )
        stmt = stmt.where(
            func.ST_Intersects(
                Record.spatial_extent,
                func.ST_MakeEnvelope(
                    bbox_vals[0], bbox_vals[1], bbox_vals[2], bbox_vals[3], 4326
                ),
            )
        )

    # Filter by datetime
    if datetime:
        stmt = _apply_datetime_filter(stmt, datetime)

    # Count total matches
    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(Dataset.id).subquery()
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    datasets = result.unique().scalars().all()

    # Fetch asset rows and raster metadata in bulk
    ds_ids = [d.id for d in datasets]
    asset_rows_map = await _fetch_dataset_asset_rows(db, ds_ids)
    raster_meta_map = await _fetch_raster_meta(db, ds_ids)

    # Convert to STAC Items
    features = []
    for dataset in datasets:
        item = await _dataset_to_stac_item(
            db,
            dataset,
            public_api_url,
            stac_api_url,
            stac_asset_rows=asset_rows_map.get(str(dataset.id)),
            raster_meta=raster_meta_map.get(str(dataset.id)),
        )
        features.append(item)

    # Build links
    links = [
        StacLink(rel="self", href=f"{stac_api_url}/search", type="application/json"),
        StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
    ]
    if offset + limit < total:
        links.append(
            StacLink(
                rel="next",
                href=f"{stac_api_url}/search?offset={offset + limit}&limit={limit}",
                type="application/json",
                method="GET",
            )
        )

    return StacItemCollection(
        features=features,
        links=links,
        numberMatched=total,
        numberReturned=len(features),
        context={"limit": limit, "returned": len(features), "matched": total},
    )


# ---------------------------------------------------------------------------
# Datetime filter helper
# ---------------------------------------------------------------------------


def _apply_datetime_filter(stmt, datetime_str: str):
    """Apply OGC datetime interval filter to a query.

    Supports:
      - Single instant: "2024-01-15T00:00:00Z"
      - Open start: "../2024-12-31T00:00:00Z"
      - Open end: "2024-01-01T00:00:00Z/.."
      - Closed range: "2024-01-01T00:00:00Z/2024-12-31T00:00:00Z"
    """
    from datetime import datetime as dt

    if "/" in datetime_str:
        parts = datetime_str.split("/", 1)
        start_str, end_str = parts[0].strip(), parts[1].strip()

        if start_str != ".." and start_str:
            try:
                start_dt = dt.fromisoformat(start_str.replace("Z", "+00:00"))
                stmt = stmt.where(
                    (Record.temporal_end >= start_dt.date())
                    | (Record.temporal_start >= start_dt.date())
                )
            except ValueError:
                pass

        if end_str != ".." and end_str:
            try:
                end_dt = dt.fromisoformat(end_str.replace("Z", "+00:00"))
                stmt = stmt.where(Record.temporal_start <= end_dt.date())
            except ValueError:
                pass
    else:
        # Single instant -- match records containing that date
        try:
            instant = dt.fromisoformat(datetime_str.strip().replace("Z", "+00:00"))
            stmt = stmt.where(Record.temporal_start <= instant.date())
            stmt = stmt.where(
                (Record.temporal_end >= instant.date())
                | (Record.temporal_end.is_(None))
            )
        except ValueError:
            pass

    return stmt
