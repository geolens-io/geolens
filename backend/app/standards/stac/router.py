"""STAC API router: landing page, conformance, collections, items, search.

Visibility is enforced on all item-returning endpoints (Phase 1061 SEC-S01).
Anonymous users see only public+published raster records; authenticated users
see public + their owned private + any restricted records granted to their roles.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from starlette.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.core.config import settings
from app.core.identity import Identity
import app.core.db as _db_module
from app.modules.auth.dependencies import get_optional_user
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record, RecordKeyword
from app.core.dependencies import get_db
from app.core.public_urls import get_public_api_url
from app.processing.raster.models import DatasetAsset, RasterAsset
from app.standards.ogc.errors import ERROR_RESPONSES_PUBLIC
from app.core.geo import make_bbox_filter
from app.modules.catalog.search.service import build_assets, dataset_to_ogc_record
from app.standards.stac.schemas import (
    StacCatalog,
    StacCollection,
    StacCollectionListResponse,
    StacConformance,
    StacItemCollection,
    StacLink,
)
from app.standards.stac.serializer import (
    STAC_CONFORMANCE,
    ogc_collection_to_stac_collection,
    ogc_record_to_stac_item,
)
from app.platform.storage import get_storage

stac_router = APIRouter(prefix="/stac", tags=["STAC"])

# Record types eligible for STAC
_STAC_RECORD_TYPES = ("raster_dataset", "vrt_dataset")


def _published_raster_filters():
    # Phase 1061 SEC-S01: aggregate queries scoped by CollectionDataset; item
    # bodies remain visibility-gated below via _base_published_raster_query.
    return (
        Record.record_type.in_(_STAC_RECORD_TYPES),
        Record.record_status == "published",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_urls(db: AsyncSession, request: Request) -> tuple[str, str]:
    """Return (stac_api_url, public_api_url) with a single settings lookup."""
    public_api_url = await get_public_api_url(db, request=request)
    stac_api_url = f"{public_api_url.rstrip('/')}/stac"
    return stac_api_url, public_api_url


def _stac_page_url(
    base_href: str, offset: int, limit: int, extra: dict | None = None
) -> str:
    """Build a STAC pagination URL preserving active query params."""
    params: dict[str, str] = {"offset": str(offset), "limit": str(limit)}
    if extra:
        params.update(extra)
    return f"{base_href}?{urlencode(params)}"


def _parse_extent_row(
    ext_row: tuple | None,
) -> tuple[list[float] | None, list[str | None] | None]:
    """Parse a spatial/temporal extent DB row into STAC-ready values."""
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
    return spatial_extent, temporal_extent


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
    """Bulk-fetch raster metadata for a set of dataset IDs.

    Delegates to the shared raster/queries helper (KISS-6). STAC items don't
    need vrt_type/resolution_strategy at this layer, so include_vrt=False.
    """
    from app.processing.raster.queries import fetch_raster_meta_bulk

    return await fetch_raster_meta_bulk(db, dataset_ids, include_vrt=False)


async def _dataset_to_stac_item(
    db: AsyncSession,
    dataset: Dataset,
    public_api_url: str,
    stac_api_url: str,
    *,
    stac_asset_rows: list[dict] | None = None,
    raster_meta: dict | None = None,
    collection_id: str | None = None,
    spatial_extent_geojson: str | None = None,
) -> dict:
    """Convert a Dataset ORM object to a STAC Item dict with presigned URLs.

    ``spatial_extent_geojson`` (PERF-5) lets bulk callers (e.g. STAC items
    page) skip per-dataset Python-side WKB deserialization in
    ``dataset_to_ogc_record`` by precomputing ST_AsGeoJSON in one query.
    """
    record = dataset.record

    # Build OGC record (base representation)
    ogc_record = dataset_to_ogc_record(
        dataset,
        public_api_url,
        stac_asset_rows=stac_asset_rows,
        raster_meta=raster_meta,
        spatial_extent_geojson=spatial_extent_geojson,
    )

    # Re-build assets with storage_provider for presigned URLs
    try:
        storage = get_storage()
    except RuntimeError:
        storage = None

    ogc_record["assets"] = build_assets(
        dataset,
        public_api_url,
        stac_asset_rows=stac_asset_rows,
        record_status=record.record_status or "draft",
        storage_backend=settings.storage_provider,
        storage_provider=storage,
    )

    # Declare projection STAC extension for raster/VRT items that emit proj:* properties.
    # Lives here (not in dataset_to_ogc_record) so OGC Records output stays free of
    # STAC-specific keys.
    record_type = getattr(record, "record_type", "vector_dataset") or "vector_dataset"
    if raster_meta and record_type in ("raster_dataset", "vrt_dataset"):
        has_proj = raster_meta.get("epsg") is not None or bool(
            raster_meta.get("width") and raster_meta.get("height")
        )
        if has_proj:
            ogc_record.setdefault("stac_extensions", []).append(
                "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
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


def _base_published_raster_query(
    user: Identity | None,
    user_roles: set[str],
):
    """Base select for published raster/VRT datasets with visibility enforced.

    Phase 1061 SEC-S01: matches the OGC Features peer router. Anonymous users
    see only public+published records; authenticated users see public + their
    owned private + any restricted records granted to their roles.
    """
    stmt = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(
            selectinload(Dataset.record).selectinload(Record.keywords),
            selectinload(Dataset.record).selectinload(Record.contacts),
            selectinload(Dataset.record).selectinload(Record.distributions),
        )
        .where(
            Record.record_type.in_(_STAC_RECORD_TYPES),
            Record.record_status == "published",
        )
    )
    return apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)


async def _resolve_roles(db: AsyncSession, user: Identity | None) -> set[str]:
    """Resolve user_roles, returning an empty set for anonymous callers."""
    if user is None:
        return set()
    return await get_user_roles(db, user)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@stac_router.get("/", response_model=StacCatalog)
async def landing_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StacCatalog:
    """STAC Catalog landing page."""
    stac_api_url, _ = await _resolve_urls(db, request)

    links = [
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
        StacLink(
            rel="service-desc",
            href=f"{stac_api_url.rsplit('/stac', 1)[0]}/openapi.json",
            type="application/vnd.oai.openapi+json;version=3.0",
        ),
    ]

    # Add rel=child for each collection
    coll_result = await db.execute(select(Collection))
    for coll in coll_result.scalars().all():
        links.append(
            StacLink(
                rel="child",
                href=f"{stac_api_url}/collections/{coll.id}",
                type="application/json",
            )
        )

    return StacCatalog(
        id="geolens-stac",
        title="GeoLens STAC API",
        description="Published raster datasets from GeoLens catalog",
        conformsTo=STAC_CONFORMANCE,
        links=links,
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
    stac_api_url, _ = await _resolve_urls(db, request)

    # Fetch all collections
    coll_result = await db.execute(select(Collection))
    collections = coll_result.scalars().all()

    # Three independent metadata queries -- run concurrently with separate
    # sessions (async sessions are not safe to share across gather tasks).

    async def _fetch_extents() -> dict[str, tuple]:
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
            .where(*_published_raster_filters())
            .group_by(CollectionDataset.collection_id)
        )
        async with _db_module.async_session() as s:
            rows = await s.execute(extent_stmt)
            return {str(r[0]): r[1:] for r in rows.all()}

    async def _fetch_keywords() -> dict[str, list[str]]:
        kw_stmt = (
            select(
                CollectionDataset.collection_id,
                func.array_agg(func.distinct(RecordKeyword.keyword)),
            )
            .select_from(RecordKeyword)
            .join(Record, RecordKeyword.record_id == Record.id)
            .join(Dataset, Dataset.record_id == Record.id)
            .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
            .where(*_published_raster_filters())
            .group_by(CollectionDataset.collection_id)
        )
        async with _db_module.async_session() as s:
            rows = await s.execute(kw_stmt)
            result: dict[str, list[str]] = {}
            for row in rows.all():
                kws = row[1]
                if kws:
                    result[str(row[0])] = sorted([k for k in kws if k])
            return result

    async def _fetch_epsg_codes() -> dict[str, list[int]]:
        epsg_stmt = (
            select(
                CollectionDataset.collection_id,
                func.array_agg(func.distinct(RasterAsset.epsg)),
            )
            .select_from(RasterAsset)
            .join(Dataset, Dataset.id == RasterAsset.dataset_id)
            .join(Record, Record.id == Dataset.record_id)
            .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
            .where(*_published_raster_filters(), RasterAsset.epsg.isnot(None))
            .group_by(CollectionDataset.collection_id)
        )
        async with _db_module.async_session() as s:
            rows = await s.execute(epsg_stmt)
            result: dict[str, list[int]] = {}
            for row in rows.all():
                codes = row[1]
                if codes:
                    result[str(row[0])] = sorted([c for c in codes if c])
            return result

    extent_map, keywords_map, epsg_map = await asyncio.gather(
        _fetch_extents(), _fetch_keywords(), _fetch_epsg_codes()
    )

    stac_collections = []
    for coll in collections:
        coll_key = str(coll.id)
        ext_row = extent_map.get(coll_key)
        spatial_extent, temporal_extent = _parse_extent_row(ext_row)

        summaries = {}
        if coll_key in epsg_map:
            summaries["proj:epsg"] = epsg_map[coll_key]

        stac_coll = ogc_collection_to_stac_collection(
            coll_key,
            coll.name,
            coll.description,
            spatial_extent=spatial_extent,
            temporal_extent=temporal_extent,
            stac_api_url=stac_api_url,
            keywords=keywords_map.get(coll_key),
            summaries=summaries or None,
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


@stac_router.get("/collections/{collection_id}", response_model=StacCollection)
async def get_collection(
    collection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StacCollection:
    """Get a single STAC Collection."""
    stac_api_url, _ = await _resolve_urls(db, request)

    coll_result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    coll = coll_result.scalar_one_or_none()
    if coll is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
        )

    # Three independent metadata queries -- run concurrently with separate sessions.

    async def _fetch_extent() -> tuple | None:
        extent_stmt = (
            select(
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
                CollectionDataset.collection_id == collection_id,
                *_published_raster_filters(),
            )
        )
        async with _db_module.async_session() as s:
            return (await s.execute(extent_stmt)).one_or_none()

    async def _fetch_kw() -> list[str] | None:
        kw_stmt = (
            select(func.distinct(RecordKeyword.keyword))
            .select_from(RecordKeyword)
            .join(Record, RecordKeyword.record_id == Record.id)
            .join(Dataset, Dataset.record_id == Record.id)
            .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
            .where(
                CollectionDataset.collection_id == collection_id,
                *_published_raster_filters(),
            )
        )
        async with _db_module.async_session() as s:
            rows = await s.execute(kw_stmt)
            result = sorted([r[0] for r in rows.all() if r[0]])
            return result or None

    async def _fetch_epsg() -> dict | None:
        epsg_stmt = (
            select(func.distinct(RasterAsset.epsg))
            .join(Dataset, Dataset.id == RasterAsset.dataset_id)
            .join(Record, Record.id == Dataset.record_id)
            .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
            .where(
                CollectionDataset.collection_id == collection_id,
                *_published_raster_filters(),
                RasterAsset.epsg.isnot(None),
            )
        )
        async with _db_module.async_session() as s:
            rows = await s.execute(epsg_stmt)
            codes = sorted([r[0] for r in rows.all() if r[0]])
            return {"proj:epsg": codes} if codes else None

    ext_row, coll_keywords, summaries = await asyncio.gather(
        _fetch_extent(), _fetch_kw(), _fetch_epsg()
    )
    spatial_extent, temporal_extent = _parse_extent_row(ext_row)

    return ogc_collection_to_stac_collection(
        str(coll.id),
        coll.name,
        coll.description,
        spatial_extent=spatial_extent,
        temporal_extent=temporal_extent,
        stac_api_url=stac_api_url,
        keywords=coll_keywords,
        summaries=summaries,
    )


@stac_router.get(
    "/collections/{collection_id}/items",
    response_class=JSONResponse,
    responses={
        200: {"content": {"application/geo+json": {}}},
        **ERROR_RESPONSES_PUBLIC,
    },
)
async def get_collection_items(
    collection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    bbox: str | None = Query(None, description="Bounding box: west,south,east,north"),
    datetime_param: str | None = Query(
        None, alias="datetime", description="OGC datetime interval"
    ),
    limit: int = Query(10, ge=1, le=200),
    offset: int = Query(
        0,
        ge=0,
        description=(
            "Legacy offset-based pagination. Phase 269 H-24 lowered the "
            "max limit to 200 and recommends keyset cursors via the rel=next "
            "link for deep paging."
        ),
    ),
) -> JSONResponse:
    """List STAC Items within a collection."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)

    # Verify collection exists
    coll_result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    if coll_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
        )

    # Base query filtered to this collection
    stmt = _base_published_raster_query().where(
        Dataset.id.in_(
            select(CollectionDataset.dataset_id).where(
                CollectionDataset.collection_id == collection_id
            )
        )
    )

    # Filter by bbox (antimeridian-aware)
    if bbox:
        try:
            parts = bbox.split(",")
            if len(parts) not in (4, 6):
                raise ValueError("need 4 or 6 values")
            bbox_vals = [float(p) for p in parts]
            if len(bbox_vals) == 6:
                bbox_vals = [bbox_vals[0], bbox_vals[1], bbox_vals[3], bbox_vals[4]]
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )
        stmt = stmt.where(make_bbox_filter(Record.spatial_extent, bbox_vals))

    # Filter by datetime
    if datetime_param:
        stmt = _apply_datetime_filter(stmt, datetime_param)

    # Count total
    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(Dataset.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginate
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    datasets = result.unique().scalars().all()

    # Bulk-fetch assets, raster metadata, and spatial-extent GeoJSON concurrently.
    # Bulk ST_AsGeoJSON in PostGIS is faster than per-dataset Python-side
    # to_shape() WKB deserialization in dataset_to_ogc_record (PERF-5).
    ds_ids = [d.id for d in datasets]

    async def _assets():
        async with _db_module.async_session() as s:
            return await _fetch_dataset_asset_rows(s, ds_ids)

    async def _raster():
        async with _db_module.async_session() as s:
            return await _fetch_raster_meta(s, ds_ids)

    async def _extents() -> dict[str, str | None]:
        if not ds_ids:
            return {}
        async with _db_module.async_session() as s:
            stmt = (
                select(
                    Dataset.id,
                    func.ST_AsGeoJSON(Record.spatial_extent, 6).label("geojson"),
                )
                .join(Record, Dataset.record_id == Record.id)
                .where(Dataset.id.in_(ds_ids))
            )
            return {str(row.id): row.geojson for row in (await s.execute(stmt)).all()}

    asset_rows_map, raster_meta_map, extent_geojson_map = await asyncio.gather(
        _assets(), _raster(), _extents()
    )

    features = []
    coll_id_str = str(collection_id)
    for dataset in datasets:
        item = await _dataset_to_stac_item(
            db,
            dataset,
            public_api_url,
            stac_api_url,
            stac_asset_rows=asset_rows_map.get(str(dataset.id)),
            raster_meta=raster_meta_map.get(str(dataset.id)),
            collection_id=coll_id_str,
            spatial_extent_geojson=extent_geojson_map.get(str(dataset.id)),
        )
        features.append(item)

    base_href = f"{stac_api_url}/collections/{collection_id}/items"
    active_params: dict[str, str] = {}
    if bbox:
        active_params["bbox"] = bbox
    if datetime_param:
        active_params["datetime"] = datetime_param

    links = [
        StacLink(
            rel="self",
            href=_stac_page_url(base_href, offset, limit, active_params),
            type="application/geo+json",
        ),
        StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
        StacLink(
            rel="collection",
            href=f"{stac_api_url}/collections/{collection_id}",
            type="application/json",
        ),
    ]
    if offset + limit < total:
        links.append(
            StacLink(
                rel="next",
                href=_stac_page_url(base_href, offset + limit, limit, active_params),
                type="application/geo+json",
            )
        )
    if offset > 0:
        links.append(
            StacLink(
                rel="prev",
                href=_stac_page_url(
                    base_href, max(0, offset - limit), limit, active_params
                ),
                type="application/geo+json",
            )
        )

    result = StacItemCollection(
        features=features,
        links=links,
        numberMatched=total,
        numberReturned=len(features),
        context={"limit": limit, "returned": len(features), "matched": total},
    )
    return Response(content=result.model_dump_json(), media_type="application/geo+json")


async def _build_item_response(
    db: AsyncSession,
    dataset: Dataset,
    public_api_url: str,
    stac_api_url: str,
    *,
    collection_id: str | None = None,
) -> JSONResponse:
    """Fetch assets/raster metadata, convert to STAC Item, return as geo+json."""

    async def _assets():
        async with _db_module.async_session() as s:
            return await _fetch_dataset_asset_rows(s, [dataset.id])

    async def _raster():
        async with _db_module.async_session() as s:
            return await _fetch_raster_meta(s, [dataset.id])

    asset_rows, raster_meta = await asyncio.gather(_assets(), _raster())

    item = await _dataset_to_stac_item(
        db,
        dataset,
        public_api_url,
        stac_api_url,
        stac_asset_rows=asset_rows.get(str(dataset.id)),
        raster_meta=raster_meta.get(str(dataset.id)),
        collection_id=collection_id,
    )
    return JSONResponse(content=item, media_type="application/geo+json")


@stac_router.get("/collections/{collection_id}/items/{item_id}", response_model=None)
async def get_collection_item(
    collection_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a single STAC Item within a collection."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)

    # Verify collection exists
    coll_result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    if coll_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
        )

    # Fetch published raster/VRT dataset within this collection
    stmt = _base_published_raster_query().where(
        Dataset.id == item_id,
        Dataset.id.in_(
            select(CollectionDataset.dataset_id).where(
                CollectionDataset.collection_id == collection_id
            )
        ),
    )
    result = await db.execute(stmt)
    dataset = result.unique().scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in collection"
        )

    return await _build_item_response(
        db, dataset, public_api_url, stac_api_url, collection_id=str(collection_id)
    )


