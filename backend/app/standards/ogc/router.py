import uuid
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
from app.core.db.tenant_session import current_tenant_var
from app.core.db.sqlstate import is_caller_type_fault
from app.core.dependencies import get_db
from app.core.geo import extent_to_bbox
from app.core.identity import Identity
from app.core.persistent_config import OGC_ITEMS_MAX_PAGE_SIZE
from app.core.public_urls import get_public_api_url, get_public_app_url
from app.core.tenancy import is_multi_tenant
from app.core.tile_scope import tile_template_query
from app.modules.auth.dependencies import get_optional_user
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.features.schemas import inline_json_schema
from app.modules.catalog.features.service import (
    feature_table_exists,
    get_feature_by_id,
    get_feature_queryable_columns,
    get_features,
    number_matched_headers,
    parse_bbox,
)
from app.platform.ratelimit import limiter
from app.platform.extensions import (
    get_billing_extensions,
    get_data_serving_extension,
)
from app.standards.ogc.errors import ERROR_RESPONSES_PUBLIC
from app.standards.ogc.filtering import (
    MAX_FEATURE_FILTER_BINDS,
    MAX_FEATURE_FILTER_LENGTH,
    build_feature_queryables_response,
    compile_feature_cql2_ast,
    feature_queryable_columns,
    parse_feature_cql2,
)
from app.standards.ogc.schemas import (
    ConformanceResponse,
    LandingPage,
    OGCCollectionMetadata,
    OGCFeatureItemsResponse,
    OGCLink,
    OGCSingleFeatureResponse,
)
from app.standards.ogc.utils import build_url, link_header_value

logger = structlog.stdlib.get_logger(__name__)

_CRS84_URI = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

# Every route that runs _check_cold_rehydrate can answer 202
# {status: 'warming', job_id} in multi-tenant mode; declaring it keeps
# generated SDK clients from discarding the body or raising UnexpectedStatus.
COLD_WARMING_RESPONSE: dict = {
    202: {
        "description": (
            "Dataset table is cold and being rehydrated (multi-tenant); "
            "poll the job and retry."
        ),
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "job_id": {"type": "string"},
                    },
                }
            }
        },
    }
}


# SQLSTATEs that mean "the CQL2 filter doesn't type against this
# table": undefined operator/function, datatype mismatch, cannot coerce,
# indeterminate datatype. Deliberately NOT the whole 42 class — 42P01 is the
# missing-table 503 and e.g. 42501 (privilege) is an operator problem.
async def _emit_ogc_usage_event(table_name: str) -> None:
    """Emit an OGC usage event through the billing-import-free seam.

    Uses get_billing_extensions() + hasattr(ext, "on_usage_event"): with
    the cloud overlay active, CloudMeteringExtension updates
    DatasetORM.last_accessed_at; with no such extension, nothing runs —
    byte-identical OSS behaviour. Best-effort: errors are logged and
    swallowed so a billing hook failure never fails an OGC response.
    """
    if not is_multi_tenant():
        return
    tenant_id = current_tenant_var.get(None)
    if tenant_id is None:
        return
    for ext in get_billing_extensions():
        if not hasattr(ext, "on_usage_event"):
            continue
        try:
            await ext.on_usage_event(  # type: ignore[attr-defined]
                tenant_id=str(tenant_id),
                dimension="tile_requests",
                value=1,
                table_name=table_name,
            )
        except Exception:  # broad: billing hook failure must never fail the response
            logger.warning(
                "OGC usage event dispatch failed",
                ext=type(ext).__name__,
                table_name=table_name,
                exc_info=True,
            )


