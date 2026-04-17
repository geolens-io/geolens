"""Search and OGC API Records endpoints."""

import json
import time
import uuid
from datetime import date, datetime, timezone
from typing import Literal
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import get_current_active_user, get_optional_user
from app.modules.auth.models import User
from app.modules.auth.visibility import (
    apply_visibility_filter,
    check_dataset_access_or_anonymous,
    get_user_roles,
)
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
    RecordKeyword,
)
from app.core.dependencies import get_db
from app.modules.catalog.search.saved import (
    create_saved_search,
    delete_saved_search,
    get_saved_search,
    list_saved_searches,
)
from app.modules.catalog.features.service import parse_bbox
from app.standards.ogc.filtering import build_queryables_response, build_record_schema_response
from app.standards.ogc.utils import build_url
from app.core.public_urls import get_public_api_url
from geoalchemy2.shape import to_shape
from app.modules.catalog.search.schemas import (
    FacetCountResponse,
    OGCCollectionMetadataResponse,
    OGCCollectionsResponse,
    OGCFeatureCollectionResponse,
    OGCRecordLink,
    SavedSearchCreate,
    SavedSearchListResponse,
    SavedSearchResponse,
)
from app.modules.catalog.search.service import (
    SearchFilters,
    dataset_to_ogc_record,
    get_facet_counts,
    search_collections,
    search_datasets,
)

logger = structlog.stdlib.get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared spatial param parsing
# ---------------------------------------------------------------------------


def _parse_spatial_params(
    geometry: str | None, bbox: str | None
) -> tuple[str | None, list[float] | None]:
    """Parse and validate geometry GeoJSON and bbox query params.

    Geometry takes precedence over bbox when both are provided.
    """
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

    bbox_parsed: list[float] | None = None
    if bbox and not geometry_geojson:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )

    return geometry_geojson, bbox_parsed


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
# Raster metadata helper (shared by _handle_search and get_collection_item)
# ---------------------------------------------------------------------------


