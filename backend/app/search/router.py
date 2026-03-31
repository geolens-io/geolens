"""Search and OGC API Records endpoints."""

import json
import uuid
from datetime import date, datetime, timezone
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user, get_optional_user
from app.auth.models import User
from app.auth.visibility import apply_visibility_filter, get_user_roles
from app.datasets.models import Dataset, DatasetGrant, Record, RecordKeyword
from app.dependencies import get_db
from app.search.saved import (
    create_saved_search,
    delete_saved_search,
    get_saved_search,
    list_saved_searches,
)
from app.features.service import parse_bbox
from app.ogc.filtering import build_queryables_response, build_record_schema_response
from app.ogc.utils import build_url
from app.public_urls import get_public_api_url
from geoalchemy2.shape import to_shape
from app.search.schemas import (
    FacetCountResponse,
    OGCCollectionMetadataResponse,
    OGCCollectionsResponse,
    OGCFeatureCollectionResponse,
    OGCRecordLink,
    SavedSearchCreate,
    SavedSearchListResponse,
    SavedSearchResponse,
)
from app.search.service import (
    dataset_to_ogc_record,
    get_facet_counts,
    search_collections,
    search_datasets,
)

# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------


def _build_pagination_url(
    public_api_url: str,
    base_path: str,
    params: dict,
    offset: int,
    limit: int,
) -> str:
    """Build an absolute pagination URL with offset, limit, and active query params."""
    query_params: dict[str, str | list[str]] = {
        "offset": str(offset),
        "limit": str(limit),
    }
    query_params.update(params)
    return (
        build_url(base_path, base_url=public_api_url)
        + "?"
        + urlencode(
            query_params,
            doseq=True,
        )
    )


# ---------------------------------------------------------------------------
# Shared search handler
# ---------------------------------------------------------------------------