@stac_router.get("/items/{item_id}", response_model=None)
async def get_item(
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a single STAC Item by dataset ID."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)

    stmt = _base_published_raster_query().where(Dataset.id == item_id)
    result = await db.execute(stmt)
    dataset = result.unique().scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )

    return await _build_item_response(db, dataset, public_api_url, stac_api_url)


def _build_search_filters(
    *,
    bbox: str | list[float] | None = None,
    intersects: str | dict | None = None,
    datetime_str: str | None = None,
    ids: str | list[str] | None = None,
    collections: str | list[str] | None = None,
) -> tuple[list, bool]:
    """Build SQLAlchemy filter clauses for STAC search.

    Returns:
        A tuple of (filter_clauses, ids_empty). ids_empty is True when an ids
        parameter was provided but all values were invalid UUIDs, signaling
        that the caller should return an empty result immediately.
    """
    filters = []

    # Filter by ids — accept comma-separated string or list
    if ids:
        id_strings = ids.split(",") if isinstance(ids, str) else ids
        parsed_ids = []
        for id_str in id_strings:
            try:
                parsed_ids.append(uuid.UUID(id_str.strip()))
            except ValueError:
                continue
        if parsed_ids:
            filters.append(Dataset.id.in_(parsed_ids))
        else:
            return [], True

    # Filter by collections — accept comma-separated string or list
    if collections:
        coll_strings = (
            collections.split(",") if isinstance(collections, str) else collections
        )
        parsed_coll_ids = []
        for cid_str in coll_strings:
            try:
                parsed_coll_ids.append(uuid.UUID(cid_str.strip()))
            except ValueError:
                continue
        if parsed_coll_ids:
            filters.append(
                Dataset.id.in_(
                    select(CollectionDataset.dataset_id).where(
                        CollectionDataset.collection_id.in_(parsed_coll_ids)
                    )
                )
            )

    # Filter by intersects (GeoJSON geometry) — accept string or dict
    if intersects:
        if isinstance(intersects, dict):
            intersects_str = json.dumps(intersects)
        else:
            intersects_str = intersects
            try:
                json.loads(intersects_str)  # validate JSON before sending to DB
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid intersects geometry: {e}",
                )
        _geom = func.ST_SetSRID(func.ST_GeomFromGeoJSON(intersects_str), 4326)
        filters.append(Record.spatial_extent.op("&&")(func.ST_Envelope(_geom)))
        filters.append(func.ST_Intersects(Record.spatial_extent, _geom))
    elif bbox:
        # Filter by bbox (only if intersects not provided) — accept string or list
        try:
            if isinstance(bbox, str):
                parts = bbox.split(",")
                if len(parts) not in (4, 6):
                    raise ValueError("need 4 or 6 values")
                bbox_vals = [float(p) for p in parts]
            else:
                bbox_vals = list(bbox)
                if len(bbox_vals) not in (4, 6):
                    raise ValueError("need 4 or 6 values")
            if len(bbox_vals) == 6:
                bbox_vals = [bbox_vals[0], bbox_vals[1], bbox_vals[3], bbox_vals[4]]
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )
        filters.append(make_bbox_filter(Record.spatial_extent, bbox_vals))

    return filters, False


