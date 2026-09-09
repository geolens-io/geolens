"""Search and OGC API Records endpoints."""

import asyncio
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
from app.platform.assets.keys import is_public_asset_key
from app.platform.extensions import get_catalog_port
from app.modules.auth.dependencies import get_optional_user
from app.modules.catalog.authorization import (
    apply_visibility_filter,
    check_dataset_access_or_anonymous,
    get_user_roles,
    visible_lineage_summaries,
    visible_lineage_summary,
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
from app.core.geo import extent_to_bbox, rollup_bbox, rollup_bbox_columns
from app.core.public_urls import get_public_api_url, get_public_app_url
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
    consume_paired_query_claim,
    count_collections,
    dataset_to_ogc_record,
    get_facet_counts,
    record_paired_query_claim,
    search_collections,
    search_datasets,
)
from app.core.persistent_config import (
    SEMANTIC_SEARCH_ENABLED,
    get_cached_semantic_search_rate_limit,
)
from app.platform.ratelimit import limiter
from slowapi.util import get_remote_address

logger = structlog.stdlib.get_logger(__name__)


def _build_pagination_url(
    public_api_url: str,
    base_path: str,
    params: dict,
    offset: int,
    limit: int,
) -> str:
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


async def _build_raster_assets(
    db: AsyncSession,
    dataset_id: uuid.UUID,
) -> dict | None:
    """Fetch raster metadata for a single dataset (column list lives in
    app/processing/raster/queries.py — KISS-6).

    For VRT datasets, also counts the source rasters the served VRT is made of.
    """
    from sqlalchemy import text

    meta = await get_catalog_port().fetch_raster_meta_one(db, dataset_id)
    if meta is None:
        return None

    # fix(#1327): count the LIVE member links (datasets/domain/service_query.py),
    # not the in-flight VrtGeneration.source_count — the link write happens at
    # the artifact swap, so the generation's own count can lag what is served.
    if meta.get("vrt_type") is not None:
        count_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM catalog.vrt_source_links "
                "WHERE vrt_dataset_id = :id"
            ),
            {"id": str(dataset_id)},
        )
        meta["source_count"] = count_result.scalar() or 0

    # fix(#1327): current_generation_id must not reach a caller.
    meta.pop("current_generation_id", None)
    return meta


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
    # fix(#315): raster/VRT raster_tiles assets are served at the
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

    # fix(#1103): one visibility query for the page, not one per row.
    lineage = await visible_lineage_summaries(
        db, [d.record for d in datasets], user, user_roles
    )

    features = [
        dataset_to_ogc_record(
            d,
            public_api_url,
            stac_asset_rows=stac_assets_by_dataset.get(str(d.id)),
            raster_meta=raster_meta.get(str(d.id)),
            spatial_extent_geojson=extent_geojson_map.get(str(d.id)),
            public_app_url=public_app_url,
            preferred_languages=preferred_languages,
            lineage_summary=lineage[d.record_id],
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


search_router = APIRouter(prefix="/search", tags=["Search"])


_SUPPORTED_FILTER_LANGS = ("cql2-text", "cql2-json")


def _resolve_filter_lang(
    params: SearchQueryParams, request: Request
) -> SearchQueryParams:
    """Resolve and validate ``filter-lang``, shared by both search handlers.

    Reads the raw query param, not ``params.cql2_filter_lang`` (unbindable
    via ``collection_items``'s bare ``Depends()``, fix(#1671)). Stays ``str``
    so an invalid value 400s instead of FastAPI's 422; an empty value counts
    as "not supplied".
    """
    lang = request.query_params.get("filter-lang") or "cql2-text"
    if lang not in _SUPPORTED_FILTER_LANGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Unsupported filter-lang: {lang}. Use cql2-text or cql2-json."),
        )
    return params.model_copy(update={"cql2_filter_lang": lang})


search_router.include_router(saved_search_router)


def _semantic_search_rate_limit(_request: Request | None = None) -> str:
    """SEC-S11: per-IP rate limit for semantic search endpoints (caps OpenAI embedding cost)."""
    return f"{get_cached_semantic_search_rate_limit()}/minute"


def _semantic_search_query_already_claimed(request: Request) -> bool:
    """fix(#1903): true when the OTHER search route already claimed this query.

    Never creates a claim: this runs before the limiter's own admit/reject
    check, so a request the bucket rejects must not seed one. A non-exempt
    outcome stashes (client, text, route) on ``request.state`` instead, for
    ``_finalize_semantic_search_claim`` to record once the request is
    known to be admitted.
    """
    query_text = request.query_params.get("q")
    if not query_text:
        return False
    # fix(#1903): the route's own identity, not a path substring test --
    # stable even if a future route in this scope shares the "facets" text.
    route = request.scope["route"].name
    client_key = get_remote_address(request)
    if consume_paired_query_claim(client_key, query_text, route):
        return True
    request.state.semantic_search_claim = (client_key, query_text, route)
    return False


def _finalize_semantic_search_claim(request: Request) -> None:
    """fix(#1903): record this request's claim once it is known to be admitted.

    Call at the very top of a search handler -- reaching that point already
    proves the rate limit let the request through. A no-op when the gate
    exempted this request (nothing pending) or the query didn't qualify.
    """
    pending = getattr(request.state, "semantic_search_claim", None)
    if pending is not None:
        record_paired_query_claim(*pending)


# ROUTE-01 (Phase 1092): dual-shape decorator — slash form is canonical
# (in OpenAPI); no-slash is a hidden alias closing the 404 regression from
# redirect_slashes=False (api/main.py).
@search_router.get(
    "/facets", response_model=FacetCountResponse, include_in_schema=False
)
@search_router.get("/facets/", response_model=FacetCountResponse)
# fix(#1855): facets embed the query, so both routes draw on ONE SEC-S11
# bucket. fix(#1903): no override_defaults -- this limit_value is callable,
# so SlowAPIMiddleware already charges the global default unconditionally
# for it (test_semantic_search_rate_limit_1778.py); adding it here would
# only double that charge.
@limiter.shared_limit(
    _semantic_search_rate_limit,
    scope="semantic_search",
    exempt_when=_semantic_search_query_already_claimed,
)
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
    _finalize_semantic_search_claim(request)
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
            semantic_enabled=await SEMANTIC_SEARCH_ENABLED.get(db),
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
# fix(#1903): the facets route's callable-limit note above applies here
# symmetrically -- this route can be the SECOND of the pair too.
@limiter.shared_limit(
    _semantic_search_rate_limit,
    scope="semantic_search",
    exempt_when=_semantic_search_query_already_claimed,
)
async def search_datasets_endpoint(
    request: Request,
    response: Response,
    params: Annotated[SearchQueryParams, Query()],
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCFeatureCollectionResponse:
    """Search datasets with text, spatial, and faceted filters."""
    _finalize_semantic_search_claim(request)
    params = _resolve_filter_lang(params, request)
    result = await _handle_search(db, user, request, params)
    for name, value in standard_response_headers(
        list(result.links or []),
        language=feature_collection_content_language(result),
    ).items():
        response.headers[name] = value
    return result


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

    # fix(#886): rollup_bbox_columns aggregates in two longitude domains so a
    # catalog with records either side of the antimeridian keeps the narrower
    # range instead of folding to a global bbox.
    extent_stmt = (
        select(
            *rollup_bbox_columns(Record.spatial_extent),
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

    # OGC collection extent is the spec (west > east) form, matching the
    # per-dataset bboxes served from extent_to_bbox below.
    spatial_extent = rollup_bbox(row[:6]) if row is not None else None

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

    extent = {}
    if spatial_extent is not None:
        extent["spatial"] = {"bbox": [spatial_extent]}
    if temporal_extent is not None:
        extent["temporal"] = temporal_extent

    # Outer-join RecordKeyword so all four array_agg expressions run in one
    # pass; DISTINCT inside each handles fan-out from the keyword join.
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

    summaries = {}
    if geometry_types:
        summaries["geometry_type"] = geometry_types
    if srids:
        summaries["srid"] = srids
    if keywords_list:
        summaries["keywords"] = keywords_list
    if organizations:
        summaries["source_organization"] = organizations

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


# ROUTE-01 (Phase 1092): canonical form is "" (no-slash); trailing-slash is
# a hidden alias, preventing the 307 + http://api:8000 Location-header leak
# from redirect_slashes=False (api/main.py; mirrors catalog/maps/router.py).
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

    catalog_collection = await _build_collection_metadata(db, user, public_api_url)

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

    count_stmt = select(func.count()).select_from(ds_base.subquery())
    total_datasets = (await db.execute(count_stmt)).scalar_one()

    # fix(#1778): no ORDER BY meant OFFSET/LIMIT paging had no defined row
    # order -- add a deterministic tiebreaker before paging, matching the
    # STAC peer routers.
    ds_stmt = ds_base.order_by(Record.created_at.desc(), Dataset.id.desc())
    ds_stmt = ds_stmt.offset(offset).limit(limit)
    ds_result = await db.execute(ds_stmt)
    datasets = ds_result.scalars().unique().all()

    dataset_collections = []
    for ds in datasets:
        extent = {}
        if ds.record.spatial_extent is not None:
            # fix(#892): OGC bbox convention needs west > east across a seam;
            # extent_to_bbox returns None on a parse failure, which degrades
            # to no spatial extent.
            bbox = extent_to_bbox(ds.record.spatial_extent)
            if bbox is None:
                logger.warning("Failed to serialize OGC bbox extent")
            else:
                extent["spatial"] = {
                    "bbox": [bbox],
                    "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                }
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
        # endpoint (coverage, no rel=items, add rel=tiles) so crawlers skip
        # the dead /items and still find the data.
        is_raster = ds.record.record_type in RASTER_FAMILY_RECORD_TYPES

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
            # fix(#1372): versioned like every rendered template so a
            # refetching client stops sharing the unversioned cache entry.
            raster_tiles_path = f"/raster-tiles/{ds.id}/tiles/{{z}}/{{x}}/{{y}}.png"
            if ds.tile_cache_version:
                raster_tiles_path = f"{raster_tiles_path}?v={ds.tile_cache_version}"
            links.append(
                {
                    "rel": "tiles",
                    "href": build_url(
                        raster_tiles_path,
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
    # NOT ``Annotated[SearchQueryParams, Query()]`` (used by search_datasets_endpoint):
    # alongside the five OGC params below, that form collapses to a single
    # scalar named ``params`` — worse than defect #1666. The published
    # contract is corrected in ``_repair_depends_bound_query_model``.
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

    # Only the public Records type "dataset" is an accepted OGC resource type;
    # internal storage subtypes stay reachable via record_type instead.
    if resource_types is not None and "dataset" not in resource_types:
        record_ids = ()

    overrides: dict[str, object] = {}
    if sortby is not None:
        parsed = parse_ogc_sortby(sortby)
        overrides["sort_by"] = parsed[0]
        overrides["sort_desc"] = parsed[1]

    # `keywords` and hyphenated `filter-lang` don't bind through the `Depends()`
    # model (pydantic can't name a `filter-lang` param; `list[str]` reads as a
    # body), so both are read from the raw query string here instead.
    raw_keywords = request.query_params.getlist("keywords")
    if raw_keywords:
        # Query string wins over any `params.keywords` FastAPI bound from a
        # GET body via `Depends()`.
        overrides["keywords"] = raw_keywords

    effective_params = params.model_copy(update=overrides) if overrides else params
    effective_params = _resolve_filter_lang(effective_params, request)

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

    user_roles = await check_dataset_access_or_anonymous(db, dataset, record_id, user)

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
        # fix(#1290): filtered where FETCHED so internal keys never enter a
        # payload structure at all, independent of the downstream builder.
        if is_public_asset_key(da.key)
    ]

    item_raster_meta = None
    rec_type = getattr(dataset.record, "record_type", None)
    if rec_type in RASTER_FAMILY_RECORD_TYPES:
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
    # fix(#315): raster_tiles asset href uses the public APP origin.
    public_app_url = await get_public_app_url(db, request=request)
    content = dataset_to_ogc_record(
        dataset,
        public_api_url,
        stac_asset_rows=stac_asset_rows or None,
        raster_meta=item_raster_meta,
        public_app_url=public_app_url,
        preferred_languages=parse_accept_languages(request),
        # fix(#1103): the datasets this one was derived from are checked on
        # their own, separately from the requester's check above.
        lineage_summary=await visible_lineage_summary(
            db, dataset.record, user, user_roles
        ),
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

    Needs materialized ``datasets`` (not just IDs) for
    ``d.record.record_type``. PERF-02: STAC assets and GeoJSON extents run
    concurrently on fresh sessions (AsyncSession isn't concurrency-safe);
    raster meta + VRT source_count stay sequential, since the VRT step
    mutates raster_meta in place. Per-block exceptions degrade to empty.
    """
    all_dataset_ids = [d.id for d in datasets]

    async def _block_stac() -> dict[str, list[dict]]:
        stac_assets: dict[str, list[dict]] = {}
        if not all_dataset_ids:
            return stac_assets
        try:
            from app.core.db import async_session

            async with async_session() as inner_db:
                for da in await get_catalog_port().list_dataset_assets(
                    inner_db, all_dataset_ids
                ):
                    # fix(#1290): same boundary as the item endpoint above.
                    if not is_public_asset_key(da.key):
                        continue
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

    # return_exceptions=True keeps one block's failure from cancelling the
    # other; non-dict results coerce back to empty dicts as the fallback.
    stac_result, extent_result = await asyncio.gather(
        _block_stac(), _block_extents(), return_exceptions=True
    )
    stac_assets_by_dataset: dict[str, list[dict]] = (
        stac_result if isinstance(stac_result, dict) else {}
    )
    extent_geojson_map: dict[str, str | None] = (
        extent_result if isinstance(extent_result, dict) else {}
    )

    # Order is load-bearing: VRT source_count mutates raster_meta in place,
    # so they MUST stay serialized (reusing `db` now the gather is done).
    raster_meta: dict[str, dict] = {}
    raster_ids = [
        d.id
        for d in datasets
        if getattr(d.record, "record_type", None) in RASTER_FAMILY_RECORD_TYPES
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