async def _handle_search(
    db: AsyncSession,
    user: User | None,
    request: Request,
    *,
    q: str | None,
    bbox: str | None,
    keywords: list[str] | None,
    geometry_type: str | None,
    srid: int | None,
    source_organization: str | None,
    record_type: str | None = None,
    date_from: date | None,
    date_to: date | None,
    vintage_start: date | None,
    vintage_end: date | None,
    sort_by: str,
    sort_desc: bool | None = None,
    offset: int,
    limit: int,
    cql2_filter: str | None = None,
    cql2_filter_lang: str = "cql2-text",
    datetime_param: str | None = None,
    exclude_synthetic: bool = True,
    spatial_predicate: Literal["intersects", "within"] = "intersects",
    geometry: str | None = None,
    collection_id: uuid.UUID | None = None,
) -> OGCFeatureCollectionResponse:
    """Parse parameters, run search, and return OGC FeatureCollection."""
    public_api_url = await get_public_api_url(db, request=request)

    # Parse geometry GeoJSON (takes precedence over bbox)
    geometry_geojson: str | None = None
    if geometry:
        try:
            parsed = json.loads(geometry)
            if "type" not in parsed or "coordinates" not in parsed:
                raise ValueError("missing type or coordinates")
            geometry_geojson = geometry
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid geometry GeoJSON: {e}",
            )

    # Parse bbox
    bbox_parsed: list[float] | None = None
    if bbox and not geometry_geojson:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )

    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    datasets, total = await search_datasets(
        db,
        user,
        user_roles,
        q=q,
        bbox=bbox_parsed,
        keywords=keywords,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
        record_type=record_type,
        date_from=date_from,
        date_to=date_to,
        vintage_start=vintage_start,
        vintage_end=vintage_end,
        sort_by=sort_by,
        sort_desc=sort_desc,
        skip=offset,
        limit=limit,
        cql2_filter=cql2_filter,
        cql2_filter_lang=cql2_filter_lang,
        datetime_param=datetime_param,
        exclude_synthetic=exclude_synthetic,
        spatial_predicate=spatial_predicate,
        geometry_geojson=geometry_geojson,
        collection_id=collection_id,
    )

    # Bulk-query DatasetAsset rows for STAC assets
    from app.raster.models import DatasetAsset

    all_dataset_ids = [d.id for d in datasets]
    stac_assets_by_dataset: dict[str, list[dict]] = {}
    if all_dataset_ids:
        da_stmt = select(DatasetAsset).where(
            DatasetAsset.dataset_id.in_(all_dataset_ids)
        )
        da_result = await db.execute(da_stmt)
        for da in da_result.scalars().all():
            ds_key = str(da.dataset_id)
            stac_assets_by_dataset.setdefault(ds_key, []).append(
                {
                    "key": da.key,
                    "href": da.href,
                    "media_type": da.media_type,
                    "roles": da.roles,
                    "title": da.title,
                    "description": da.description,
                }
            )

    # Pre-fetch raster metadata for STAC property enrichment
    raster_meta: dict[str, dict] = {}
    raster_ids = [
        d.id
        for d in datasets
        if getattr(d.record, "record_type", None) in ("raster_dataset", "vrt_dataset")
    ]
    if raster_ids:
        from app.raster.models import RasterAsset

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
            RasterAsset.vrt_type,
            RasterAsset.resolution_strategy,
        ).where(RasterAsset.dataset_id.in_(raster_ids))
        ra_result = await db.execute(ra_stmt)
        for row in ra_result.all():
            raster_meta[str(row.dataset_id)] = {
                "band_count": row.band_count,
                "epsg": row.epsg,
                "res_x": float(row.res_x) if row.res_x is not None else None,
                "res_y": float(row.res_y) if row.res_y is not None else None,
                "width": row.width,
                "height": row.height,
                "dtype": row.dtype,
                "nodata": row.nodata,
                "band_info": row.band_info,
                "vrt_type": row.vrt_type,
                "resolution_strategy": row.resolution_strategy,
            }

        # Fetch source_count for VRT datasets from VrtGeneration table
        from app.raster.models import VrtGeneration

        vrt_dataset_ids = [
            did
            for did in raster_ids
            if raster_meta.get(str(did), {}).get("vrt_type") is not None
        ]
        if vrt_dataset_ids:
            vg_stmt = (
                select(
                    RasterAsset.dataset_id,
                    VrtGeneration.source_count,
                )
                .join(
                    VrtGeneration,
                    VrtGeneration.id == RasterAsset.current_generation_id,
                )
                .where(RasterAsset.dataset_id.in_(vrt_dataset_ids))
            )
            vg_result = await db.execute(vg_stmt)
            for row in vg_result.all():
                if str(row.dataset_id) in raster_meta:
                    raster_meta[str(row.dataset_id)]["source_count"] = row.source_count

    features = [
        dataset_to_ogc_record(
            d,
            public_api_url,
            stac_asset_rows=stac_assets_by_dataset.get(str(d.id)),
            raster_meta=raster_meta.get(str(d.id)),
        )
        for d in datasets
    ]

    # Append collection results on first page when text search is active
    # Skip when filtering by a specific collection
    if q and q.strip() and offset == 0 and not record_type and not collection_id:
        coll_results = await search_collections(db, q, user, user_roles, limit=5)
        for coll in coll_results:
            features.append(
                {
                    "type": "Feature",
                    "id": coll["id"],
                    "geometry": None,
                    "properties": {
                        "type": "collection",
                        "title": coll["name"],
                        "description": coll["description"],
                        "record_type": "collection",
                        "dataset_count": coll["dataset_count"],
                        "created": coll["created_at"],
                    },
                    "links": [
                        {
                            "rel": "self",
                            "href": build_url(
                                f"/catalog/collections/{coll['id']}",
                                base_url=public_api_url,
                            ),
                            "type": "application/json",
                        }
                    ],
                }
            )

    # Build dict of active query parameters for pagination URLs
    active_params: dict[str, str | list[str]] = {}
    if q:
        active_params["q"] = q
    if geometry:
        active_params["geometry"] = geometry
    if bbox:
        active_params["bbox"] = bbox
    if keywords:
        active_params["keywords"] = (
            keywords  # list value, urlencode with doseq handles it
        )
    if geometry_type:
        active_params["geometry_type"] = geometry_type
    if srid is not None:
        active_params["srid"] = str(srid)
    if source_organization:
        active_params["source_organization"] = source_organization
    if record_type:
        active_params["record_type"] = record_type
    if collection_id:
        active_params["collection_id"] = str(collection_id)
    if date_from is not None:
        active_params["date_from"] = date_from.isoformat()
    if date_to is not None:
        active_params["date_to"] = date_to.isoformat()
    if vintage_start is not None:
        active_params["vintage_start"] = vintage_start.isoformat()
    if vintage_end is not None:
        active_params["vintage_end"] = vintage_end.isoformat()
    if sort_by != "relevance":
        active_params["sort_by"] = sort_by
    if datetime_param:
        active_params["datetime"] = datetime_param
    if not exclude_synthetic:
        active_params["exclude_synthetic"] = "false"
    if cql2_filter:
        active_params["filter"] = cql2_filter
    if cql2_filter_lang != "cql2-text":
        active_params["filter-lang"] = cql2_filter_lang
    base_path = "/collections/datasets/items"

    links = [
        OGCRecordLink(
            rel="self",
            href=build_url(base_path, base_url=public_api_url),
            type="application/geo+json",
        ),
        OGCRecordLink(
            rel="collection",
            href=build_url("/collections/datasets", base_url=public_api_url),
            type="application/json",
        ),
        OGCRecordLink(
            rel="root",
            href=build_url("/", base_url=public_api_url),
            type="application/json",
        ),
    ]

    # Next link: more results beyond current page
    if offset + limit < total:
        links.append(
            OGCRecordLink(
                rel="next",
                href=_build_pagination_url(
                    public_api_url,
                    base_path,
                    active_params,
                    offset=offset + limit,
                    limit=limit,
                ),
                type="application/geo+json",
            )
        )

    # Previous link: not on first page
    if offset > 0:
        links.append(
            OGCRecordLink(
                rel="prev",
                href=_build_pagination_url(
                    public_api_url,
                    base_path,
                    active_params,
                    offset=max(0, offset - limit),
                    limit=limit,
                ),
                type="application/geo+json",
            )
        )

    return OGCFeatureCollectionResponse(
        type="FeatureCollection",
        timeStamp=datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        numberMatched=total,
        numberReturned=len(features),
        features=features,
        links=links,
    )