def _build_search_links(
    stac_api_url: str,
    *,
    matched: int,
    returned: int,
    offset: int,
    limit: int,
    bbox: str | list[float] | None = None,
    datetime_str: str | None = None,
    collections: str | list[str] | None = None,
    ids: str | list[str] | None = None,
    intersects: str | dict | None = None,
) -> list[StacLink]:
    """Build pagination and navigation links for STAC search results."""
    search_href = f"{stac_api_url}/search"
    active_params: dict[str, str] = {}
    if bbox:
        active_params["bbox"] = (
            bbox if isinstance(bbox, str) else ",".join(str(v) for v in bbox)
        )
    if datetime_str:
        active_params["datetime"] = datetime_str
    if collections:
        active_params["collections"] = (
            collections if isinstance(collections, str) else ",".join(collections)
        )
    if ids:
        active_params["ids"] = ids if isinstance(ids, str) else ",".join(ids)
    if intersects:
        active_params["intersects"] = (
            intersects if isinstance(intersects, str) else json.dumps(intersects)
        )

    links = [
        StacLink(
            rel="self",
            href=_stac_page_url(search_href, offset, limit, active_params),
            type="application/geo+json",
        ),
        StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
    ]
    if offset + limit < matched:
        links.append(
            StacLink(
                rel="next",
                href=_stac_page_url(search_href, offset + limit, limit, active_params),
                type="application/geo+json",
            )
        )
    if offset > 0:
        links.append(
            StacLink(
                rel="prev",
                href=_stac_page_url(
                    search_href, max(0, offset - limit), limit, active_params
                ),
                type="application/geo+json",
            )
        )

    return links


