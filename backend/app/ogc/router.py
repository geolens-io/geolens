import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_optional_user
from app.auth.models import User
from app.auth.visibility import apply_visibility_filter, get_user_roles
from app.datasets.models import Dataset, DatasetGrant, Record
from app.dependencies import get_db
from app.features.service import get_feature_by_id, get_features, parse_bbox
from app.ogc.errors import ERROR_RESPONSES_PUBLIC
from app.ogc.schemas import (
    ConformanceResponse,
    LandingPage,
    OGCCollectionMetadata,
    OGCFeatureItemsResponse,
    OGCLink,
    OGCSingleFeatureResponse,
)
from app.ogc.utils import build_url
from app.public_urls import get_public_api_url
from app.utils.geo import extent_to_bbox

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
    db: AsyncSession, user: User | None, dataset_id: uuid.UUID
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
    user: User | None = Depends(get_optional_user),
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

    metadata = OGCCollectionMetadata(
        id=str(dataset.id),
        title=dataset.record.title,
        description=dataset.record.summary,
        extent=extent if extent else None,
        links=[
            OGCLink(
                rel="self",
                href=build_url(
                    f"/collections/{dataset.id}",
                    base_url=public_api_url,
                ),
                type="application/json",
                title="This collection",
            ),
            OGCLink(
                rel="items",
                href=build_url(
                    f"/collections/{dataset.id}/items",
                    base_url=public_api_url,
                ),
                type="application/geo+json",
                title="Features",
            ),
            OGCLink(
                rel="root",
                href=build_url("/", base_url=public_api_url),
                type="application/json",
                title="Landing page",
            ),
        ],
    )
    # TYPE-N2: return the pydantic model directly so FastAPI's response_model
    # validation actually runs. Previously this was wrapped in JSONResponse,
    # which silently disabled response validation.
    return metadata


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
    limit: int = Query(10, ge=1, le=1000),
    offset: int = Query(0, ge=0),
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
    user: User | None = Depends(get_optional_user),
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
        "bbox",
        "f",
        "datetime",
        "crs",
        "api_key",
        "include_geometry",
    }
    property_filters = {
        k: v for k, v in request.query_params.items() if k not in ogc_reserved
    } or None

    # Build allowed_columns set from dataset column_info for validation
    allowed_columns = None
    if dataset.column_info:
        allowed_columns = {col["name"] for col in dataset.column_info if "name" in col}

    # Reuse existing feature service. Pass the cached feature_count so the
    # pagination COUNT(*) collapses into a constant-time lookup, and honor
    # include_geometry so clients that don't need geometry avoid the
    # ST_AsGeoJSON cost (PERF-N1).
    rows, total = await get_features(
        db,
        dataset.table_name,
        limit=limit,
        offset=offset,
        bbox=bbox_parsed,
        has_geometry=has_geometry,
        property_filters=property_filters,
        allowed_columns=allowed_columns,
        include_geometry=include_geometry,
        cached_feature_count=dataset.feature_count,
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

    def _page_url(off: int) -> str:
        params = {"limit": str(limit), "offset": str(off), **active_params}
        return build_url(base_path, base_url=public_api_url) + "?" + urlencode(params)

    self_params = (
        f"?{urlencode({'limit': str(limit), 'offset': str(offset), **active_params})}"
    )
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
    if offset + limit < total:
        links.append(
            OGCLink(
                rel="next",
                href=_page_url(offset + limit),
                type="application/geo+json",
            )
        )
    if offset > 0:
        links.append(
            OGCLink(
                rel="prev",
                href=_page_url(max(0, offset - limit)),
                type="application/geo+json",
            )
        )

    response_data = OGCFeatureItemsResponse(
        numberMatched=total,
        numberReturned=len(features),
        features=features,
        links=links,
    )

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
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """OGC API Features single feature endpoint -- returns a GeoJSON Feature."""
    _validate_f_param(f)
    public_api_url = await get_public_api_url(db, request=request)
    dataset = await _get_visible_dataset(db, user, dataset_id)
    has_geometry = dataset.geometry_type is not None

    row = await get_feature_by_id(
        db, dataset.table_name, feature_id, has_geometry=has_geometry
    )
    if row is None:
        raise HTTPException(
            status_code=404,
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
