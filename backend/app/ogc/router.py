import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_optional_user
from app.auth.models import User
from app.auth.visibility import apply_visibility_filter, get_user_roles
from app.datasets.models import Dataset, DatasetGrant, Record
from app.dependencies import get_db
from app.features.service import get_feature_by_id, get_features, parse_bbox
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

ogc_router = APIRouter(tags=["OGC Features"])

# Separate router for per-dataset OGC Features endpoints.
# Must be registered AFTER collections_router in main.py to avoid
# /collections/{dataset_id} catching literal paths like /collections/datasets.
ogc_features_router = APIRouter(tags=["OGC Features"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extent_to_bbox(extent) -> list[float] | None:
    """Convert a GeoAlchemy2 geometry extent to [minx, miny, maxx, maxy]."""
    if extent is None:
        return None
    try:
        shape = to_shape(extent)
        return list(shape.bounds)
    except Exception:
        return None


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


@ogc_router.get("/", response_model=LandingPage)
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


@ogc_router.get("/conformance", response_model=ConformanceResponse)
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
    "/collections/{dataset_id}", response_model=OGCCollectionMetadata
)
async def get_dataset_collection(
    request: Request,
    dataset_id: uuid.UUID,
    f: str | None = Query(None),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Per-dataset OGC collection metadata with extent, CRS, and items link."""
    _validate_f_param(f)
    public_api_url = await get_public_api_url(db, request=request)
    dataset = await _get_visible_dataset(db, user, dataset_id)

    extent = {}
    bbox = _extent_to_bbox(dataset.record.spatial_extent)
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
    return JSONResponse(
        content=metadata.model_dump(mode="json"), media_type="application/json"
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
        }
    },
)
async def get_collection_items(
    request: Request,
    dataset_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    bbox: str | None = Query(None, description="Bounding box: minx,miny,maxx,maxy"),
    f: str | None = Query(None),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """OGC API Features items endpoint -- returns GeoJSON FeatureCollection for a dataset."""
    _validate_f_param(f)
    public_api_url = await get_public_api_url(db, request=request)
    dataset = await _get_visible_dataset(db, user, dataset_id)

    # Parse bbox
    bbox_parsed = None
    if bbox:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid bbox: {e}")

    has_geometry = dataset.geometry_type is not None

    # Extract property filters from query params (any param not in the OGC reserved set)
    ogc_reserved = {"limit", "offset", "bbox", "f", "datetime", "crs", "api_key"}
    property_filters = {
        k: v for k, v in request.query_params.items() if k not in ogc_reserved
    } or None

    # Build allowed_columns set from dataset column_info for validation
    allowed_columns = None
    if dataset.column_info:
        allowed_columns = {col["name"] for col in dataset.column_info if "name" in col}

    # Reuse existing feature service
    rows, total = await get_features(
        db,
        dataset.table_name,
        limit=limit,
        offset=offset,
        bbox=bbox_parsed,
        has_geometry=has_geometry,
        property_filters=property_filters,
        allowed_columns=allowed_columns,
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
    links = [
        OGCLink(
            rel="self",
            href=build_url(base_path, base_url=public_api_url),
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
        next_params = f"?offset={offset + limit}&limit={limit}"
        if bbox:
            next_params += f"&bbox={bbox}"
        links.append(
            OGCLink(
                rel="next",
                href=build_url(base_path, base_url=public_api_url) + next_params,
                type="application/geo+json",
            )
        )
    if offset > 0:
        prev_offset = max(0, offset - limit)
        prev_params = f"?offset={prev_offset}&limit={limit}"
        if bbox:
            prev_params += f"&bbox={bbox}"
        links.append(
            OGCLink(
                rel="previous",
                href=build_url(base_path, base_url=public_api_url) + prev_params,
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
        }
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