async def _execute_search(
    db: AsyncSession,
    stac_api_url: str,
    public_api_url: str,
    *,
    bbox: str | list[float] | None = None,
    datetime_str: str | None = None,
    collections: str | list[str] | None = None,
    ids: str | list[str] | None = None,
    intersects: str | dict | None = None,
    limit: int = 10,
    offset: int = 0,
) -> JSONResponse:
    """Shared STAC Item Search logic for GET and POST endpoints.

    Parameters accept both string (from GET query params) and native types
    (from POST JSON body) to avoid unnecessary serialization round-trips.
    """
    # Build filters from search parameters
    filters, ids_empty = _build_search_filters(
        bbox=bbox,
        intersects=intersects,
        datetime_str=datetime_str,
        ids=ids,
        collections=collections,
    )

    # Early return when ids param was given but all values were invalid
    if ids_empty:
        return StacItemCollection(
            features=[],
            links=[
                StacLink(
                    rel="self",
                    href=f"{stac_api_url}/search",
                    type="application/json",
                ),
                StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
            ],
            numberMatched=0,
            numberReturned=0,
            context={"limit": limit, "returned": 0, "matched": 0},
        )

    stmt = _base_published_raster_query()
    for f in filters:
        stmt = stmt.where(f)

    # Filter by datetime
    if datetime_str:
        stmt = _apply_datetime_filter(stmt, datetime_str)

    # Count total matches
    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(Dataset.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    datasets = result.unique().scalars().all()

    # Fetch asset rows, raster metadata, and collection membership concurrently
    ds_ids = [d.id for d in datasets]

    async def _assets():
        async with _db_module.async_session() as s:
            return await _fetch_dataset_asset_rows(s, ds_ids)

    async def _raster():
        async with _db_module.async_session() as s:
            return await _fetch_raster_meta(s, ds_ids)

    async def _coll_membership() -> dict[str, str]:
        if not ds_ids:
            return {}
        cd_stmt = select(
            CollectionDataset.dataset_id, CollectionDataset.collection_id
        ).where(CollectionDataset.dataset_id.in_(ds_ids))
        async with _db_module.async_session() as s:
            cd_result = await s.execute(cd_stmt)
            return {
                str(row.dataset_id): str(row.collection_id) for row in cd_result.all()
            }

    asset_rows_map, raster_meta_map, collection_id_map = await asyncio.gather(
        _assets(), _raster(), _coll_membership()
    )

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
            collection_id=collection_id_map.get(str(dataset.id)),
        )
        features.append(item)

    # Build links
    links = _build_search_links(
        stac_api_url,
        matched=total,
        returned=len(features),
        offset=offset,
        limit=limit,
        bbox=bbox,
        datetime_str=datetime_str,
        collections=collections,
        ids=ids,
        intersects=intersects,
    )

    result = StacItemCollection(
        features=features,
        links=links,
        numberMatched=total,
        numberReturned=len(features),
        context={"limit": limit, "returned": len(features), "matched": total},
    )
    return Response(content=result.model_dump_json(), media_type="application/geo+json")