# ---------------------------------------------------------------------------
# Search router
# ---------------------------------------------------------------------------

search_router = APIRouter(prefix="/search", tags=["Search"])


@search_router.get("/facets/", response_model=FacetCountResponse)
async def search_facets_endpoint(
    request: Request,
    q: str | None = Query(None, description="Full-text search query"),
    bbox: str | None = Query(None, description="Bounding box: minx,miny,maxx,maxy"),
    keywords: list[str] | None = Query(None, description="Filter by keywords"),
    geometry_type: str | None = Query(None, description="Filter by geometry type"),
    srid: int | None = Query(None, description="Filter by SRID"),
    source_organization: str | None = Query(
        None, description="Filter by source organization"
    ),
    datetime_param: str | None = Query(
        None, alias="datetime", description="OGC datetime interval"
    ),
    exclude_synthetic: bool = Query(
        True, description="Exclude synthetic/test datasets"
    ),
    spatial_predicate: Literal["intersects", "within"] = Query(
        "intersects", description="Spatial predicate: intersects or within"
    ),
    geometry: str | None = Query(
        None, description="GeoJSON geometry for spatial filter"
    ),
    collection_id: uuid.UUID | None = Query(
        None, description="Filter by collection membership"
    ),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> FacetCountResponse:
    """Return record_type facet counts for the given filters."""
    # Parse geometry GeoJSON (takes precedence over bbox)
    geometry_geojson: str | None = None
    if geometry:
        try:
            parsed = json.loads(geometry)
            if "type" not in parsed or "coordinates" not in parsed:
                raise ValueError("missing type or coordinates")
            geometry_geojson = geometry
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid geometry GeoJSON: {e}",
            )

    # Parse bbox
    bbox_parsed: list[float] | None = None
    if bbox and not geometry_geojson:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )

    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    result = await get_facet_counts(
        db,
        user,
        user_roles,
        q=q,
        bbox=bbox_parsed,
        keywords=keywords,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
        datetime_param=datetime_param,
        exclude_synthetic=exclude_synthetic,
        spatial_predicate=spatial_predicate,
        geometry_geojson=geometry_geojson,
        collection_id=collection_id,
    )
    return result