async def _check_cold_rehydrate(
    table_name: str,
    record_status: str,
    tenant_id: str,
) -> "JSONResponse | None":
    """Prepare a cold OGC table through the provider-neutral serving seam.

    Mirrors the tile-router seam: returns None when record_status !=
    'cold', when not is_multi_tenant(), or when the Community extension
    returns None. A broad Exception logs and returns None — cold-check
    failure must never fail an OGC response. When cold and
    the overlay is present: 'hydrated' returns None; 'warming' returns a
    202 JSONResponse.

    Args:
        table_name: the dataset table_name.
        record_status: from the already-resolved dataset object — no
            extra database round trip on the hot path.
        tenant_id: the server-resolved tenant UUID string.
    """
    # Fast path: table is hot.
    if record_status != "cold":
        return None

    # Table preparation is only relevant in multi-tenant mode. The Community
    # default is additionally a no-op, preserving the overlay-absent path.
    if not is_multi_tenant():
        return None

    try:
        result = await get_data_serving_extension().prepare_table_for_read(
            table_name=table_name,
            tenant_id=tenant_id,
        )
    except Exception:  # broad: cold-check failure must never fail an OGC response
        logger.warning(
            "ogc_cold_rehydrate_check_failed",
            table_name=table_name,
            tenant_id=tenant_id,
            exc_info=True,
        )
        return None

    if result is None:
        return None

    if result.status == "warming":
        return JSONResponse(
            content={"status": "warming", "job_id": result.job_id},
            status_code=202,
        )

    # status='hydrated': sync rehydrate completed inline.
    return None


ogc_router = APIRouter(tags=["OGC Features"])

# Separate router for per-dataset OGC Features endpoints.
# Must be registered AFTER collections_router in main.py to avoid
# /collections/{dataset_id} catching literal paths like /collections/datasets.
ogc_features_router = APIRouter(tags=["OGC Features"])


def _validate_f_param(f: str | None) -> None:
    """Validate the OGC f query parameter. Only 'json' is supported."""
    if f is not None and f != "json":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format: '{f}'. Only 'json' is supported.",
        )


async def _get_visible_dataset(
    db: AsyncSession, user: Identity | None, dataset_id: uuid.UUID
) -> Dataset:
    """Fetch a dataset with visibility enforcement. Raises 404 if not found or not accessible."""
    from sqlalchemy.orm import joinedload

    stmt = (
        select(Dataset)
        .options(joinedload(Dataset.record))
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    result = await db.execute(stmt)
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{dataset_id}' not found",
        )
    return dataset