@stac_router.get(
    "/search",
    response_class=JSONResponse,
    responses={
        200: {"content": {"application/geo+json": {}}},
        **ERROR_RESPONSES_PUBLIC,
    },
)
async def search_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
    bbox: str | None = Query(None, description="Bounding box: west,south,east,north"),
    datetime_param: str | None = Query(
        None, alias="datetime", description="OGC datetime interval"
    ),
    collections: str | None = Query(None, description="Comma-separated collection IDs"),
    ids: str | None = Query(None, description="Comma-separated item IDs"),
    intersects: str | None = Query(
        None, description="GeoJSON geometry for spatial intersection"
    ),
    limit: int = Query(10, ge=1, le=200),
    offset: int = Query(
        0,
        ge=0,
        description=(
            "Legacy offset-based pagination. Phase 269 H-24 lowered the "
            "max limit to 200 from 1000 to bound deep-paging cost."
        ),
    ),
) -> JSONResponse:
    """STAC Item Search (GET)."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)
    return await _execute_search(
        db,
        stac_api_url,
        public_api_url,
        bbox=bbox,
        datetime_str=datetime_param,
        collections=collections,
        ids=ids,
        intersects=intersects,
        limit=limit,
        offset=offset,
    )


class StacSearchBody(BaseModel):
    """JSON body for POST /search."""

    bbox: list[float] | None = None
    datetime: str | None = None
    collections: list[str] | None = None
    ids: list[str] | None = None
    intersects: dict | None = None
    limit: int = 10
    offset: int = 0


@stac_router.post(
    "/search",
    response_class=JSONResponse,
    responses={
        200: {"content": {"application/geo+json": {}}},
        **ERROR_RESPONSES_PUBLIC,
    },
)
async def search_post(
    body: StacSearchBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """STAC Item Search (POST with JSON body)."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)

    return await _execute_search(
        db,
        stac_api_url,
        public_api_url,
        bbox=body.bbox,
        datetime_str=body.datetime,
        collections=body.collections,
        ids=body.ids,
        intersects=body.intersects,
        # H-24: clamp body limit to 200 (was 1000) for parity with GET search.
        limit=max(1, min(body.limit, 200)),
        offset=max(0, body.offset),
    )


# ---------------------------------------------------------------------------
# Datetime filter helper
# ---------------------------------------------------------------------------


def _apply_datetime_filter(stmt, datetime_str: str):
    """Apply OGC datetime interval filter to a query.

    Delegates parsing to the canonical ``parse_ogc_datetime`` helper in
    search/service.py so STAC and OGC Records share one implementation.
    Malformed inputs raise ValueError (was silently ignored before — that
    masked client mistakes).
    """
    from app.modules.catalog.search.service import parse_ogc_datetime

    start, end = parse_ogc_datetime(datetime_str.strip())

    if "/" in datetime_str:
        if start is not None:
            stmt = stmt.where(
                (Record.temporal_end >= start) | (Record.temporal_start >= start)
            )
        if end is not None:
            stmt = stmt.where(Record.temporal_start <= end)
    else:
        # Single instant — match records whose temporal range contains it.
        if start is not None:
            stmt = stmt.where(Record.temporal_start <= start)
            stmt = stmt.where(
                (Record.temporal_end >= start) | (Record.temporal_end.is_(None))
            )
    return stmt