@search_router.get("/datasets/", response_model=OGCFeatureCollectionResponse)
async def search_datasets_endpoint(
    request: Request,
    q: str | None = Query(None, description="Full-text search query"),
    bbox: str | None = Query(None, description="Bounding box: minx,miny,maxx,maxy"),
    keywords: list[str] | None = Query(None, description="Filter by keywords"),
    geometry_type: str | None = Query(None, description="Filter by geometry type"),
    srid: int | None = Query(None, description="Filter by SRID"),
    source_organization: str | None = Query(
        None, description="Filter by source organization"
    ),
    record_type: str | None = Query(
        None, description="Filter by record type (vector_dataset, raster_dataset)"
    ),
    date_from: date | None = Query(None, description="Filter created_at >="),
    date_to: date | None = Query(None, description="Filter created_at <="),
    vintage_start: date | None = Query(
        None, description="Filter data_vintage_start >="
    ),
    vintage_end: date | None = Query(None, description="Filter data_vintage_end <="),
    sort_by: str = Query(
        "relevance",
        description="Sort: relevance, date_added, name, last_updated",
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(10, ge=1, le=100, description="Page size"),
    datetime_param: str | None = Query(
        None,
        alias="datetime",
        description="OGC datetime interval: instant, start/end, ../end, start/..",
    ),
    exclude_synthetic: bool = Query(
        True, description="Exclude synthetic/test datasets"
    ),
    spatial_predicate: Literal["intersects", "within"] = Query(
        "intersects", description="Spatial predicate: intersects or within"
    ),
    geometry: str | None = Query(
        None, description="GeoJSON geometry for spatial filter"
    ),
    collection_id: uuid.UUID | None = Query(
        None, description="Filter by collection membership"
    ),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCFeatureCollectionResponse:
    """Search datasets with text, spatial, and faceted filters."""
    return await _handle_search(
        db,
        user,
        request,
        q=q,
        bbox=bbox,
        keywords=keywords,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
        record_type=record_type,
        date_from=date_from,
        date_to=date_to,
        vintage_start=vintage_start,
        vintage_end=vintage_end,
        sort_by=sort_by,
        offset=offset,
        limit=limit,
        datetime_param=datetime_param,
        exclude_synthetic=exclude_synthetic,
        spatial_predicate=spatial_predicate,
        geometry=geometry,
        collection_id=collection_id,
    )


# ---------------------------------------------------------------------------
# Saved searches endpoints
# ---------------------------------------------------------------------------


@search_router.post(
    "/saved/",
    response_model=SavedSearchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_saved_search_endpoint(
    body: SavedSearchCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SavedSearchResponse:
    """Save a search query with a name for later reuse."""
    saved = await create_saved_search(db, user.id, body.name, body.params)
    await db.commit()
    await db.refresh(saved)
    return SavedSearchResponse.model_validate(saved)


@search_router.get("/saved/", response_model=SavedSearchListResponse)
async def list_saved_searches_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SavedSearchListResponse:
    """List saved searches for the authenticated user."""
    searches, total = await list_saved_searches(db, user.id, skip=skip, limit=limit)
    return SavedSearchListResponse(
        searches=[SavedSearchResponse.model_validate(s) for s in searches],
        total=total,
    )


@search_router.get("/saved/{search_id}", response_model=SavedSearchResponse)
async def get_saved_search_endpoint(
    search_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SavedSearchResponse:
    """Get a single saved search by ID."""
    saved = await get_saved_search(db, search_id, user.id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved search not found",
        )
    return SavedSearchResponse.model_validate(saved)


@search_router.delete("/saved/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search_endpoint(
    search_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a saved search."""
    deleted = await delete_saved_search(db, search_id, user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved search not found",
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# OGC Collections router
# ---------------------------------------------------------------------------

collections_router = APIRouter(prefix="/collections", tags=["OGC Features"])


async def _build_collection_metadata(
    db: AsyncSession,
    user: User | None,
    public_api_url: str,
) -> dict:
    """Build dynamic collection metadata with aggregated extents and summaries."""
    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    # Spatial + temporal extent in one query (these fields are now on Record)
    extent_stmt = (
        select(
            func.ST_AsGeoJSON(
                func.ST_Envelope(func.ST_Collect(Record.spatial_extent))
            ).label("bbox_geojson"),
            func.min(Record.temporal_start).label("temporal_start"),
            func.max(Record.temporal_end).label("temporal_end"),
        )
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
    )
    extent_stmt = apply_visibility_filter(
        extent_stmt, user, user_roles, Record, DatasetGrant
    )
    result = await db.execute(extent_stmt)
    row = result.one()

    # Parse spatial extent
    spatial_extent = None
    if row.bbox_geojson is not None:
        geojson = json.loads(row.bbox_geojson)
        coords = geojson["coordinates"][0]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        spatial_extent = [min(xs), min(ys), max(xs), max(ys)]

    # Build temporal extent
    temporal_extent = None
    if row.temporal_start is not None or row.temporal_end is not None:
        temporal_extent = {
            "interval": [
                [
                    row.temporal_start.isoformat() if row.temporal_start else "..",
                    row.temporal_end.isoformat() if row.temporal_end else "..",
                ]
            ]
        }

    # Build extent object
    extent = {}
    if spatial_extent is not None:
        extent["spatial"] = {"bbox": [spatial_extent]}
    if temporal_extent is not None:
        extent["temporal"] = temporal_extent

    # Summaries: geometry types
    geo_stmt = (
        select(func.distinct(Dataset.geometry_type))
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.geometry_type.isnot(None))
    )
    geo_stmt = apply_visibility_filter(geo_stmt, user, user_roles, Record, DatasetGrant)
    geo_result = await db.execute(geo_stmt)
    geometry_types = sorted([r[0] for r in geo_result.all()])

    # Summaries: SRIDs
    srid_stmt = (
        select(func.distinct(Dataset.srid))
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.srid.isnot(None))
    )
    srid_stmt = apply_visibility_filter(
        srid_stmt, user, user_roles, Record, DatasetGrant
    )
    srid_result = await db.execute(srid_stmt)
    srids = sorted([r[0] for r in srid_result.all()])

    # Summaries: keywords (from record_keywords table)
    kw_stmt = (
        select(func.distinct(RecordKeyword.keyword))
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .join(RecordKeyword, RecordKeyword.record_id == Record.id)
    )
    kw_stmt = apply_visibility_filter(kw_stmt, user, user_roles, Record, DatasetGrant)
    kw_result = await db.execute(kw_stmt)
    keywords_list = sorted([r[0] for r in kw_result.all()])

    # Summaries: source organizations
    org_stmt = (
        select(func.distinct(Record.source_organization))
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .where(Record.source_organization.isnot(None))
        .where(Record.source_organization != "")
    )
    org_stmt = apply_visibility_filter(org_stmt, user, user_roles, Record, DatasetGrant)
    org_result = await db.execute(org_stmt)
    organizations = sorted([r[0] for r in org_result.all()])

    # Build summaries
    summaries = {}
    if geometry_types:
        summaries["geometry_type"] = geometry_types
    if srids:
        summaries["srid"] = srids
    if keywords_list:
        summaries["keywords"] = keywords_list
    if organizations:
        summaries["source_organization"] = organizations

    # Build collection
    collection: dict = {
        "id": "datasets",
        "title": "GeoLens Dataset Catalog",
        "description": "Searchable catalog of geospatial datasets managed by GeoLens",
        "itemType": "record",
        "links": [
            {
                "rel": "self",
                "href": build_url("/collections/datasets", base_url=public_api_url),
                "type": "application/json",
            },
            {
                "rel": "items",
                "href": build_url(
                    "/collections/datasets/items",
                    base_url=public_api_url,
                ),
                "type": "application/geo+json",
            },
            {
                "rel": "root",
                "href": build_url("/", base_url=public_api_url),
                "type": "application/json",
            },
            {
                "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
                "href": build_url(
                    "/collections/datasets/queryables",
                    base_url=public_api_url,
                ),
                "type": "application/schema+json",
                "title": "Queryable properties",
            },
            {
                "rel": "http://www.opengis.net/def/rel/ogc/1.0/schema",
                "href": build_url(
                    "/collections/datasets/schema",
                    base_url=public_api_url,
                ),
                "type": "application/schema+json",
                "title": "Record schema",
            },
        ],
    }
    if extent:
        collection["extent"] = extent
    if summaries:
        collection["summaries"] = summaries

    return collection


@collections_router.get("", response_model=OGCCollectionsResponse)
async def list_collections(
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCCollectionsResponse:
    """List available OGC collections (catalog + per-dataset feature collections)."""
    public_api_url = await get_public_api_url(db, request=request)

    # "datasets" catalog collection (OGC Records)
    catalog_collection = await _build_collection_metadata(db, user, public_api_url)

    # Per-dataset feature collections (OGC Features)
    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    from sqlalchemy.orm import joinedload as _jl

    ds_stmt = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(_jl(Dataset.record))
    )
    ds_stmt = apply_visibility_filter(ds_stmt, user, user_roles, Record, DatasetGrant)
    ds_result = await db.execute(ds_stmt)
    datasets = ds_result.scalars().unique().all()

    dataset_collections = []
    for ds in datasets:
        extent = {}
        if ds.record.spatial_extent is not None:
            try:
                shape = to_shape(ds.record.spatial_extent)
                bbox = list(shape.bounds)
                extent["spatial"] = {
                    "bbox": [bbox],
                    "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                }
            except Exception:
                pass
        if ds.record.temporal_start is not None or ds.record.temporal_end is not None:
            extent["temporal"] = {
                "interval": [
                    [
                        ds.record.temporal_start.isoformat()
                        if ds.record.temporal_start
                        else "..",
                        ds.record.temporal_end.isoformat()
                        if ds.record.temporal_end
                        else "..",
                    ]
                ]
            }

        entry: dict = {
            "id": str(ds.id),
            "title": ds.record.title,
            "description": ds.record.summary,
            "itemType": "feature",
            "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"],
            "links": [
                {
                    "rel": "self",
                    "href": build_url(
                        f"/collections/{ds.id}",
                        base_url=public_api_url,
                    ),
                    "type": "application/json",
                },
                {
                    "rel": "items",
                    "href": build_url(
                        f"/collections/{ds.id}/items",
                        base_url=public_api_url,
                    ),
                    "type": "application/geo+json",
                },
                {
                    "rel": "root",
                    "href": build_url("/", base_url=public_api_url),
                    "type": "application/json",
                },
            ],
        }
        if extent:
            entry["extent"] = extent
        dataset_collections.append(entry)

    return OGCCollectionsResponse(
        collections=[catalog_collection] + dataset_collections,
        links=[
            OGCRecordLink(
                rel="self",
                href=build_url("/collections", base_url=public_api_url),
                type="application/json",
            ),
            OGCRecordLink(
                rel="root",
                href=build_url("/", base_url=public_api_url),
                type="application/json",
            ),
        ],
    )


@collections_router.get("/datasets", response_model=OGCCollectionMetadataResponse)
async def get_collection_metadata(
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCCollectionMetadataResponse:
    """Get metadata for the datasets collection."""
    public_api_url = await get_public_api_url(db, request=request)
    result = await _build_collection_metadata(db, user, public_api_url)
    return OGCCollectionMetadataResponse(**result)


@collections_router.get("/datasets/queryables")
async def get_queryables(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Queryable properties for the datasets collection (OGC API Features Part 3)."""
    public_api_url = await get_public_api_url(db, request=request)
    return JSONResponse(
        content=build_queryables_response(public_api_url),
        media_type="application/schema+json",
    )


@collections_router.get("/datasets/schema")
async def get_record_schema(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """JSON Schema describing a catalog record (OGC API Common Part 3)."""
    public_api_url = await get_public_api_url(db, request=request)
    return JSONResponse(
        content=build_record_schema_response(public_api_url),
        media_type="application/schema+json",
    )


# OGC sortby field -> internal sort_by mapping
_OGC_SORT_MAP = {"title": "name", "created": "date_added", "updated": "last_updated"}


@collections_router.get("/datasets/sortables")
async def get_sortables(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Sortable properties for the datasets collection (OGC API Records)."""
    public_api_url = await get_public_api_url(db, request=request)
    return JSONResponse(
        content={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": build_url(
                "/collections/datasets/sortables", base_url=public_api_url
            ),
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "title": "Title",
                    "description": "Dataset title",
                },
                "created": {
                    "type": "string",
                    "format": "date-time",
                    "title": "Created",
                    "description": "Record creation timestamp",
                },
                "updated": {
                    "type": "string",
                    "format": "date-time",
                    "title": "Updated",
                    "description": "Record last update timestamp",
                },
            },
        },
        media_type="application/schema+json",
    )


@collections_router.get("/datasets/items")
async def collection_items(
    request: Request,
    q: str | None = Query(None),
    bbox: str | None = Query(None),
    keywords: list[str] | None = Query(None),
    geometry_type: str | None = Query(None),
    srid: int | None = Query(None),
    source_organization: str | None = Query(None),
    record_type: str | None = Query(None),
    type_param: str | None = Query(
        None, alias="type", description="OGC record type filter"
    ),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    vintage_start: date | None = Query(None),
    vintage_end: date | None = Query(None),
    sort_by: str = Query("relevance"),
    sortby: str | None = Query(None, description="OGC sortby: +field or -field"),
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    cql_filter: str | None = Query(
        None, alias="filter", description="CQL2 filter expression"
    ),
    filter_lang: str = Query(
        "cql2-text",
        alias="filter-lang",
        description="Filter language: cql2-text or cql2-json",
    ),
    datetime_param: str | None = Query(
        None,
        alias="datetime",
        description="OGC datetime interval: instant, start/end, ../end, start/..",
    ),
    exclude_synthetic: bool = Query(
        True, description="Exclude synthetic/test datasets"
    ),
    spatial_predicate: Literal["intersects", "within"] = Query(
        "intersects", description="Spatial predicate: intersects or within"
    ),
    geometry: str | None = Query(
        None, description="GeoJSON geometry for spatial filter"
    ),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """OGC API Records items endpoint -- mirrors /search/datasets."""
    # OGC type param -> record_type
    if type_param and not record_type:
        record_type = type_param

    # OGC sortby -> internal sort_by mapping (sortby takes precedence)
    sort_desc: bool | None = None
    if sortby is not None:
        # URL query strings decode '+' as space; treat leading space as ascending
        _field = sortby.lstrip("+- ")
        if sortby.startswith("-"):
            sort_desc = True
        elif sortby.startswith("+") or sortby.startswith(" "):
            sort_desc = False
        mapped = _OGC_SORT_MAP.get(_field)
        if mapped is None:
            return JSONResponse(
                status_code=400,
                content={
                    "code": "InvalidParameterValue",
                    "description": f"Unknown sortby field: {_field}. Valid: {', '.join(_OGC_SORT_MAP.keys())}",
                },
            )
        sort_by = mapped

    result = await _handle_search(
        db,
        user,
        request,
        q=q,
        bbox=bbox,
        keywords=keywords,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
        record_type=record_type,
        date_from=date_from,
        date_to=date_to,
        vintage_start=vintage_start,
        vintage_end=vintage_end,
        sort_by=sort_by,
        sort_desc=sort_desc,
        offset=offset,
        limit=limit,
        cql2_filter=cql_filter,
        cql2_filter_lang=filter_lang,
        datetime_param=datetime_param,
        exclude_synthetic=exclude_synthetic,
        spatial_predicate=spatial_predicate,
        geometry=geometry,
    )
    return JSONResponse(
        content=result.model_dump(mode="json"),
        media_type="application/geo+json",
    )


@collections_router.get("/datasets/items/{record_id}")
async def get_collection_item(
    record_id: uuid.UUID,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a single dataset as an OGC Record Feature."""
    from sqlalchemy.orm import joinedload as _jl2

    result = await db.execute(
        select(Dataset)
        .options(
            _jl2(Dataset.record).joinedload(Record.keywords),
            _jl2(Dataset.record).joinedload(Record.contacts),
            _jl2(Dataset.record).joinedload(Record.distributions),
        )
        .where(Dataset.id == record_id)
    )
    dataset = result.unique().scalar_one_or_none()

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found",
        )

    # Visibility check
    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    if "admin" not in user_roles:
        # Re-query with visibility filter to check access
        vis_stmt = (
            select(Dataset)
            .join(Record, Dataset.record_id == Record.id)
            .where(Dataset.id == record_id)
        )
        vis_stmt = apply_visibility_filter(
            vis_stmt, user, user_roles, Record, DatasetGrant
        )
        vis_result = await db.execute(vis_stmt)
        if vis_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Record not found",
            )

    # Query DatasetAsset rows for STAC assets
    from app.raster.models import DatasetAsset as DA

    da_result = await db.execute(select(DA).where(DA.dataset_id == record_id))
    stac_asset_rows = [
        {
            "key": da.key,
            "href": da.href,
            "media_type": da.media_type,
            "roles": da.roles,
            "title": da.title,
            "description": da.description,
        }
        for da in da_result.scalars().all()
    ]

    # Fetch raster metadata for STAC property enrichment
    item_raster_meta = None
    rec_type = getattr(dataset.record, "record_type", None)
    if rec_type in ("raster_dataset", "vrt_dataset"):
        from app.raster.models import RasterAsset

        ra_row = await db.execute(
            select(
                RasterAsset.band_count,
                RasterAsset.epsg,
                RasterAsset.res_x,
                RasterAsset.res_y,
                RasterAsset.width,
                RasterAsset.height,
                RasterAsset.dtype,
                RasterAsset.nodata,
                RasterAsset.band_info,
                RasterAsset.vrt_type,
                RasterAsset.resolution_strategy,
                RasterAsset.current_generation_id,
            ).where(RasterAsset.dataset_id == record_id)
        )
        ra = ra_row.one_or_none()
        if ra:
            item_raster_meta = {
                "band_count": ra.band_count,
                "epsg": ra.epsg,
                "res_x": float(ra.res_x) if ra.res_x is not None else None,
                "res_y": float(ra.res_y) if ra.res_y is not None else None,
                "width": ra.width,
                "height": ra.height,
                "dtype": ra.dtype,
                "nodata": ra.nodata,
                "band_info": ra.band_info,
                "vrt_type": ra.vrt_type,
                "resolution_strategy": ra.resolution_strategy,
            }
            # Fetch source_count for VRT datasets
            if ra.vrt_type is not None and ra.current_generation_id is not None:
                from app.raster.models import VrtGeneration

                vg_row = await db.execute(
                    select(VrtGeneration.source_count).where(
                        VrtGeneration.id == ra.current_generation_id
                    )
                )
                vg = vg_row.scalar_one_or_none()
                if vg is not None:
                    item_raster_meta["source_count"] = vg

    public_api_url = await get_public_api_url(db, request=request)
    return JSONResponse(
        content=dataset_to_ogc_record(
            dataset,
            public_api_url,
            stac_asset_rows=stac_asset_rows or None,
            raster_meta=item_raster_meta,
        ),
        media_type="application/geo+json",
    )
