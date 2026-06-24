import uuid
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import current_tenant_var
from app.core.dependencies import get_db
from app.core.geo import extent_to_bbox
from app.core.identity import Identity
from app.core.public_urls import get_public_api_url
from app.core.tenancy import is_multi_tenant
from app.modules.auth.dependencies import get_optional_user
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.features.service import (
    get_feature_by_id,
    get_features,
    parse_bbox,
)
from app.platform.extensions import get_billing_extensions, has_extension
from app.standards.ogc.errors import ERROR_RESPONSES_PUBLIC
from app.standards.ogc.schemas import (
    ConformanceResponse,
    LandingPage,
    OGCCollectionMetadata,
    OGCFeatureItemsResponse,
    OGCLink,
    OGCSingleFeatureResponse,
)
from app.standards.ogc.utils import build_url

logger = structlog.stdlib.get_logger(__name__)


async def _emit_ogc_usage_event(table_name: str) -> None:
    """Emit an OGC-serve usage event through the billing-import-free seam (METER-03).

    Called after a successful OGC collection/items serve in multi_tenant mode.
    Uses get_billing_extensions() + hasattr(ext, "on_usage_event") so that:
    - When the cloud overlay is active, CloudMeteringExtension.on_usage_event()
      updates DatasetORM.last_accessed_at via update_last_accessed().
    - When no extension provides on_usage_event (single_tenant / cloud-absent),
      nothing runs — byte-identical OSS behaviour.

    Best-effort: errors are logged and swallowed so a billing hook failure NEVER
    fails an OGC response.

    METER-03: the table_name is carried on the event so the cloud extension can
    scope the last_accessed_at update to the correct dataset row.
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
        except Exception:  # broad: billing hook failures must never fail an OGC response; varied extension errors
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
    """Check if an OGC feature table is cold and delegate to the overlay (COLD-02).

    Mirrors the tile-router _check_cold_rehydrate seam exactly:
    - Returns None immediately when record_status != 'cold' (hot — the common path).
    - Returns None when not is_multi_tenant() or has_extension('cloud') is False
      (single_tenant / community / enterprise — byte-identical, no import attempted).
    - Deferred import of geolens_cloud.cold_tier.rehydrate.check_and_rehydrate inside
      a try/except so the public core image never hard-imports the overlay package.
    - ImportError → return None (overlay absent, serve normally).
    - Broad Exception → log warning, return None (cold-check failure MUST NEVER fail
      an OGC response — T-1214-17).

    When the table IS cold and the overlay is present:
      - status='hydrated' → return None so the caller continues normally.
      - status='warming'  → return a 202 JSONResponse ({status: 'warming', job_id}).

    Args:
        table_name:    The dataset table_name.
        record_status: The record_status from the already-resolved dataset object —
                       no extra DB round-trip on the hot path (T-1214-18).
        tenant_id:     The server-resolved tenant UUID string.
    """
    # Fast path: table is hot.
    if record_status != "cold":
        return None

    # Guard: cold-tier is cloud-only / multi-tenant.
    if not is_multi_tenant():
        return None
    if not has_extension("cloud"):
        return None

    try:
        from geolens_cloud.cold_tier.rehydrate import check_and_rehydrate  # type: ignore[import]

        result = await check_and_rehydrate(table_name=table_name, tenant_id=tenant_id)
    except ImportError:
        return None
    except (
        Exception
    ):  # broad: cold-check failure must NEVER fail an OGC response (T-1214-17)
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


# ---------------------------------------------------------------------------
# OGC Discovery endpoints
# ---------------------------------------------------------------------------


@ogc_router.get("/", response_model=LandingPage, responses=ERROR_RESPONSES_PUBLIC)
async def landing_page(
    request: Request,
    f: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> LandingPage:
    """OGC API landing page -- entry point for machine clients."""
    _validate_f_param(f)
    public_api_url = await get_public_api_url(db, request=request)
    return LandingPage(
        title="GeoLens",
        description="OGC API Records catalog for geospatial datasets",
        links=[
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
                type="application/vnd.oai.openapi+json;version=3.0",
                title="OpenAPI definition",
            ),
            OGCLink(
                href=build_url("/docs", base_url=public_api_url),
                rel="service-doc",
                type="text/html",
                title="API documentation",
            ),
        ],
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
            "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30",
            # OGC API Features Part 1: Core
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
            # OGC API Features Part 3: Filtering
            "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/filter",
            "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/features-filter",
            "http://www.opengis.net/spec/cql2/1.0/conf/cql2-text",
            "http://www.opengis.net/spec/cql2/1.0/conf/cql2-json",
            "http://www.opengis.net/spec/cql2/1.0/conf/basic-cql2",
            # OGC API Records Part 1
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core",
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core-query-parameters",
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/sorting",
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json",
        ]
    )


# ---------------------------------------------------------------------------
# Per-dataset OGC Features endpoints
# ---------------------------------------------------------------------------


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

    # fix(#315): raster/VRT datasets have no backing feature table, so they expose no
    # feature items. Advertise itemType=coverage and omit the rel=items link so
    # clients are not led into the dead /items endpoint (which 404s, see
    # get_collection_items).
    is_raster = dataset.record.record_type in ("raster_dataset", "vrt_dataset")

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
    else:
        # fix(#315): a coverage collection has no rel=items, so without a
        # replacement link the body would only carry self+root and be a
        # dead-end. Advertise the raster tile endpoint so coverage clients have
        # something to dereference. Mirrors the STAC raster_tiles asset href in
        # search/service_records.py (the stable public tile URL).
        links.append(
            OGCLink(
                rel="tiles",
                href=build_url(
                    f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png",
                    base_url=public_api_url,
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

    # METER-03 (Phase 1213-06): emit OGC collection-serve usage event through the
    # billing-import-free seam so the cloud overlay can update last_accessed_at.
    # Best-effort fire-and-forget — errors logged, response unaffected.
    if dataset.table_name:
        await _emit_ogc_usage_event(dataset.table_name)

    # TYPE-N2: return the pydantic model directly so FastAPI's response_model
    # validation actually runs. Previously this was wrapped in JSONResponse,
    # which silently disabled response validation.
    return metadata


@ogc_features_router.get(
    "/collections/{dataset_id}/items/",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": OGCFeatureItemsResponse.model_json_schema()
                }
            }
        },
        **ERROR_RESPONSES_PUBLIC,
    },
    include_in_schema=False,  # trailing-slash alias, hidden from OpenAPI (ROUTE-01 pattern)
)
@ogc_features_router.get(
    "/collections/{dataset_id}/items",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": OGCFeatureItemsResponse.model_json_schema()
                }
            }
        },
        **ERROR_RESPONSES_PUBLIC,
    },
)
async def get_collection_items(
    request: Request,
    dataset_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=200),
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
            "Keyset cursor: returns features with gid > after_gid. Phase 269 H-24 "
            "primary pagination path; use the rel=next link for follow-up pages."
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
    dataset = await _get_visible_dataset(db, user, dataset_id)

    # fix(#315): raster/VRT datasets have no backing PostGIS feature table, so a feature
    # query would raise UndefinedTableError -> 500 (and hold a DB connection).
    # Return a fast 404 before any feature query is attempted.
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Collection '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

    # fix(#315): CQL2 filtering is only supported on the datasets (records) collection,
    # which has a dedicated handler. On per-dataset feature collections a filter
    # would otherwise be silently dropped (or a malformed one return 200), so
    # reject it explicitly with 400 — matching the records-path reject contract.
    if request.query_params.get("filter") is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "CQL2 filter is not supported on feature collections; use the "
                "datasets (records) collection for catalog-level CQL2 filtering."
            ),
        )

    # Parse bbox
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
        # fix(#315): filter/filter-lang are rejected above on feature collections; keep
        # them out of property_filters so they never leak into the SQL WHERE.
        "filter",
        "filter-lang",
    }
    property_filters = {
        k: v for k, v in request.query_params.items() if k not in ogc_reserved
    } or None

    # Build allowed_columns set from dataset column_info for validation
    allowed_columns = None
    if dataset.column_info:
        allowed_columns = {col["name"] for col in dataset.column_info if "name" in col}

    # COLD-02 (Phase 1214-04): cold-rehydrate seam — BEFORE feature query.
    # Uses the already-resolved dataset.record.record_status (no extra DB round-trip,
    # T-1214-18). A cold-check failure is swallowed so it NEVER fails the OGC response
    # (T-1214-17). Published/anon-shared datasets are hot so public viewers never
    # receive 202-warming (T-1214-17).
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
    # ST_AsGeoJSON cost (PERF-N1).
    # H-24: when after_gid is provided, the service uses keyset pagination and
    # ignores offset.
    # fix(#315): the raster/VRT guard above handles datasets that never had a backing
    # table. A genuinely-missing VECTOR table (cold-evicted / partial ingest)
    # still raises ProgrammingError/OperationalError here; mirror the native
    # list_features handler and return 503 rather than an unhandled 500 that
    # holds a DB connection.
    try:
        rows, total = await get_features(
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
        )
    except (ProgrammingError, OperationalError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset table is temporarily unavailable",
        )

    # Convert rows to GeoJSON features
    features = []
    for row in rows:
        features.append(
            {
                "type": "Feature",
                "id": row["gid"],
                "geometry": row.get("geometry"),
                "properties": row.get("properties", {}),
            }
        )

    # Build pagination links
    base_path = f"/collections/{dataset_id}/items"
    active_params: dict[str, str] = {}
    if bbox:
        active_params["bbox"] = bbox
    if datetime_param:
        active_params["datetime"] = datetime_param
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
    # H-24: emit a keyset `next` link when the page is full — primary path.
    # Fall back to offset-based `next`/`prev` for legacy clients only when
    # the request itself used offset.
    if rows and len(rows) == limit:
        next_after_gid = rows[-1]["gid"]
        links.append(
            OGCLink(
                rel="next",
                href=_page_url_keyset(next_after_gid),
                type="application/geo+json",
            )
        )
    elif after_gid is None and offset + limit < total:
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
        numberMatched=total,
        numberReturned=len(features),
        features=features,
        links=links,
    )

    # METER-03 (Phase 1213-06): emit OGC items-serve usage event through the
    # billing-import-free seam so the cloud overlay can update last_accessed_at.
    # Best-effort fire-and-forget — errors logged, response unaffected.
    if dataset.table_name:
        await _emit_ogc_usage_event(dataset.table_name)

    return JSONResponse(
        content=response_data.model_dump(mode="json"),
        media_type="application/geo+json",
        headers={"Content-Crs": "<http://www.opengis.net/def/crs/OGC/1.3/CRS84>"},
    )


@ogc_features_router.get(
    "/collections/{dataset_id}/items/{feature_id}",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": OGCSingleFeatureResponse.model_json_schema()
                }
            }
        },
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

    # fix(#315): raster/VRT datasets have no backing PostGIS feature table, so a
    # feature-by-id query would raise UndefinedTableError -> 500. Return 404
    # before any query is attempted.
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Collection '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

    has_geometry = dataset.geometry_type is not None

    # COLD-02 (Phase 1214-04): cold-rehydrate seam — BEFORE feature-by-id query.
    if dataset.table_name and dataset.record:
        _item_cold_tid = current_tenant_var.get(None)
        _item_cold_result = await _check_cold_rehydrate(
            dataset.table_name,
            dataset.record.record_status or "",
            str(_item_cold_tid) if _item_cold_tid is not None else "",
        )
        if _item_cold_result is not None:
            return _item_cold_result

    # fix(#315): as with get_collection_items, a genuinely-missing VECTOR table
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

    return JSONResponse(
        content=feature.model_dump(mode="json"),
        media_type="application/geo+json",
        headers={"Content-Crs": "<http://www.opengis.net/def/crs/OGC/1.3/CRS84>"},
    )
