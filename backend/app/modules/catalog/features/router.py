"""Feature-serving endpoints: paginated GeoJSON from PostGIS data tables."""

import uuid
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user, require_permission
from app.modules.catalog.authorization import check_dataset_access
from app.modules.catalog.datasets.domain.service import get_dataset
from app.core.dependencies import get_db
from app.modules.catalog.features.schemas import (
    FeatureCreate,
    FeatureReplace,
    FeatureUpdate,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
)
from app.modules.catalog.features.service import (
    delete_feature,
    get_feature_by_id,
    get_features,
    get_features_geojson_z,
    insert_feature,
    parse_bbox,
    refresh_dataset_metadata,
    replace_feature,
    update_feature,
)
from app.platform.cache.provider import get_tile_cache
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH, ERROR_RESPONSES_WRITE
from app.standards.ogc.utils import build_url
from app.core.public_urls import get_public_api_url

logger = structlog.get_logger()

features_router = APIRouter(prefix="/datasets", tags=["Features"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@features_router.get(
    "/{dataset_id}/features.geojson",
    response_class=JSONResponse,
    responses={200: {"content": {"application/geo+json": {}}}, **ERROR_RESPONSES_AUTH},
)
async def get_features_geojson_z_endpoint(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return up to 5,000 features as RFC 7946 GeoJSON with Z coordinates."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access(db, dataset, dataset_id, user)

    if dataset.geometry_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset has no geometry",
        )

    try:
        rows, truncated, total_count = await get_features_geojson_z(
            db, dataset.table_name, cap=5000, cached_feature_count=dataset.feature_count
        )
    except (ProgrammingError, OperationalError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset table is unavailable",
        )

    body = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": row["gid"],
                "geometry": row["geometry"],
                "properties": row["properties"],
            }
            for row in rows
        ],
        "truncated": truncated,
        "total_count": total_count,
    }

    return JSONResponse(content=body, media_type="application/geo+json")


@features_router.get(
    "/{dataset_id}/features/",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": GeoJSONFeatureCollection.model_json_schema()
                }
            }
        },
        **ERROR_RESPONSES_AUTH,
    },
)
async def list_features(
    dataset_id: uuid.UUID,
    request: Request,
    limit: int = Query(10, ge=1, le=200),
    offset: int = Query(
        0,
        ge=0,
        description=(
            "Legacy offset-based pagination. Phase 269 H-24 lowered the "
            "max limit to 200 from 1000."
        ),
    ),
    bbox: str | None = Query(None, description="Bounding box: minx,miny,maxx,maxy"),
    include_geometry: bool = Query(True, description="Include geometry in response"),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get paginated GeoJSON features for a dataset."""
    # Fetch dataset
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # RBAC check
    await check_dataset_access(db, dataset, dataset_id, user)

    # Parse bbox
    parsed_bbox: list[float] | None = None
    if bbox is not None:
        try:
            parsed_bbox = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )

    # Extract property filters from query params
    reserved_params = {"limit", "offset", "bbox", "include_geometry", "api_key"}
    column_names = {col["name"] for col in (dataset.column_info or [])}
    property_filters: dict[str, str] = {}
    for key, value in request.query_params.items():
        if key not in reserved_params and key in column_names:
            property_filters[key] = value

    has_geometry = dataset.geometry_type is not None

    # Query features
    try:
        rows, total = await get_features(
            db,
            dataset.table_name,
            limit=limit,
            offset=offset,
            bbox=parsed_bbox,
            property_filters=property_filters if property_filters else None,
            has_geometry=has_geometry,
            allowed_columns=column_names,
            include_geometry=include_geometry,
            cached_feature_count=dataset.feature_count,
        )
    except (ProgrammingError, OperationalError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset table is unavailable",
        )

    # Build GeoJSON features
    features = [
        GeoJSONFeature(
            id=row["gid"],
            geometry=row["geometry"],
            properties=row["properties"],
        )
        for row in rows
    ]

    # Build pagination links
    base_path = f"/datasets/{dataset_id}/features/"
    public_api_url = await get_public_api_url(db, request=request)

    # Collect active query params for pagination link continuity
    active_params: dict[str, str] = {}
    if bbox is not None:
        active_params["bbox"] = bbox
    for key, value in property_filters.items():
        active_params[key] = value

    links: list[dict] = [
        {
            "rel": "self",
            "href": build_url(base_path, base_url=public_api_url),
            "type": "application/geo+json",
        },
    ]

    if offset + limit < total:
        next_params = {"offset": str(offset + limit), "limit": str(limit)}
        next_params.update(active_params)
        links.append(
            {
                "rel": "next",
                "href": build_url(base_path, base_url=public_api_url)
                + "?"
                + urlencode(next_params),
                "type": "application/geo+json",
            }
        )

    if offset > 0:
        prev_params = {"offset": str(max(0, offset - limit)), "limit": str(limit)}
        prev_params.update(active_params)
        links.append(
            {
                "rel": "prev",
                "href": build_url(base_path, base_url=public_api_url)
                + "?"
                + urlencode(prev_params),
                "type": "application/geo+json",
            }
        )

    response = GeoJSONFeatureCollection(
        numberMatched=total,
        numberReturned=len(features),
        features=features,
        links=links,
    )

    return JSONResponse(
        content=response.model_dump(mode="json"),
        media_type="application/geo+json",
    )


@features_router.get(
    "/{dataset_id}/features/{gid}",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {"schema": GeoJSONFeature.model_json_schema()}
            }
        },
        **ERROR_RESPONSES_AUTH,
    },
)
async def get_single_feature(
    dataset_id: uuid.UUID,
    gid: int,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a single GeoJSON feature by gid."""
    # Fetch dataset
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # RBAC check
    await check_dataset_access(db, dataset, dataset_id, user)

    has_geometry = dataset.geometry_type is not None

    row = await get_feature_by_id(
        db, dataset.table_name, gid, has_geometry=has_geometry
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature not found",
        )

    feature = GeoJSONFeature(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
    )

    return JSONResponse(
        content=feature.model_dump(mode="json"),
        media_type="application/geo+json",
    )


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------


@features_router.post(
    "/{dataset_id}/features/",
    response_class=JSONResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "content": {
                "application/geo+json": {"schema": GeoJSONFeature.model_json_schema()}
            }
        },
        **ERROR_RESPONSES_WRITE,
    },
)
async def create_feature(
    dataset_id: uuid.UUID,
    body: FeatureCreate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Insert a new GeoJSON feature into a dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        row = await insert_feature(
            db,
            dataset.table_name,
            body.geometry.model_dump(),
            body.properties,
            dataset.column_info or [],
            dataset.geometry_type,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    await refresh_dataset_metadata(db, dataset)
    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="feature.insert",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "gid": row["gid"],
                "property_fields": sorted((row.get("properties") or {}).keys()),
            },
        ),
    )
    await db.commit()

    # Invalidate cached tiles so the new feature appears immediately
    tile_cache = get_tile_cache()
    if tile_cache is not None:
        await tile_cache.invalidate_table(dataset.table_name)

    logger.info(
        "feature.insert",
        dataset_id=str(dataset_id),
        gid=row["gid"],
        user_id=str(user.id),
    )

    feature = GeoJSONFeature(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
    )
    return JSONResponse(
        content=feature.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
        media_type="application/geo+json",
    )


