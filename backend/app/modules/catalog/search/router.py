"""Search and OGC API Records endpoints."""

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.extensions import get_catalog_port
from app.modules.auth.dependencies import get_optional_user
from app.modules.catalog.authorization import (
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
from app.modules.catalog.search.router_saved import router as saved_search_router
from app.standards.ogc.filtering import (
    build_queryables_response,
    build_record_schema_response,
)
from app.standards.ogc.utils import (
    build_url,
    link_header_value,
    parse_accept_languages,
)
from app.standards.ogc.errors import BAD_REQUEST_RESPONSE, ERROR_RESPONSES_PUBLIC
from app.core.public_urls import get_public_api_url, get_public_app_url
from geoalchemy2.shape import to_shape
from app.modules.catalog.search.schemas import (
    FacetCountResponse,
    OGCCollectionMetadataResponse,
    OGCCollectionsResponse,
    OGCFeatureCollectionResponse,
    OGCRecordLink,
)
from app.modules.catalog.search.query_params import (
    SearchQueryParams,
    parse_spatial_params,
)
from app.modules.catalog.search import cache as search_cache
from app.modules.catalog.search.records_protocol import (
    collection_search_feature,
    feature_collection_content_language,
    parse_array_query_values,
    parse_ogc_sortby,
    parse_record_ids,
    serialized_feature_language,
    standard_response_headers,
    validate_legacy_external_id_access,
)
from app.modules.catalog.search.service import (
    SearchFilters,
    count_collections,
    dataset_to_ogc_record,
    get_facet_counts,
    search_collections,
    search_datasets,
)
from app.core.persistent_config import (
    SEMANTIC_SEARCH_ENABLED,
    get_cached_semantic_search_rate_limit,
)
from app.modules.auth.router import limiter

logger = structlog.stdlib.get_logger(__name__)


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
    """Fetch raster metadata for a single dataset (column list lives in
    app/processing/raster/queries.py — KISS-6).

    For VRT datasets, also looks up source_count from VrtGeneration.
    """
    meta = await get_catalog_port().fetch_raster_meta_one(db, dataset_id)
    if meta is None:
        return None

    # Fetch source_count for VRT datasets (only this site needs it)
    if (
        meta.get("vrt_type") is not None
        and meta.get("current_generation_id") is not None
    ):
        source_count = await get_catalog_port().get_vrt_generation_source_count(
            db, meta["current_generation_id"]
        )
        if source_count is not None:
            meta["source_count"] = source_count

    # Drop the internal generation_id from the public response (kept only for the join above).
    meta.pop("current_generation_id", None)
    return meta


# ---------------------------------------------------------------------------
# Shared search handler
# ---------------------------------------------------------------------------


async def _handle_search(
    db: AsyncSession,
    user: Identity | None,
    request: Request,
    params: SearchQueryParams,
    *,
    record_ids: tuple[uuid.UUID, ...] | None = None,
    collection_ids: tuple[uuid.UUID, ...] | None = None,
    external_ids: tuple[str, ...] | None = None,
    resource_types: frozenset[str] | None = None,
    extra_pagination_params: dict[str, str | list[str]] | None = None,
) -> OGCFeatureCollectionResponse:
    """Parse parameters, run search, and return OGC FeatureCollection."""
    public_api_url = await get_public_api_url(db, request=request)
    # fix(#315 follow-up): raster/VRT raster_tiles assets are served at the
    # public APP origin (/raster-tiles/...), not the /api origin.
    public_app_url = await get_public_app_url(db, request=request)
    preferred_languages = parse_accept_languages(request)

    filters = params.to_filters()
    if (
        record_ids is not None
        or external_ids is not None
        or resource_types is not None
        or extra_pagination_params is not None
    ):
        filters = replace(
            filters,
            record_ids=record_ids,
            external_ids=external_ids,
            public_resource_types=(
                tuple(sorted(resource_types)) if resource_types is not None else None
            ),
            standards_query_params=(
                tuple(
                    (key, tuple(value if isinstance(value, list) else [value]))
                    for key, value in sorted(extra_pagination_params.items())
                )
                if extra_pagination_params
                else None
            ),
        )

    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    cache_key: str | None = None
    if search_cache.is_anon_cacheable(user):
        # Only read semantic flag when caching is applicable — authed callers skip both reads.
        semantic_enabled_for_key = await SEMANTIC_SEARCH_ENABLED.get(db)
        cache_key = search_cache.build_cache_key(
            endpoint="search",
            filters=filters,
            user_roles=user_roles,
            public_api_url=public_api_url,
            # fix(#315): raster_tiles asset hrefs depend on the app origin, so it
            # must be in the key (multi-origin deploys sharing one API host).
            public_app_url=public_app_url,
            semantic_enabled=semantic_enabled_for_key,
            preferred_languages=tuple(preferred_languages),
        )
        cached = await search_cache.get_cached(cache_key)
        if cached is not None:
            return OGCFeatureCollectionResponse(**cached)

    try:
        datasets, total = await search_datasets(
            db,
            user,
            user_roles,
            filters,
            preferred_languages=preferred_languages,
        )
    except DataError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid spatial filter geometry",
        )

    (
        stac_assets_by_dataset,
        raster_meta,
        extent_geojson_map,
    ) = await _bulk_fetch_dataset_metadata(db, datasets)

    features = [
        dataset_to_ogc_record(
            d,
            public_api_url,
            stac_asset_rows=stac_assets_by_dataset.get(str(d.id)),
            raster_meta=raster_meta.get(str(d.id)),
            spatial_extent_geojson=extent_geojson_map.get(str(d.id)),
            public_app_url=public_app_url,
            preferred_languages=preferred_languages,
        )
        for d in datasets
    ]

    collection_type_requested = bool(
        resource_types is not None and "collection" in resource_types
    )
    text_search_requested = bool(params.q and params.q.strip())

    # Collections are surfaced for text searches, explicit collection IDs, or
    # an explicit public collection type when the request is not scoped to an
    # internal record type or collection membership.
    collections_applicable = bool(
        (
            text_search_requested
            or collection_ids is not None
            or collection_type_requested
        )
        and not params.record_type
        and not params.collection_id
        and (resource_types is None or "collection" in resource_types)
    )
    collections_paginated = bool(
        collections_applicable
        and (collection_type_requested or collection_ids is not None)
    )

    # fix(#315): retain the five-item page-0 augmentation for native text search.
    # fix(#475): explicit Records collection filters participate in the combined
    # dataset-first result set, including its count and pagination.
    page0_collection_cap = 5
    collection_total = 0
    if collections_applicable:
        collection_total = await count_collections(
            db, params.q or "", collection_ids=collection_ids
        )
        if not collections_paginated:
            collection_total = min(collection_total, page0_collection_cap)

    if collections_paginated:
        collection_limit = max(0, params.limit - len(features))
        collection_offset = max(0, params.offset - total)
    else:
        collection_limit = page0_collection_cap if params.offset == 0 else 0
        collection_offset = 0

    if collections_applicable and collection_limit:
        coll_results = await search_collections(
            db,
            params.q or "",
            user,
            user_roles,
            limit=collection_limit,
            offset=collection_offset,
            collection_ids=collection_ids,
        )
        for coll in coll_results:
            features.append(collection_search_feature(coll, public_api_url))

    # Build pagination links
    active_params = params.active_pagination_params()
    if extra_pagination_params:
        active_params.update(extra_pagination_params)
    base_path = "/collections/datasets/items"

    links = [
        OGCRecordLink(
            rel="self",
            href=_build_pagination_url(
                public_api_url,
                base_path,
                active_params,
                offset=params.offset,
                limit=params.limit,
            ),
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

    pagination_total = total + collection_total if collections_paginated else total
    if params.offset + params.limit < pagination_total:
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

    response = OGCFeatureCollectionResponse(
        type="FeatureCollection",
        timeStamp=datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        # fix(#315): stable across pages; fix(#475): explicitly selected
        # collections are counted and paginated with datasets.
        numberMatched=total + collection_total,
        numberReturned=len(features),
        features=features,
        links=links,
    )
    if cache_key is not None:
        await search_cache.set_cached(cache_key, response.model_dump(mode="json"))
    return response


# ---------------------------------------------------------------------------
# Search router
# ---------------------------------------------------------------------------

search_router = APIRouter(prefix="/search", tags=["Search"])
search_router.include_router(saved_search_router)


def _semantic_search_rate_limit(_request: Request | None = None) -> str:
    """SEC-S11: per-IP rate limit for semantic search endpoints (caps OpenAI embedding cost)."""
    return f"{get_cached_semantic_search_rate_limit()}/minute"


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
@search_router.get(
    "/facets", response_model=FacetCountResponse, include_in_schema=False
)
@search_router.get("/facets/", response_model=FacetCountResponse)
# WR-02: no semantic-search rate limit on /facets/ — this endpoint does pure
# SQL aggregation and never calls the embedding model. Applying the 30/min
# embedding cost-cap (SEC-S11) here would silently throttle SPA users who
# refresh the search UI more than 30 times per minute.
async def search_facets_endpoint(
    request: Request,
    q: str | None = Query(None, max_length=1000, description="Full-text search query"),
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
        None, max_length=10000, description="GeoJSON geometry for spatial filter"
    ),
    collection_id: uuid.UUID | None = Query(
        None, description="Filter by collection membership"
    ),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> FacetCountResponse:
    """Return record_type facet counts for the given filters."""
    geometry_geojson, bbox_parsed = parse_spatial_params(geometry, bbox)

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

    facet_cache_key: str | None = None
    if search_cache.is_anon_cacheable(user):
        facet_cache_key = search_cache.build_cache_key(
            endpoint="facets",
            filters=facet_filters,
            user_roles=user_roles,
            public_api_url=None,
            semantic_enabled=None,
        )
        cached = await search_cache.get_cached(facet_cache_key)
        if cached is not None:
            # FastAPI coerces dict -> FacetCountResponse via response_model.
            return cached

    result = await get_facet_counts(
        db,
        user,
        user_roles,
        facet_filters,
    )
    if facet_cache_key is not None:
        await search_cache.set_cached(facet_cache_key, result)
    return result


# ROUTE-01 (Phase 1092): dual-shape decorator — see /facets above.
@search_router.get(
    "/datasets",
    response_model=OGCFeatureCollectionResponse,
    include_in_schema=False,
)
@search_router.get(
    "/datasets/",
    response_model=OGCFeatureCollectionResponse,
    responses={400: BAD_REQUEST_RESPONSE},
)
@limiter.limit(_semantic_search_rate_limit)
async def search_datasets_endpoint(
    request: Request,
    response: Response,
    params: SearchQueryParams = Depends(),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCFeatureCollectionResponse:
    """Search datasets with text, spatial, and faceted filters."""
    # Read keywords from raw query string (list[str] may not bind via Depends).
    raw_keywords = request.query_params.getlist("keywords")
    if raw_keywords and not params.keywords:
        params = params.model_copy(update={"keywords": raw_keywords})
    # Validate the raw hyphenated "filter-lang" (not bound by Pydantic Depends);
    # mirrors collection_items so a bogus value 400s instead of being ignored.
    raw_filter_lang = request.query_params.get("filter-lang")
    if raw_filter_lang:
        if raw_filter_lang not in ("cql2-text", "cql2-json"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported filter-lang: {raw_filter_lang}. Use cql2-text or cql2-json.",
            )
        params = params.model_copy(update={"cql2_filter_lang": raw_filter_lang})
    result = await _handle_search(db, user, request, params)
    for name, value in standard_response_headers(
        list(result.links or []),
        language=feature_collection_content_language(result),
    ).items():
        response.headers[name] = value
    return result


# ---------------------------------------------------------------------------
# OGC Collections router
# ---------------------------------------------------------------------------

collections_router = APIRouter(
    prefix="/collections",
    tags=["OGC Features"],
    responses=ERROR_RESPONSES_PUBLIC,
)


_COLLECTION_META_CACHE = search_cache._COLLECTION_META_CACHE


async def _build_collection_metadata(
    db: AsyncSession,
    user: Identity | None,
    public_api_url: str,
) -> dict:
    """Build dynamic collection metadata with aggregated extents and summaries.

    Results are cached for 60 seconds keyed by user-id (or 'anon') to avoid
    redundant aggregate queries on every request.
    """
    cache_key = search_cache.collection_metadata_cache_key(
        str(user.id) if user is not None else "anon"
    )
    cached = search_cache.get_collection_metadata_cached(cache_key)
    if cached is not None:
        cached["links"] = _build_collection_links(public_api_url)
        return cached

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
    try:
        result = await db.execute(extent_stmt)
        row = result.one()
    except Exception:  # broad: ST_Extent aggregation can fail on diverse PostGIS errors; degrade to no-extent metadata
        logger.error(
            "Failed to compute spatial extent for collection metadata", exc_info=True
        )
        row = None

    # Parse spatial extent
    spatial_extent = None
    if row is not None and row.bbox_geojson is not None:
        geojson = json.loads(row.bbox_geojson)
        coords = geojson["coordinates"][0]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        spatial_extent = [min(xs), min(ys), max(xs), max(ys)]

    # Build temporal extent
    temporal_extent = None
    if row is not None and (
        row.temporal_start is not None or row.temporal_end is not None
    ):
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

    # Summaries + keywords in a single query: outer-join RecordKeyword so all
    # four array_agg expressions run in one pass instead of two round-trips.
    # DISTINCT inside each array_agg handles fan-out from the keyword join.
    summary_stmt = (
        select(
            func.array_agg(func.distinct(Dataset.geometry_type))
            .filter(Dataset.geometry_type.isnot(None))
            .label("geometry_types"),
            func.array_agg(func.distinct(Dataset.srid))
            .filter(Dataset.srid.isnot(None))
            .label("srids"),
            func.array_agg(func.distinct(Record.source_organization))
            .filter(
                Record.source_organization.isnot(None),
                Record.source_organization != "",
            )
            .label("organizations"),
            func.array_agg(func.distinct(RecordKeyword.keyword))
            .filter(RecordKeyword.keyword.isnot(None))
            .label("keywords"),
        )
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .outerjoin(RecordKeyword, RecordKeyword.record_id == Record.id)
    )
    summary_stmt = apply_visibility_filter(
        summary_stmt, user, user_roles, Record, DatasetGrant
    )
    # Best-effort summaries: a transient aggregation failure (e.g. a
    # corrupted record_keywords row) must not 500 the entire collection
    # metadata endpoint — degrade to "extent only, no summaries".
    try:
        summary_row = (await db.execute(summary_stmt)).one()
    except Exception:  # broad: summary aggregation can hit diverse DB errors; degrade to no-summary metadata
        logger.error(
            "Failed to compute summaries for collection metadata", exc_info=True
        )
        summary_row = None
    geometry_types = sorted((summary_row.geometry_types if summary_row else None) or [])
    srids = sorted((summary_row.srids if summary_row else None) or [])
    organizations = sorted((summary_row.organizations if summary_row else None) or [])
    keywords_list = sorted((summary_row.keywords if summary_row else None) or [])

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

    search_cache.set_collection_metadata_cached(cache_key, collection)

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


# ROUTE-01 (Phase 1092): both slash and no-slash variants register the same
# handler directly. Canonical OpenAPI form is "" (no-slash); the trailing
# slash variant is a hidden alias for callers that send it. Mirrors the
# Phase 280 dual-shape pattern in catalog/maps/router.py. Prevents the
# 307 + http://api:8000 Location-header leak when redirect_slashes=False
# at the app level (see api/main.py).
@collections_router.get(
    "/", response_model=OGCCollectionsResponse, include_in_schema=False
)
@collections_router.get("", response_model=OGCCollectionsResponse)
async def list_collections(
    request: Request,
    response: Response,
    offset: int = Query(
        0, ge=0, description="Pagination offset for per-dataset collections"
    ),
    limit: int = Query(
        50, ge=1, le=200, description="Max per-dataset collections to return"
    ),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCCollectionsResponse:
    """List available OGC collections (catalog + per-dataset feature collections)."""
    public_api_url = await get_public_api_url(db, request=request)
    # Raster tiles are served at the public APP origin (/raster-tiles/...), not
    # the /api origin (which has no such route). fix(#315)
    public_app_url = await get_public_app_url(db, request=request)

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
            except Exception:  # broad: extent parse — geoalchemy/shapely errors degrade to no-spatial extent
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

        # fix(#315): raster/VRT have no feature table -> mirror the detail
        # endpoint (itemType=coverage, omit rel=items, add rel=tiles) so crawlers
        # starting from the list skip the dead /items and still find the data.
        is_raster = ds.record.record_type in ("raster_dataset", "vrt_dataset")

        links: list[dict] = [
            {
                "rel": "self",
                "href": build_url(
                    f"/collections/{ds.id}",
                    base_url=public_api_url,
                ),
                "type": "application/json",
            },
        ]
        if not is_raster:
            links.append(
                {
                    "rel": "items",
                    "href": build_url(
                        f"/collections/{ds.id}/items",
                        base_url=public_api_url,
                    ),
                    "type": "application/geo+json",
                }
            )
        else:
            links.append(
                {
                    "rel": "tiles",
                    "href": build_url(
                        f"/raster-tiles/{ds.id}/tiles/{{z}}/{{x}}/{{y}}.png",
                        base_url=public_app_url,
                    ),
                    "type": "image/png",
                }
            )
        links.append(
            {
                "rel": "root",
                "href": build_url("/", base_url=public_api_url),
                "type": "application/json",
            }
        )

        entry: dict = {
            "id": str(ds.id),
            "title": ds.record.title,
            "description": ds.record.summary,
            "itemType": "coverage" if is_raster else "feature",
            "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"],
            "links": links,
        }
        if extent:
            entry["extent"] = extent
        dataset_collections.append(entry)

    # Build OGC-compliant pagination links
    nav_links: list[OGCRecordLink] = [
        OGCRecordLink(
            rel="self",
            href=_build_pagination_url(
                public_api_url,
                "/collections",
                {},
                offset=offset,
                limit=limit,
            ),
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
                    public_api_url,
                    base_path,
                    {},
                    offset=offset + limit,
                    limit=limit,
                ),
                type="application/json",
            )
        )
    if offset > 0:
        nav_links.append(
            OGCRecordLink(
                rel="prev",
                href=_build_pagination_url(
                    public_api_url,
                    base_path,
                    {},
                    offset=max(0, offset - limit),
                    limit=limit,
                ),
                type="application/json",
            )
        )

    result = OGCCollectionsResponse(
        collections=[catalog_collection] + dataset_collections,
        links=nav_links,
    )
    if link_value := link_header_value(nav_links):
        response.headers["Link"] = link_value
    return result


@collections_router.get("/datasets", response_model=OGCCollectionMetadataResponse)
async def get_collection_metadata(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCCollectionMetadataResponse:
    """Get metadata for the datasets collection."""
    public_api_url = await get_public_api_url(db, request=request)
    result = await _build_collection_metadata(db, user, public_api_url)
    return OGCCollectionMetadataResponse(**result)


@collections_router.get("/datasets/queryables", response_class=JSONResponse)
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


@collections_router.get("/datasets/schema", response_class=JSONResponse)
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


@collections_router.get("/datasets/sortables", response_class=JSONResponse)
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


@collections_router.get(
    "/datasets/items",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": {
                        "$ref": "#/components/schemas/OGCFeatureCollectionResponse"
                    }
                }
            }
        },
        **ERROR_RESPONSES_PUBLIC,
    },
)
async def collection_items(
    request: Request,
    params: SearchQueryParams = Depends(),
    type_param: list[str] = Query(
        default_factory=list,
        alias="type",
        description=(
            "Public OGC resource types as repeated or comma-separated values "
            "(for example, type=dataset,collection)"
        ),
    ),
    ids: list[str] = Query(
        default_factory=list,
        description="Record IDs as repeated or comma-separated UUID values",
    ),
    external_ids: list[str] = Query(
        default_factory=list,
        alias="externalIds",
        description=(
            "Source-system resource identifiers as repeated or comma-separated values"
        ),
    ),
    sortby: str | None = Query(None, description="OGC sortby: +field or -field"),
    external_id: str | None = Query(
        None,
        alias="externalId",
        description=(
            "Deprecated singular compatibility alias for externalIds "
            "(matches a dataset UUID)"
        ),
        deprecated=True,
    ),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """OGC API Records items endpoint -- mirrors /search/datasets."""
    parsed_types = parse_array_query_values(type_param, parameter="type")
    resource_types = (
        frozenset(value.lower() for value in parsed_types)
        if parsed_types is not None
        else None
    )

    parsed_ids = parse_record_ids(
        parse_array_query_values(ids, parameter="ids"),
        parameter="ids",
    )
    parsed_external_ids = parse_array_query_values(
        external_ids, parameter="externalIds"
    )

    # Keep the singular compatibility alias's historical access behavior while
    # returning the same FeatureCollection shape as every collection query.
    legacy_external_id: uuid.UUID | None = None
    if external_id is not None:
        legacy_external_id = await validate_legacy_external_id_access(
            db, external_id, user
        )

    identifier_sets = [set(values) for values in (parsed_ids,) if values is not None]
    if legacy_external_id is not None:
        identifier_sets.append({legacy_external_id})

    record_ids: tuple[uuid.UUID, ...] | None = None
    if identifier_sets:
        matching_ids = set.intersection(*identifier_sets)
        record_ids = tuple(sorted(matching_ids, key=str))

    collection_ids = parsed_ids
    if legacy_external_id is not None or parsed_external_ids is not None:
        collection_ids = ()

    # The serialized dataset rows expose the public Records type "dataset".
    # Internal storage subtypes (vector_dataset, raster_dataset, table, etc.)
    # remain available through the native record_type parameter but are not
    # accepted as OGC resource types.
    if resource_types is not None and "dataset" not in resource_types:
        record_ids = ()

    # Apply OGC-specific overrides via model_copy to keep params immutable
    overrides: dict[str, object] = {}
    if sortby is not None:
        parsed = parse_ogc_sortby(sortby)
        overrides["sort_by"] = parsed[0]
        overrides["sort_desc"] = parsed[1]

    # Read keywords from raw query string (list[str] may not bind via Depends).
    raw_keywords = request.query_params.getlist("keywords")
    if raw_keywords and not params.keywords:
        overrides["keywords"] = raw_keywords

    # Read OGC CQL2 filter params from raw query string (hyphenated
    # "filter-lang" is not resolved by Pydantic model Depends binding).
    raw_filter = request.query_params.get("filter")
    raw_filter_lang = request.query_params.get("filter-lang")
    if raw_filter and not params.cql2_filter:
        overrides["cql2_filter"] = raw_filter
    if raw_filter_lang:
        if raw_filter_lang not in ("cql2-text", "cql2-json"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported filter-lang: {raw_filter_lang}. "
                    "Use cql2-text or cql2-json."
                ),
            )
        overrides["cql2_filter_lang"] = raw_filter_lang

    effective_params = params.model_copy(update=overrides) if overrides else params

    pagination_params: dict[str, str | list[str]] = {}
    for parameter in ("type", "ids", "externalIds", "externalId"):
        values = request.query_params.getlist(parameter)
        if values:
            pagination_params[parameter] = values

    result = await _handle_search(
        db,
        user,
        request,
        effective_params,
        record_ids=record_ids,
        collection_ids=collection_ids,
        external_ids=parsed_external_ids,
        resource_types=resource_types,
        extra_pagination_params=pagination_params,
    )
    return JSONResponse(
        content=result.model_dump(mode="json"),
        media_type="application/geo+json",
        headers=standard_response_headers(
            list(result.links or []),
            language=feature_collection_content_language(result),
        ),
    )