@ogc_router.get("/", response_model=LandingPage, responses=ERROR_RESPONSES_PUBLIC)
async def landing_page(
    request: Request,
    response: Response,
    f: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> LandingPage:
    """OGC API landing page -- entry point for machine clients."""
    _validate_f_param(f)
    # This representation is static English; Accept-Language does not select a
    # translated variant, so report the serialized language rather than echoing
    # the requested language.
    response.headers["Content-Language"] = "en"
    public_api_url = await get_public_api_url(db, request=request)
    links = [
        OGCLink(
            href=build_url("/", base_url=public_api_url),
            rel="self",
            type="application/json",
            title="This document",
        ),
        OGCLink(
            href=build_url("/conformance", base_url=public_api_url),
            rel="conformance",
            type="application/json",
            title="Conformance classes",
        ),
        OGCLink(
            href=build_url("/collections", base_url=public_api_url),
            rel="data",
            type="application/json",
            title="Collections",
        ),
        OGCLink(
            href=build_url("/openapi.json", base_url=public_api_url),
            rel="service-desc",
            type="application/vnd.oai.openapi+json;version=3.1",
            title="OpenAPI definition",
        ),
    ]
    # service-doc points at the interactive Swagger UI (/docs), which FastAPI
    # disables in production (settings.is_production -> docs_url=None, see
    # api/main.py). Advertising it unconditionally makes the OGC landing link a
    # dead /docs (404) on every production instance and the demo. service-doc is
    # optional in OGC API Common, so only emit it when /docs actually resolves.
    # service-desc -> /openapi.json stays available in production and is kept.
    if not settings.is_production:
        links.append(
            OGCLink(
                href=build_url("/docs", base_url=public_api_url),
                rel="service-doc",
                type="text/html",
                title="API documentation",
            )
        )
    return LandingPage(
        title="GeoLens",
        description="OGC API Records catalog for geospatial datasets",
        links=links,
    )


@ogc_router.get(
    "/conformance", response_model=ConformanceResponse, responses=ERROR_RESPONSES_PUBLIC
)
async def conformance(f: str | None = Query(None)) -> ConformanceResponse:
    """OGC conformance declaration -- lists supported specification classes."""
    _validate_f_param(f)
    return ConformanceResponse(
        conformsTo=[
            # OGC API Common
            "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core",
            "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/landing-page",
            "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/json",
            # OGC API Features Part 1: Core
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
            # Part 3 conformance is advertised because `filter=` and
            # per-collection queryables are implemented together.
            "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/queryables",
            "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/filter",
            "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/features-filter",
            # CQL2 query language (Records collection + feature collections).
            # advanced-comparison-operators and basic-spatial-functions are
            # advertised because every operator they cover is tested in both
            # encodings (test_ogc_features_filter.py), including the encoding
            # shims in standards/ogc/filtering.py that final-spec clients need.
            "http://www.opengis.net/spec/cql2/1.0/conf/cql2-text",
            "http://www.opengis.net/spec/cql2/1.0/conf/cql2-json",
            "http://www.opengis.net/spec/cql2/1.0/conf/basic-cql2",
            "http://www.opengis.net/spec/cql2/1.0/conf/advanced-comparison-operators",
            "http://www.opengis.net/spec/cql2/1.0/conf/basic-spatial-functions",
            # OGC API Records Part 1
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core",
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core-query-parameters",
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/sorting",
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json",
        ]
    )


@ogc_features_router.get(
    "/collections/{dataset_id}",
    response_model=OGCCollectionMetadata,
    responses=ERROR_RESPONSES_PUBLIC,
)
async def get_dataset_collection(
    request: Request,
    dataset_id: uuid.UUID,
    f: str | None = Query(None),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> OGCCollectionMetadata:
    """Per-dataset OGC collection metadata with extent, CRS, and items link."""
    _validate_f_param(f)
    public_api_url = await get_public_api_url(db, request=request)
    dataset = await _get_visible_dataset(db, user, dataset_id)

    extent = {}
    bbox = extent_to_bbox(dataset.record.spatial_extent)
    if bbox:
        extent["spatial"] = {
            "bbox": [bbox],
            "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        }
    if (
        dataset.record.temporal_start is not None
        or dataset.record.temporal_end is not None
    ):
        extent["temporal"] = {
            "interval": [
                [
                    dataset.record.temporal_start.isoformat()
                    if dataset.record.temporal_start
                    else "..",
                    dataset.record.temporal_end.isoformat()
                    if dataset.record.temporal_end
                    else "..",
                ]
            ]
        }

    # Raster/VRT datasets have no backing feature table, so they expose no
    # feature items. Advertise itemType=coverage and omit the rel=items link so
    # clients are not led into the dead /items endpoint (which 404s, see
    # get_collection_items).
    is_raster = dataset.record.record_type in RASTER_FAMILY_RECORD_TYPES

    links = [
        OGCLink(
            rel="self",
            href=build_url(
                f"/collections/{dataset.id}",
                base_url=public_api_url,
            ),
            type="application/json",
            title="This collection",
        ),
    ]
    if not is_raster:
        links.append(
            OGCLink(
                rel="items",
                href=build_url(
                    f"/collections/{dataset.id}/items",
                    base_url=public_api_url,
                ),
                type="application/geo+json",
                title="Features",
            )
        )
        # OGC Features Part 3 queryables link — required by the
        # conf/queryables class, vector collections only (raster has no items).
        links.append(
            OGCLink(
                rel="http://www.opengis.net/def/rel/ogc/1.0/queryables",
                href=build_url(
                    f"/collections/{dataset.id}/queryables",
                    base_url=public_api_url,
                ),
                type="application/schema+json",
                title="Queryables",
            )
        )
    else:
        # A coverage collection has no rel=items, so without a
        # replacement link the body would only carry self+root and be a
        # dead-end. Advertise the raster tile endpoint so coverage clients have
        # something to dereference. NOTE: raster tiles are served at the public
        # APP origin (/raster-tiles/...), which nginx rewrites to the internal
        # tile proxy; the /api origin has no such route, so use public_app_url.
        public_app_url = await get_public_app_url(db, request=request)
        # Versioned like every rendered template so a
        # refetching client stops sharing the unversioned cache entry.
        raster_tiles_path = (
            f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png"
            + tile_template_query(
                dataset.tile_cache_version, dataset.publication_version
            )
        )
        links.append(
            OGCLink(
                rel="tiles",
                href=build_url(
                    raster_tiles_path,
                    base_url=public_app_url,
                ),
                type="image/png",
                title="Raster tiles",
            )
        )
    links.append(
        OGCLink(
            rel="root",
            href=build_url("/", base_url=public_api_url),
            type="application/json",
            title="Landing page",
        )
    )

    metadata = OGCCollectionMetadata(
        id=str(dataset.id),
        title=dataset.record.title,
        description=dataset.record.summary,
        extent=extent if extent else None,
        itemType="coverage" if is_raster else "feature",
        links=links,
    )

    # Emit OGC collection-serve usage event through the
    # billing-import-free seam so the cloud overlay can update last_accessed_at.
    # Best-effort fire-and-forget — errors logged, response unaffected.
    if dataset.table_name:
        await _emit_ogc_usage_event(dataset.table_name)

    # Return the Pydantic model directly so FastAPI validates the response.
    return metadata


@ogc_features_router.get(
    "/collections/{dataset_id}/queryables",
    response_class=JSONResponse,
    responses={**COLD_WARMING_RESPONSE, **ERROR_RESPONSES_PUBLIC},
)
async def get_collection_queryables(
    request: Request,
    dataset_id: uuid.UUID,
    f: str | None = Query(None),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Queryable properties for one feature collection (OGC Features Part 3).

    Derived from the live table schema rather than the stored column_info
    snapshot, so the advertised set always matches what `filter=`
    on /items validates against. `additionalProperties: false` is what makes
    rejecting filters on unlisted properties spec-conformant.
    """
    _validate_f_param(f)
    public_api_url = await get_public_api_url(db, request=request)
    dataset = await _get_visible_dataset(db, user, dataset_id)

    # Mirrors get_collection_items: raster collections have no feature table.
    if dataset.record.record_type in RASTER_FAMILY_RECORD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Collection '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

    # A cold (evicted) table has no information_schema
    # rows, so deriving queryables from it would publish an attribute-less
    # document as authoritative. Run the same cold-rehydrate seam as /items
    # BEFORE reading the live schema (202-warming instead of a wrong 200).
    if dataset.table_name and dataset.record:
        _q_cold_tid = current_tenant_var.get(None)
        _q_cold_result = await _check_cold_rehydrate(
            dataset.table_name,
            dataset.record.record_status or "",
            str(_q_cold_tid) if _q_cold_tid is not None else "",
        )
        if _q_cold_result is not None:
            return _q_cold_result

    # `get_column_info` returns [] for a MISSING table as
    # well as for an attribute-less one. A missing table (partial ingest /
    # eviction race) must stay the same retryable 503 the /items path
    # reports, not publish an empty queryables document as authoritative.
    # Schema-introspection database errors are
    # operational — same 503 classification as the items path.
    try:
        if not await feature_table_exists(db, dataset.table_name):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dataset table is temporarily unavailable",
            )
        live_columns = await get_feature_queryable_columns(db, dataset.table_name)
    except (ProgrammingError, OperationalError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset table is temporarily unavailable",
        )

    queryables = feature_queryable_columns(
        live_columns,
        dataset.geometry_type,
    )
    return JSONResponse(
        content=build_feature_queryables_response(
            str(dataset.id),
            dataset.record.title,
            queryables,
            public_api_url,
        ),
        media_type="application/schema+json",
    )


# CQL2 compile is synchronous, event-loop-blocking work, and
# the filter is the one input letting an anonymous caller choose how
# much of it to buy. The single-pass rename in filtering.py cut the
# pathological case from 2.4s to 40ms, but shapes under the bind cap
# still reach hundreds of binds — the rename bounds cost per request,
# this bounds rate. 10/second sits far above any interactive client
# (QGIS/pygeoapi paging) and far below what keeps the loop busy.
_FILTERED_ITEMS_RATE_LIMIT = "10/second"


def _items_request_carries_no_filter(request: Request) -> bool:
    """Exempt an unfiltered items request from the filter-specific limit.

    A bulk ``ogr2ogr OAPIF:`` export pages this route without buying any
    compile cost, so only a request carrying ``filter=`` is charged.

    CONSTRAINT: the decorator below MUST keep ``override_defaults=False``.
    slowapi decides whether to fall back to global default limits from
    the route limit's presence and ``override_defaults``, BEFORE
    ``exempt_when`` is consulted. With slowapi's default
    ``override_defaults=True``, an exempted route limit would leave the
    ordinary paging request with no limit at all.
    """
    return "filter" not in request.query_params


# Two of the four refusals are resource bounds on a VALID
# filter, which the generic "invalid query parameters" 400 the route inherits
# does not describe.
FILTER_BAD_REQUEST_RESPONSE = {
    **ERROR_RESPONSES_PUBLIC[400],
    "description": (
        "Bad request. Either a query parameter is invalid, or the `filter` was "
        "refused. A CQL2 filter is refused when it names a queryable this "
        "collection does not publish, or uses an operator this server does not "
        "implement; when it is longer than "
        f"{MAX_FEATURE_FILTER_LENGTH:,} characters; when it nests deeper than "
        "the parser will walk; or when it expands to more than "
        f"{MAX_FEATURE_FILTER_BINDS:,} bound parameters. The last two are "
        "resource bounds rather than syntax errors, so the filter can be valid "
        "CQL2 and still be declined: an `IN` list reaches the parameter "
        "ceiling well before the character limit, since `render_postcompile` "
        "expands it to one parameter per member. Both are answered "
        "deterministically, so a client that splits the filter and pages the "
        "results gets the same rows."
    ),
}


@ogc_features_router.get(
    "/collections/{dataset_id}/items/",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": inline_json_schema(OGCFeatureItemsResponse)
                }
            }
        },
        **ERROR_RESPONSES_PUBLIC,
        400: FILTER_BAD_REQUEST_RESPONSE,
    },
    include_in_schema=False,  # Trailing-slash alias hidden from OpenAPI.
)
@ogc_features_router.get(
    "/collections/{dataset_id}/items",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": inline_json_schema(OGCFeatureItemsResponse)
                }
            }
        },
        **COLD_WARMING_RESPONSE,
        **ERROR_RESPONSES_PUBLIC,
        400: FILTER_BAD_REQUEST_RESPONSE,
    },
)
@limiter.limit(
    _FILTERED_ITEMS_RATE_LIMIT,
    exempt_when=_items_request_carries_no_filter,
    override_defaults=False,
)
async def get_collection_items(
    request: Request,
    dataset_id: uuid.UUID,
    limit: int = Query(
        10,
        ge=1,
        description=(
            "Page size for bulk GeoJSON export. The maximum is an "
            "admin-configurable ceiling (default 1000; Network settings tab, "
            "`ogc_items_max_page_size`) rather than the 200 used by offset-paged "
            "list endpoints, because this route pages via the constant-time "
            "`after_gid` keyset cursor. Per OGC API Features Core "
            "/req/core/fc-limit-response-1(C) a value above the ceiling is "
            "clamped to it, not rejected."
        ),
    ),
    offset: int = Query(
        0,
        ge=0,
        description=(
            "Legacy offset-based pagination. Prefer `after_gid` keyset cursor "
            "(via the `next` link) — offset is retained for backward "
            "compatibility but is O(N) at high values."
        ),
    ),
    after_gid: int | None = Query(
        None,
        ge=0,
        description=(
            "Keyset cursor: returns features with gid > after_gid. The preferred "
            "pagination path; use the rel=next link for follow-up pages."
        ),
    ),
    bbox: str | None = Query(None, description="Bounding box: minx,miny,maxx,maxy"),
    datetime_param: str | None = Query(
        None,
        alias="datetime",
        description="OGC datetime interval: instant, start/end, ../end, start/..",
    ),
    f: str | None = Query(None),
    include_geometry: bool = Query(
        True,
        description="Include geometry in response. Set to false for attribute-only queries.",
    ),
    filter_expr: str | None = Query(
        None,
        alias="filter",
        description=(
            "CQL2 filter expression evaluated server-side against this "
            "collection's OGC Features Part 3 queryables document. Combines "
            "with bbox and property filters by AND."
        ),
    ),
    filter_lang: str = Query(
        "cql2-text",
        alias="filter-lang",
        description="Filter language: cql2-text (default) or cql2-json.",
    ),
    filter_crs: str | None = Query(
        None,
        alias="filter-crs",
        description=(
            "CRS of filter geometries. Only CRS84 "
            "(http://www.opengis.net/def/crs/OGC/1.3/CRS84) is supported."
        ),
    ),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """OGC API Features items endpoint -- returns GeoJSON FeatureCollection for a dataset.

    Note: ``datetime`` is accepted per OGC API Features Core but acts as a
    no-op for per-dataset feature queries.  Per-dataset feature tables contain
    user-uploaded data with no standard temporal column, so the spec provision
    "if the collection does not include temporal information, the datetime
    parameter SHALL be ignored" applies (OGC 17-069r4 §7.15.5).
    """
    _validate_f_param(f)
    public_api_url = await get_public_api_url(db, request=request)

    # The page-size ceiling is an admin-configurable PersistentConfig value,
    # not a static Query(le=...). Per OGC
    # API Features Core /req/core/fc-limit-response-1(C) a limit above the
    # maximum SHALL NOT error — clamp to the ceiling instead (mirrors the STAC
    # sibling STAC endpoint. max(1, ...) guards a ceiling mis-set to 0; the clamped value
    # flows into the feature query and the echoed self/next links.
    max_page_size = await OGC_ITEMS_MAX_PAGE_SIZE.get(db)
    limit = min(limit, max(1, max_page_size))

    dataset = await _get_visible_dataset(db, user, dataset_id)

    # Raster/VRT datasets have no backing PostGIS feature table, so a feature
    # query would raise UndefinedTableError -> 500 (and hold a DB connection).
    # Return a fast 404 before any feature query is attempted.
    if dataset.record.record_type in RASTER_FAMILY_RECORD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Collection '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

    # `filter=` is now evaluated server-side (compiled below,
    # after the cold-rehydrate seam). Filter geometries are WGS84-only —
    # reject any other filter-crs instead of misinterpreting coordinates.
    if filter_crs is not None and filter_crs != _CRS84_URI:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported filter-crs: only {_CRS84_URI} is supported.",
        )

    bbox_parsed = None
    if bbox:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid bbox: {e}"
            )

    has_geometry = dataset.geometry_type is not None

    # Extract property filters from query params (any param not in the OGC reserved set)
    ogc_reserved = {
        "limit",
        "offset",
        "after_gid",
        "bbox",
        "f",
        "datetime",
        "crs",
        "api_key",
        "include_geometry",
        # The CQL2 filter params bind explicitly above; keep them
        # out of property_filters so they never double as column filters.
        "filter",
        "filter-lang",
        "filter-crs",
    }
    property_filters = {
        k: v for k, v in request.query_params.items() if k not in ogc_reserved
    } or None

    allowed_columns = None
    if dataset.column_info:
        allowed_columns = {col["name"] for col in dataset.column_info if "name" in col}

    # Cold-rehydrate seam — BEFORE feature query.
    # Uses the already-resolved dataset.record.record_status with no extra DB
    # round trip. A cold-check failure is swallowed so it never fails the OGC
    # response. Published or anonymously shared datasets stay hot, so public
    # viewers never receive a warming response.
    if dataset.table_name and dataset.record:
        _ogc_cold_tid = current_tenant_var.get(None)
        _ogc_cold_result = await _check_cold_rehydrate(
            dataset.table_name,
            dataset.record.record_status or "",
            str(_ogc_cold_tid) if _ogc_cold_tid is not None else "",
        )
        if _ogc_cold_result is not None:
            return _ogc_cold_result

    # Reuse existing feature service. Pass the cached feature_count so the
    # pagination COUNT(*) collapses into a constant-time lookup, and honor
    # include_geometry so clients that don't need geometry avoid the
    # ST_AsGeoJSON cost. When after_gid is provided, the service uses keyset pagination and
    # ignores offset.
    # The raster/VRT guard above only covers datasets that never
    # had a backing table. A genuinely-missing VECTOR table (cold-evicted /
    # partial ingest) still raises here; mirror list_features and return
    # 503, not an unhandled 500 that holds a DB connection.
    # Compile the CQL2 filter against the live table schema —
    # the same schema authority the queryables document publishes. This runs
    # after the cold-rehydrate seam so a cold table warms (202) instead of
    # misreporting its columns as unknown queryables.
    cql2_where: str | None = None
    cql2_binds: list = []
    if filter_expr is not None:
        # Ordering is deliberate: a parse failure is the caller's bug (400,
        # no database access); a missing table
        # yields an empty live schema, and compiling against it would 400
        # every attribute filter as an unknown property, so table
        # availability stays the retryable 503; schema-dependent validation
        # runs last.
        filter_ast = parse_feature_cql2(filter_expr, filter_lang)
        # The schema-introspection queries carry no
        # caller input, so any database error here is operational — classify
        # it exactly like the feature query's 503, not a 500.
        try:
            if not await feature_table_exists(db, dataset.table_name):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Dataset table is temporarily unavailable",
                )
            live_columns = await get_feature_queryable_columns(db, dataset.table_name)
        except (ProgrammingError, OperationalError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dataset table is temporarily unavailable",
            )
        queryables = feature_queryable_columns(
            live_columns,
            dataset.geometry_type,
        )
        cql2_where, cql2_binds = compile_feature_cql2_ast(filter_ast, queryables)

    try:
        # A full page must be distinguishable from a full
        # *final* page, or a feature count that is an exact multiple of `limit`
        # emits a phantom keyset `next` to an empty page.
        # the over-fetch that answers it moved into get_features, which reports
        # it as `has_more`, so every caller gets the same answer.
        page = await get_features(
            db,
            dataset.table_name,
            limit=limit,
            offset=offset,
            after_gid=after_gid,
            bbox=bbox_parsed,
            has_geometry=has_geometry,
            property_filters=property_filters,
            allowed_columns=allowed_columns,
            include_geometry=include_geometry,
            cached_feature_count=dataset.feature_count,
            cql2_where=cql2_where,
            cql2_binds=cql2_binds,
        )
    except ValueError as exc:
        # An unparseable property-filter value is rejected before
        # the query runs, naming the property.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DBAPIError as exc:
        # /with a filter or property-filter active,
        # a type-shaped DB error is the filter itself (e.g. incomparable
        # types pre-validation let through) — report as the caller's 400,
        # never an unhandled 500 (QA finding B3). Only type/data SQLSTATEs
        # count: class 22, 42xxx operator/cast, client-side bind
        # DataErrors; everything else keeps the retryable 503.
        # Classification lives in `is_caller_type_fault` (shared with the
        # native features list); catch widened to DBAPIError since
        # asyncpg reports an unencodable value as bare DBAPIError with
        # SQLSTATE 22000, matching no narrower subclass.
        caller_predicate = cql2_where is not None or bool(property_filters)
        if caller_predicate and is_caller_type_fault(exc):
            source = "CQL2 filter" if cql2_where is not None else "Property filter"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{source} is not evaluable against this collection's "
                    "property types"
                ),
            )
        if isinstance(exc, (ProgrammingError, OperationalError)):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dataset table is temporarily unavailable",
            )
        raise

    features = [
        {
            "type": "Feature",
            "id": row["gid"],
            "geometry": row.get("geometry"),
            "properties": row.get("properties", {}),
        }
        for row in page.rows
    ]

    base_path = f"/collections/{dataset_id}/items"
    active_params: dict[str, str] = {}
    if bbox:
        active_params["bbox"] = bbox
    if datetime_param:
        active_params["datetime"] = datetime_param
    # `include_geometry` is excluded from property_filters (it is
    # listed in ogc_reserved) and was never added here either, so a client
    # that opted out of geometry on page 1 got it back on page 2 via the
    # rel=next link this block builds, and the self link stopped describing
    # the request that produced the response.
    if not include_geometry:
        active_params["include_geometry"] = "false"
    if filter_expr is not None:
        active_params["filter"] = filter_expr
        if filter_lang != "cql2-text":
            active_params["filter-lang"] = filter_lang
        if filter_crs:
            active_params["filter-crs"] = filter_crs
    if property_filters:
        active_params.update(property_filters)

    def _page_url_offset(off: int) -> str:
        params = {"limit": str(limit), "offset": str(off), **active_params}
        return build_url(base_path, base_url=public_api_url) + "?" + urlencode(params)

    def _page_url_keyset(after: int) -> str:
        params = {"limit": str(limit), "after_gid": str(after), **active_params}
        return build_url(base_path, base_url=public_api_url) + "?" + urlencode(params)

    # Self link mirrors whichever pagination mode the client requested.
    if after_gid is not None:
        self_qs = urlencode(
            {"limit": str(limit), "after_gid": str(after_gid), **active_params}
        )
    else:
        self_qs = urlencode(
            {"limit": str(limit), "offset": str(offset), **active_params}
        )
    self_params = f"?{self_qs}"

    links = [
        OGCLink(
            rel="self",
            href=build_url(base_path, base_url=public_api_url) + self_params,
            type="application/geo+json",
        ),
        OGCLink(
            rel="collection",
            href=build_url(
                f"/collections/{dataset_id}",
                base_url=public_api_url,
            ),
            type="application/json",
        ),
    ]
    # Emit a keyset `next` link when more rows exist — primary path.
    # Fall back to offset-based `next`/`prev` for legacy clients only when
    # the request itself used offset.
    if page.rows and page.has_more:
        next_after_gid = page.rows[-1]["gid"]
        links.append(
            OGCLink(
                rel="next",
                href=_page_url_keyset(next_after_gid),
                type="application/geo+json",
            )
        )
    elif after_gid is None and page.has_more:
        # page.has_more drives the link because numberMatched may be a planner
        # estimate at or below the number of rows already served.
        links.append(
            OGCLink(
                rel="next",
                href=_page_url_offset(offset + limit),
                type="application/geo+json",
            )
        )
    if after_gid is None and offset > 0:
        links.append(
            OGCLink(
                rel="prev",
                href=_page_url_offset(max(0, offset - limit)),
                type="application/geo+json",
            )
        )

    response_data = OGCFeatureItemsResponse(
        numberMatched=page.total,
        numberReturned=len(features),
        features=features,
        links=links,
    )

    # Emit OGC items-serve usage event through the
    # billing-import-free seam so the cloud overlay can update last_accessed_at.
    # Best-effort fire-and-forget — errors logged, response unaffected.
    if dataset.table_name:
        await _emit_ogc_usage_event(dataset.table_name)

    headers = {
        "Content-Crs": "<http://www.opengis.net/def/crs/OGC/1.3/CRS84>",
        **number_matched_headers(page.total_is_estimate),
    }
    if link_value := link_header_value(links):
        headers["Link"] = link_value
    return JSONResponse(
        content=response_data.model_dump(mode="json"),
        media_type="application/geo+json",
        headers=headers,
    )


@ogc_features_router.get(
    "/collections/{dataset_id}/items/{feature_id}",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": inline_json_schema(OGCSingleFeatureResponse)
                }
            }
        },
        **COLD_WARMING_RESPONSE,
        **ERROR_RESPONSES_PUBLIC,
    },
)
async def get_collection_item_feature(
    request: Request,
    dataset_id: uuid.UUID,
    feature_id: int,
    f: str | None = Query(None),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """OGC API Features single feature endpoint -- returns a GeoJSON Feature."""
    _validate_f_param(f)
    public_api_url = await get_public_api_url(db, request=request)
    dataset = await _get_visible_dataset(db, user, dataset_id)

    # Raster/VRT datasets have no backing PostGIS feature table, so a
    # feature-by-id query would raise UndefinedTableError -> 500. Return 404
    # before any query is attempted.
    if dataset.record.record_type in RASTER_FAMILY_RECORD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Collection '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

    has_geometry = dataset.geometry_type is not None

    # Cold-rehydrate seam — BEFORE feature-by-id query.
    if dataset.table_name and dataset.record:
        _item_cold_tid = current_tenant_var.get(None)
        _item_cold_result = await _check_cold_rehydrate(
            dataset.table_name,
            dataset.record.record_status or "",
            str(_item_cold_tid) if _item_cold_tid is not None else "",
        )
        if _item_cold_result is not None:
            return _item_cold_result

    # As with get_collection_items, a genuinely-missing VECTOR table
    # (cold-evicted / partial ingest) raises ProgrammingError/OperationalError;
    # return 503 rather than an unhandled 500. The raster/VRT 404 guard above
    # handles datasets that never had a backing table.
    try:
        row = await get_feature_by_id(
            db, dataset.table_name, feature_id, has_geometry=has_geometry
        )
    except (ProgrammingError, OperationalError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset table is temporarily unavailable",
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature '{feature_id}' not found in collection '{dataset_id}'",
        )

    feature = OGCSingleFeatureResponse(
        id=row["gid"],
        geometry=row.get("geometry"),
        properties=row.get("properties"),
        links=[
            OGCLink(
                rel="self",
                href=build_url(
                    f"/collections/{dataset_id}/items/{feature_id}",
                    base_url=public_api_url,
                ),
                type="application/geo+json",
            ),
            OGCLink(
                rel="collection",
                href=build_url(
                    f"/collections/{dataset_id}",
                    base_url=public_api_url,
                ),
                type="application/json",
            ),
        ],
    )

    headers = {"Content-Crs": "<http://www.opengis.net/def/crs/OGC/1.3/CRS84>"}
    if link_value := link_header_value(feature.links):
        headers["Link"] = link_value
    return JSONResponse(
        content=feature.model_dump(mode="json"),
        media_type="application/geo+json",
        headers=headers,
    )