@features_router.put(
    "/{dataset_id}/features/{gid}",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {"schema": GeoJSONFeature.model_json_schema()}
            }
        },
        **ERROR_RESPONSES_WRITE,
    },
)
async def replace_single_feature(
    dataset_id: uuid.UUID,
    gid: int,
    body: FeatureReplace,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Full replacement of a feature (PUT semantics)."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        row = await replace_feature(
            db,
            dataset.table_name,
            gid,
            body.geometry.model_dump(),
            body.properties,
            dataset.column_info or [],
            dataset.geometry_type,
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    await refresh_dataset_metadata(db, dataset)
    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="feature.replace",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "gid": row["gid"],
                "property_fields": sorted((row.get("properties") or {}).keys()),
            },
        ),
    )
    await db.commit()

    # Invalidate cached tiles so the replaced feature renders correctly
    tile_cache = get_tile_cache()
    if tile_cache is not None:
        await tile_cache.invalidate_table(dataset.table_name)

    feature = GeoJSONFeature(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
    )
    return JSONResponse(
        content=feature.model_dump(mode="json"),
        media_type="application/geo+json",
    )


@features_router.patch(
    "/{dataset_id}/features/{gid}",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {"schema": GeoJSONFeature.model_json_schema()}
            }
        },
        **ERROR_RESPONSES_WRITE,
    },
)
async def patch_single_feature(
    dataset_id: uuid.UUID,
    gid: int,
    body: FeatureUpdate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Partial update of a feature (PATCH semantics)."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        row = await update_feature(
            db,
            dataset.table_name,
            gid,
            body.geometry.model_dump() if body.geometry else None,
            body.properties,
            dataset.column_info or [],
            dataset.geometry_type,
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Only refresh metadata if geometry changed (extent may change)
    if body.geometry is not None:
        await refresh_dataset_metadata(db, dataset)
    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="feature.update",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "gid": row["gid"],
                "geometry_updated": body.geometry is not None,
                "property_fields": sorted((body.properties or {}).keys()),
            },
        ),
    )
    await db.commit()

    # Invalidate cached tiles so the updated feature renders correctly
    tile_cache = get_tile_cache()
    if tile_cache is not None:
        await tile_cache.invalidate_table(dataset.table_name)

    feature = GeoJSONFeature(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
    )
    return JSONResponse(
        content=feature.model_dump(mode="json"),
        media_type="application/geo+json",
    )


@features_router.delete(
    "/{dataset_id}/features/{gid}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERROR_RESPONSES_WRITE,
)
async def delete_single_feature(
    dataset_id: uuid.UUID,
    gid: int,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a feature by gid (hard delete)."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        await delete_feature(db, dataset.table_name, gid)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    await refresh_dataset_metadata(db, dataset)
    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="feature.delete",
            resource_type="dataset",
            resource_id=dataset_id,
            details={"gid": gid},
        ),
    )
    await db.commit()

    # Invalidate cached tiles so the deleted feature disappears immediately
    tile_cache = get_tile_cache()
    if tile_cache is not None:
        await tile_cache.invalidate_table(dataset.table_name)

    logger.info(
        "feature.delete",
        dataset_id=str(dataset_id),
        gid=gid,
        user_id=str(user.id),
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