async def _build_raster_assets(
    db: AsyncSession,
    dataset_id: uuid.UUID,
) -> dict | None:
    """Fetch raster metadata for a single dataset.

    Returns a dict of raster properties or None if no raster asset exists.
    """
    from app.processing.raster.models import RasterAsset

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
        ).where(RasterAsset.dataset_id == dataset_id)
    )
    ra = ra_row.one_or_none()
    if ra is None:
        return None

    meta = {
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
        from app.processing.raster.models import VrtGeneration

        vg_row = await db.execute(
            select(VrtGeneration.source_count).where(
                VrtGeneration.id == ra.current_generation_id
            )
        )
        vg = vg_row.scalar_one_or_none()
        if vg is not None:
            meta["source_count"] = vg

    return meta


# ---------------------------------------------------------------------------
# Search query params — injectable via Depends() to eliminate parameter sprawl
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel


class SearchQueryParams(_BaseModel):
    """Query parameters for the search endpoints, injectable via FastAPI Depends().

    Handles raw HTTP query params; use :meth:`to_filters` to convert into the
    service-layer ``SearchFilters`` dataclass (which expects pre-parsed bbox
    and geometry_geojson).
    """

    q: str | None = Query(None, description="Full-text search query")
    bbox: str | None = Query(None, description="Bounding box: minx,miny,maxx,maxy")
    keywords: list[str] | None = Query(None, description="Filter by keywords")
    geometry_type: str | None = Query(None, description="Filter by geometry type")
    srid: int | None = Query(None, description="Filter by SRID")
    source_organization: str | None = Query(
        None, description="Filter by source organization"
    )
    record_type: str | None = Query(
        None, description="Filter by record type (vector_dataset, raster_dataset)"
    )
    date_from: date | None = Query(None, description="Filter created_at >=")
    date_to: date | None = Query(None, description="Filter created_at <=")
    vintage_start: date | None = Query(
        None, description="Filter data_vintage_start >="
    )
    vintage_end: date | None = Query(None, description="Filter data_vintage_end <=")
    sort_by: str = Query(
        "relevance",
        description="Sort: relevance, date_added, name, last_updated",
    )
    sort_desc: bool | None = Query(None, description="Sort direction override")
    offset: int = Query(0, ge=0, description="Pagination offset")
    limit: int = Query(10, ge=1, le=1000, description="Page size")
    cql2_filter: str | None = Query(
        None, alias="filter", description="CQL2 filter expression"
    )
    cql2_filter_lang: str = Query(
        "cql2-text",
        alias="filter-lang",
        description="Filter language: cql2-text or cql2-json",
    )
    datetime_param: str | None = Query(
        None,
        alias="datetime",
        description="OGC datetime interval: instant, start/end, ../end, start/..",
    )
    exclude_synthetic: bool = Query(
        True, description="Exclude synthetic/test datasets"
    )
    spatial_predicate: Literal["intersects", "within"] = Query(
        "intersects", description="Spatial predicate: intersects or within"
    )
    geometry: str | None = Query(
        None, description="GeoJSON geometry for spatial filter"
    )
    collection_id: uuid.UUID | None = Query(
        None, description="Filter by collection membership"
    )

    model_config = {"extra": "ignore"}

    def to_filters(self) -> SearchFilters:
        """Convert raw query params into a service-layer SearchFilters."""
        geometry_geojson, bbox_parsed = _parse_spatial_params(
            self.geometry, self.bbox
        )
        return SearchFilters(
            q=self.q,
            bbox=bbox_parsed,
            keywords=self.keywords,
            geometry_type=self.geometry_type,
            srid=self.srid,
            source_organization=self.source_organization,
            record_type=self.record_type,
            date_from=self.date_from,
            date_to=self.date_to,
            vintage_start=self.vintage_start,
            vintage_end=self.vintage_end,
            sort_by=self.sort_by,
            sort_desc=self.sort_desc,
            skip=self.offset,
            limit=self.limit,
            cql2_filter=self.cql2_filter,
            cql2_filter_lang=self.cql2_filter_lang,
            datetime_param=self.datetime_param,
            exclude_synthetic=self.exclude_synthetic,
            spatial_predicate=self.spatial_predicate,
            geometry_geojson=geometry_geojson,
            collection_id=self.collection_id,
        )

    def active_pagination_params(self) -> dict[str, str | list[str]]:
        """Build a dict of non-default query params for pagination URLs."""
        params: dict[str, str | list[str]] = {}
        if self.q:
            params["q"] = self.q
        if self.geometry:
            params["geometry"] = self.geometry
        if self.bbox:
            params["bbox"] = self.bbox
        if self.keywords:
            params["keywords"] = self.keywords
        if self.geometry_type:
            params["geometry_type"] = self.geometry_type
        if self.srid is not None:
            params["srid"] = str(self.srid)
        if self.source_organization:
            params["source_organization"] = self.source_organization
        if self.record_type:
            params["record_type"] = self.record_type
        if self.collection_id:
            params["collection_id"] = str(self.collection_id)
        if self.date_from is not None:
            params["date_from"] = self.date_from.isoformat()
        if self.date_to is not None:
            params["date_to"] = self.date_to.isoformat()
        if self.vintage_start is not None:
            params["vintage_start"] = self.vintage_start.isoformat()
        if self.vintage_end is not None:
            params["vintage_end"] = self.vintage_end.isoformat()
        if self.sort_by != "relevance":
            params["sort_by"] = self.sort_by
        if self.datetime_param:
            params["datetime"] = self.datetime_param
        if not self.exclude_synthetic:
            params["exclude_synthetic"] = "false"
        if self.cql2_filter:
            params["filter"] = self.cql2_filter
        if self.cql2_filter_lang != "cql2-text":
            params["filter-lang"] = self.cql2_filter_lang
        return params


# ---------------------------------------------------------------------------
# Shared search handler
# ---------------------------------------------------------------------------


async def _handle_search(
    db: AsyncSession,
    user: User | None,
    request: Request,
    params: SearchQueryParams,
) -> OGCFeatureCollectionResponse:
    """Parse parameters, run search, and return OGC FeatureCollection."""
    public_api_url = await get_public_api_url(db, request=request)

    filters = params.to_filters()

    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    datasets, total = await search_datasets(
        db,
        user,
        user_roles,
        filters,
    )

    # Bulk-query DatasetAsset rows for STAC assets
    from app.processing.raster.models import DatasetAsset

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
        from app.processing.raster.models import RasterAsset

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
        from app.processing.raster.models import VrtGeneration

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
    if (
        params.q
        and params.q.strip()
        and params.offset == 0
        and not params.record_type
        and not params.collection_id
    ):
        coll_results = await search_collections(
            db, params.q, user, user_roles, limit=5
        )
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

    # Build pagination links
    active_params = params.active_pagination_params()
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
    if params.offset + params.limit < total:
        links.append(
            OGCRecordLink(
                rel="next",
                href=_build_pagination_url(
                    public_api_url,
                    base_path,
                    active_params,
                    offset=params.offset + params.limit,
                    limit=params.limit,
                ),
                type="application/geo+json",
            )
        )

    # Previous link: not on first page
    if params.offset > 0:
        links.append(
            OGCRecordLink(
                rel="prev",
                href=_build_pagination_url(
                    public_api_url,
                    base_path,
                    active_params,
                    offset=max(0, params.offset - params.limit),
                    limit=params.limit,
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
    geometry_geojson, bbox_parsed = _parse_spatial_params(geometry, bbox)

    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    facet_filters = SearchFilters(
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

    result = await get_facet_counts(
        db,
        user,
        user_roles,
        facet_filters,
    )
    return result


@search_router.get("/datasets/", response_model=OGCFeatureCollectionResponse)
async def search_datasets_endpoint(
    request: Request,
    params: SearchQueryParams = Depends(),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCFeatureCollectionResponse:
    """Search datasets with text, spatial, and faceted filters."""
    return await _handle_search(db, user, request, params)


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


# ---------------------------------------------------------------------------
# TTL cache for collection metadata aggregates
# ---------------------------------------------------------------------------

_COLLECTION_META_CACHE: dict[str, tuple[float, dict]] = {}
_COLLECTION_META_TTL = 60  # seconds


def _invalidate_collection_meta_cache() -> None:
    """Clear the collection metadata cache (useful after writes)."""
    _COLLECTION_META_CACHE.clear()


async def _distinct_aggregate(
    db: AsyncSession,
    column,
    user: User | None,
    user_roles: set[str],
    *,
    from_dataset: bool = True,
    extra_joins: list | None = None,
    extra_filters: list | None = None,
) -> list:
    """Run a distinct aggregate query with visibility filtering.

    Args:
        column: The column to select distinct values from.
        from_dataset: When True, start from Dataset joined to Record (default).
        extra_joins: Additional (target, onclause) join pairs.
        extra_filters: Additional WHERE clauses.

    Returns a sorted list of distinct non-null values.
    """
    stmt = select(func.distinct(column))
    if from_dataset:
        stmt = stmt.select_from(Dataset).join(Record, Dataset.record_id == Record.id)
    for target, onclause in (extra_joins or []):
        stmt = stmt.join(target, onclause)
    for filt in extra_filters or []:
        stmt = stmt.where(filt)
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    result = await db.execute(stmt)
    return sorted([r[0] for r in result.all()])


async def _build_collection_metadata(
    db: AsyncSession,
    user: User | None,
    public_api_url: str,
) -> dict:
    """Build dynamic collection metadata with aggregated extents and summaries.

    Results are cached for 60 seconds keyed by user-id (or 'anon') to avoid
    redundant aggregate queries on every request.
    """
    cache_key = str(user.id) if user is not None else "anon"
    cached = _COLLECTION_META_CACHE.get(cache_key)
    if cached is not None:
        ts, data = cached
        if time.monotonic() - ts < _COLLECTION_META_TTL:
            # Re-stamp links with current public_api_url (may differ per request)
            data = dict(data)
            data["links"] = _build_collection_links(public_api_url)
            return data

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

    # Summaries via reusable aggregate helper
    geometry_types = await _distinct_aggregate(
        db, Dataset.geometry_type, user, user_roles,
        extra_filters=[Dataset.geometry_type.isnot(None)],
    )
    srids = await _distinct_aggregate(
        db, Dataset.srid, user, user_roles,
        extra_filters=[Dataset.srid.isnot(None)],
    )
    keywords_list = await _distinct_aggregate(
        db, RecordKeyword.keyword, user, user_roles,
        extra_joins=[(RecordKeyword, RecordKeyword.record_id == Record.id)],
    )
    organizations = await _distinct_aggregate(
        db, Record.source_organization, user, user_roles,
        extra_filters=[
            Record.source_organization.isnot(None),
            Record.source_organization != "",
        ],
    )

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
        "links": _build_collection_links(public_api_url),
    }
    if extent:
        collection["extent"] = extent
    if summaries:
        collection["summaries"] = summaries

    # Store in cache
    _COLLECTION_META_CACHE[cache_key] = (time.monotonic(), collection)

    return collection


def _build_collection_links(public_api_url: str) -> list[dict]:
    """Build the standard links array for the datasets collection."""
    return [
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
    ]


@collections_router.get("", response_model=OGCCollectionsResponse)
async def list_collections(
    request: Request,
    offset: int = Query(0, ge=0, description="Pagination offset for per-dataset collections"),
    limit: int = Query(200, ge=1, le=1000, description="Max per-dataset collections to return"),
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

    ds_base = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(_jl(Dataset.record))
    )
    ds_base = apply_visibility_filter(ds_base, user, user_roles, Record, DatasetGrant)

    # Total count for pagination links
    count_stmt = select(func.count()).select_from(ds_base.subquery())
    total_datasets = (await db.execute(count_stmt)).scalar_one()

    ds_stmt = ds_base.offset(offset).limit(limit)
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
                logger.warning("Failed to serialize OGC bbox extent", exc_info=True)
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

    # Build OGC-compliant pagination links
    nav_links: list[OGCRecordLink] = [
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
    ]
    base_path = "/collections"
    if offset + limit < total_datasets:
        nav_links.append(
            OGCRecordLink(
                rel="next",
                href=_build_pagination_url(
                    public_api_url, base_path, {},
                    offset=offset + limit, limit=limit,
                ),
                type="application/json",
            )
        )
    if offset > 0:
        nav_links.append(
            OGCRecordLink(
                rel="prev",
                href=_build_pagination_url(
                    public_api_url, base_path, {},
                    offset=max(0, offset - limit), limit=limit,
                ),
                type="application/json",
            )
        )

    return OGCCollectionsResponse(
        collections=[catalog_collection] + dataset_collections,
        links=nav_links,
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


def _parse_ogc_sortby(sortby: str) -> tuple[str, bool | None] | JSONResponse:
    """Parse OGC sortby parameter into (sort_by, sort_desc).

    Returns a (sort_by, sort_desc) tuple on success or a JSONResponse error
    on invalid input.
    """
    # URL query strings decode '+' as space; treat leading space as ascending
    _field = sortby.lstrip("+- ")
    sort_desc: bool | None = None
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
    return mapped, sort_desc


async def _lookup_by_external_id(
    db: AsyncSession,
    external_id: str,
    request: Request,
) -> JSONResponse:
    """Lookup a single OGC record by externalId (dataset UUID).

    Returns a JSONResponse with the record or an error response.
    """
    try:
        record_uuid = uuid.UUID(external_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "code": "InvalidParameterValue",
                "description": f"Invalid externalId: {external_id}",
            },
        )
    from sqlalchemy.orm import joinedload as _jl_ext

    ext_result = await db.execute(
        select(Dataset)
        .options(
            _jl_ext(Dataset.record).joinedload(Record.keywords),
            _jl_ext(Dataset.record).joinedload(Record.contacts),
            _jl_ext(Dataset.record).joinedload(Record.distributions),
        )
        .where(Dataset.id == record_uuid)
    )
    dataset = ext_result.unique().scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    public_api_url = await get_public_api_url(db, request=request)
    return JSONResponse(
        content=dataset_to_ogc_record(dataset, public_api_url),
        media_type="application/geo+json",
    )


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
    params: SearchQueryParams = Depends(),
    type_param: str | None = Query(
        None, alias="type", description="OGC record type filter"
    ),
    sortby: str | None = Query(None, description="OGC sortby: +field or -field"),
    external_id: str | None = Query(
        None,
        alias="externalId",
        description="OGC Records external identifier filter (matches dataset UUID)",
    ),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """OGC API Records items endpoint -- mirrors /search/datasets."""
    # OGC externalId -> fetch single record by UUID
    if external_id:
        return await _lookup_by_external_id(db, external_id, request)

    # Apply OGC-specific overrides via model_copy to keep params immutable
    overrides: dict = {}
    if type_param and not params.record_type:
        overrides["record_type"] = type_param
    if sortby is not None:
        parsed = _parse_ogc_sortby(sortby)
        if isinstance(parsed, JSONResponse):
            return parsed
        overrides["sort_by"] = parsed[0]
        overrides["sort_desc"] = parsed[1]

    effective_params = params.model_copy(update=overrides) if overrides else params

    result = await _handle_search(db, user, request, effective_params)
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

    # Single visibility check (raises 404 if access denied)
    await check_dataset_access_or_anonymous(db, dataset, record_id, user)

    # Query DatasetAsset rows for STAC assets
    from app.processing.raster.models import DatasetAsset as DA

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
        item_raster_meta = await _build_raster_assets(db, record_id)

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