@collections_router.get(
    "/datasets/items/{record_id}",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": {"$ref": "#/components/schemas/OGCRecordResponse"}
                }
            }
        },
        **ERROR_RESPONSES_PUBLIC,
    },
)
async def get_collection_item(
    record_id: uuid.UUID,
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a single dataset as an OGC Record Feature."""
    from sqlalchemy.orm import joinedload as _jl2, selectinload as _sl2

    result = await db.execute(
        select(Dataset)
        .options(
            _jl2(Dataset.record).options(
                _sl2(Record.keywords),
                _sl2(Record.contacts),
                _sl2(Record.distributions),
                _sl2(Record.translations),
            ),
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
    stac_asset_rows = [
        {
            "key": da.key,
            "href": da.href,
            "media_type": da.media_type,
            "roles": da.roles,
            "title": da.title,
            "description": da.description,
        }
        for da in await get_catalog_port().get_dataset_assets(db, record_id)
    ]

    # Fetch raster metadata for STAC property enrichment (best-effort —
    # transient raster-meta failures must not 500 the entire item endpoint).
    item_raster_meta = None
    rec_type = getattr(dataset.record, "record_type", None)
    if rec_type in ("raster_dataset", "vrt_dataset"):
        try:
            item_raster_meta = await _build_raster_assets(db, record_id)
        except Exception:  # broad: raster meta enrichment is best-effort; any DB error degrades to no raster props
            logger.warning(
                "ogc_item_raster_meta_failed",
                record_id=str(record_id),
                exc_info=True,
            )
            item_raster_meta = None

    public_api_url = await get_public_api_url(db, request=request)
    # fix(#315 follow-up): raster_tiles asset href uses the public APP origin.
    public_app_url = await get_public_app_url(db, request=request)
    content = dataset_to_ogc_record(
        dataset,
        public_api_url,
        stac_asset_rows=stac_asset_rows or None,
        raster_meta=item_raster_meta,
        public_app_url=public_app_url,
        preferred_languages=parse_accept_languages(request),
    )
    return JSONResponse(
        content=content,
        media_type="application/geo+json",
        headers=standard_response_headers(
            content.get("links"),
            language=serialized_feature_language(content),
        ),
    )


async def _bulk_fetch_dataset_metadata(
    db: AsyncSession,
    datasets: list[Dataset],
) -> tuple[
    dict[str, list[dict]],
    dict[str, dict],
    dict[str, str | None],
]:
    """Bulk-fetch the three pre-render maps used by dataset_to_ogc_record.

    Takes the materialized datasets list (not just IDs) — needs
    ``d.record.record_type`` to build the raster_ids filter (already
    eager-loaded via selectinload in search_datasets).

    Returns ``(stac_assets_by_dataset, raster_meta, extent_geojson_map)``,
    each keyed by ``str(dataset_id)``.

    Raster and STAC asset access routes through CatalogPort so search does not
    import processing-owned modules directly.

    PERF-02 (Phase 274): block 1 (STAC assets) and block 4 (ST_AsGeoJSON
    extents) are independent of each other AND of blocks 2+3, so they run
    concurrently via ``asyncio.gather`` against fresh short-lived sessions
    from ``app.core.db.async_session``. SQLAlchemy AsyncSession is NOT
    safe for concurrent use, so each parallel block opens its own session
    rather than sharing the caller's ``db`` parameter.

    Blocks 2 and 3 stay sequential because block 3 mutates block 2's
    output in place — they reuse the caller's ``db`` after the gather
    completes.

    Best-effort error semantics preserved: per-block exceptions are
    captured (via ``return_exceptions=True`` on the gather, plus
    explicit try/except inside each inner function) so a transient
    failure in any one block leaves the others' results intact.
    """
    all_dataset_ids = [d.id for d in datasets]

    async def _block_stac() -> dict[str, list[dict]]:
        # PERF-02: runs concurrently with _block_extents under asyncio.gather.
        # Uses its own short-lived session because the parent `db` is not
        # safe for concurrent execution.
        stac_assets: dict[str, list[dict]] = {}
        if not all_dataset_ids:
            return stac_assets
        try:
            from app.core.db import async_session

            async with async_session() as inner_db:
                for da in await get_catalog_port().list_dataset_assets(
                    inner_db, all_dataset_ids
                ):
                    ds_key = str(da.dataset_id)
                    stac_assets.setdefault(ds_key, []).append(
                        {
                            "key": da.key,
                            "href": da.href,
                            "media_type": da.media_type,
                            "roles": da.roles,
                            "title": da.title,
                            "description": da.description,
                        }
                    )
        except Exception:  # broad: bulk STAC asset fetch — degrade to empty so other enrichment can still run
            logger.warning(
                "search_bulk_fetch_stac_assets_failed",
                dataset_count=len(all_dataset_ids),
                exc_info=True,
            )
            return {}
        return stac_assets

    async def _block_extents() -> dict[str, str | None]:
        # PERF-02: runs concurrently with _block_stac under asyncio.gather.
        # Uses its own short-lived session for the same reason.
        extents: dict[str, str | None] = {}
        if not all_dataset_ids:
            return extents
        try:
            from app.core.db import async_session

            async with async_session() as inner_db:
                geojson_stmt = (
                    select(
                        Dataset.id,
                        func.ST_AsGeoJSON(Record.spatial_extent, 6).label("geojson"),
                    )
                    .join(Record, Dataset.record_id == Record.id)
                    .where(Dataset.id.in_(all_dataset_ids))
                )
                for _row in (await inner_db.execute(geojson_stmt)).all():
                    extents[str(_row.id)] = _row.geojson
        except Exception:  # broad: bulk GeoJSON extent fetch — degrade to empty so search response still ships
            logger.warning(
                "search_bulk_fetch_geojson_extents_failed",
                dataset_count=len(all_dataset_ids),
                exc_info=True,
            )
            return {}
        return extents

    # PERF-02: run the two independent blocks concurrently.
    # return_exceptions=True ensures one block's failure does not cancel
    # the other; we coerce non-dict results back to empty dicts for the
    # best-effort fallback (matches the pre-PERF-02 per-block try/except).
    stac_result, extent_result = await asyncio.gather(
        _block_stac(), _block_extents(), return_exceptions=True
    )
    stac_assets_by_dataset: dict[str, list[dict]] = (
        stac_result if isinstance(stac_result, dict) else {}
    )
    extent_geojson_map: dict[str, str | None] = (
        extent_result if isinstance(extent_result, dict) else {}
    )

    # Blocks 2 + 3 — raster meta + VRT source_count. Block order is
    # load-bearing here: block 3 mutates block 2's output in place, so
    # they MUST stay serialized. They reuse the caller's `db` session
    # because they run after the gather completes.
    raster_meta: dict[str, dict] = {}
    raster_ids = [
        d.id
        for d in datasets
        if getattr(d.record, "record_type", None) in ("raster_dataset", "vrt_dataset")
    ]
    if raster_ids:
        try:
            raster_meta.update(
                await get_catalog_port().fetch_raster_meta_bulk(db, raster_ids)
            )
        except Exception:  # broad: bulk raster meta fetch — degrade to empty so search response still ships
            logger.warning(
                "search_bulk_fetch_raster_meta_failed",
                raster_count=len(raster_ids),
                exc_info=True,
            )
            raster_meta = {}

        # Block 3 — VRT source_count (mutates raster_meta IN PLACE)
        if raster_meta:
            try:
                vrt_dataset_ids = [
                    did
                    for did in raster_ids
                    if raster_meta.get(str(did), {}).get("vrt_type") is not None
                ]
                if vrt_dataset_ids:
                    RasterAsset = get_catalog_port().raster_asset_orm_class()
                    VrtGeneration = get_catalog_port().vrt_generation_orm_class()
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
                            raster_meta[str(row.dataset_id)]["source_count"] = (
                                row.source_count
                            )
            except Exception:  # broad: VRT source-count enrichment is best-effort; any DB error skips the field
                logger.warning(
                    "search_bulk_fetch_vrt_source_count_failed",
                    raster_count=len(raster_ids),
                    exc_info=True,
                )

    return stac_assets_by_dataset, raster_meta, extent_geojson_map
