"""Feature-serving endpoints: paginated GeoJSON from PostGIS data tables."""

import uuid
from urllib.parse import urlencode

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.db.sqlstate import is_operational
from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
    request_carries_credentials,
    require_permission,
)
from app.modules.catalog.authorization import (
    check_dataset_access,
    check_dataset_access_or_anonymous,
    check_dataset_write_access,
    require_dataset_editing_enabled,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.embed_tokens.service import validate_embed_token_access
from app.core.dependencies import get_db
from app.modules.catalog.features.schemas import (
    FeatureCreate,
    FeatureReplace,
    FeatureUpdate,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    inline_json_schema,
)
from app.modules.catalog.features.service import (
    delete_feature,
    effective_geometry_type,
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

# Datasets with no PostGIS data table behind them. Any feature write 42P01s.
_NON_FEATURE_RECORD_TYPES = ("raster_dataset", "vrt_dataset")


def _require_feature_table(dataset) -> None:
    """Reject feature writes to datasets with no writable feature geometry.

    fix(#458 E-08): the read handlers 404 raster/VRT datasets, but the write
    handlers didn't — a write hit a missing `data.<table>` (42P01) and surfaced
    as a 500. Mirror the read side.

    Also reject non-spatial (tabular) datasets, where `geometry_type is None`
    (the same signal the read path uses for `has_geometry`). Their table has no
    `geom`/`geom_4326` column, so an insert/replace 42703s, and a delete — which
    touches no geometry — succeeds but then 500s in `refresh_dataset_metadata`'s
    unconditional `geom_4326` read, *outside* the DBAPIError handler below
    (PR #463 review). Created layers always carry a concrete `geometry_type`
    (generic ones resolve via `effective_geometry_type`), so this never blocks a
    spatial layer.
    """
    if dataset.record.record_type in _NON_FEATURE_RECORD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This dataset has no feature table.",
        )
    if dataset.geometry_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This dataset has no geometry column and does not support "
            "feature editing.",
        )


def _feature_write_db_error(exc: DBAPIError) -> HTTPException:
    """Classify a DB error raised by a feature write.

    fix(#458 E-09/E-26): feature values bind raw, so a type mismatch (22P02), a
    NOT NULL violation (23502), or a write to a table with no such column (42703,
    tabular datasets) used to surface as an unhandled 500. Classify by SQLSTATE:
    a request the table cannot answer is the caller's fault (400); a database
    outage stays a 503.
    """
    if is_operational(exc):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Feature could not be written: a value is incompatible with a "
        "column's type or constraints.",
    )


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
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    embed_token: str | None = Header(
        default=None,
        alias="X-Embed-Token",
        description=(
            "Optional embed token. Datasets in the token's scope are "
            "authorized even without user credentials (embed viewers)."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return up to 5,000 features as RFC 7946 GeoJSON with Z coordinates.

    fix(#394) codex P2: the viewer's bounded-GeoJSON path (small 3D layers,
    eligible cluster layers) already sends ``X-Embed-Token``, and the B-023
    shared-map union now exposes embed-scoped private layers to embeds — so
    this endpoint accepts the token as fallback authorization via the SAME
    ``validate_embed_token_access`` capability check as tile serving.

    fix(#390): the non-embed path uses ``check_dataset_access_or_anonymous``
    so public+published datasets serve to anonymous callers (matching vector
    tiles and the dataset-detail read path); private/restricted datasets still
    404 for anon and follow full RBAC for credentialed callers. This unblocks
    client clustering for anonymous public-map viewers.

    fix(#390) codex P2: a request that *supplied* credentials which failed to
    resolve (expired / revoked JWT -> ``get_optional_user`` is ``None``) still
    gets 401, not the anonymous 404, so the frontend's refresh-on-401 retry
    fires instead of a private layer permanently failing as "not found".
    Truly credentialless requests keep the anonymous public path.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    embed_ok = bool(embed_token) and await validate_embed_token_access(
        embed_token,  # type: ignore[arg-type]  # bool() guard above
        dataset_id,
        db,
        request,
    )
    if not embed_ok:
        if user is None and request_carries_credentials(request):
            # Credentials were supplied but did not resolve (expired/revoked
            # token). Return 401 so the client refreshes and retries rather
            # than the anonymous path's 404. fix(#390) codex P2.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    # fix(#315): raster/VRT datasets have no backing PostGIS feature table, so a feature
    # query would raise UndefinedTableError -> 500 (and hold a DB connection).
    # Return a fast 404 before any feature query is attempted (mirrors OGC contract).
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Dataset '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

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
                    "schema": inline_json_schema(GeoJSONFeatureCollection)
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

    # fix(#315): raster/VRT datasets have no backing PostGIS feature table, so a feature
    # query would raise UndefinedTableError. Return a fast 404 before any query
    # (mirrors OGC contract). The ProgrammingError->503 catch below remains a
    # backstop for genuinely-missing tables on non-raster datasets.
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Dataset '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

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
                "application/geo+json": {"schema": inline_json_schema(GeoJSONFeature)}
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

    # fix(#315): raster/VRT datasets have no backing PostGIS feature table, so
    # get_feature_by_id would raise UndefinedTableError -> unhandled 500 (a DoS
    # reachable by any authenticated user). Return a fast 404 before any query
    # (mirrors OGC contract).
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Dataset '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

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
                "application/geo+json": {"schema": inline_json_schema(GeoJSONFeature)}
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

    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db)
    _require_feature_table(dataset)

    try:
        row = await insert_feature(
            db,
            dataset.table_name,
            body.geometry.model_dump(),
            body.properties,
            dataset.column_info or [],
            # fix(#430 codex r7): generic for created datasets — see effective_geometry_type
            await effective_geometry_type(db, dataset),
            dataset_srid=dataset.srid,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

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
    # fix(#TBD B-038): roll the _v= URL cache-buster in the same transaction —
    # the post-commit Valkey purge cannot reach CDN/browser caches keyed on the URL.
    dataset.bump_tile_cache_version()
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
                "application/geo+json": {"schema": inline_json_schema(GeoJSONFeature)}
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

    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db)
    _require_feature_table(dataset)

    try:
        row = await replace_feature(
            db,
            dataset.table_name,
            gid,
            body.geometry.model_dump(),
            body.properties,
            dataset.column_info or [],
            # fix(#430 codex r7): generic for created datasets — see effective_geometry_type
            await effective_geometry_type(db, dataset),
            dataset_srid=dataset.srid,
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
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

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
    # fix(#TBD B-038): roll the _v= URL cache-buster (see feature.insert above).
    dataset.bump_tile_cache_version()
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
                "application/geo+json": {"schema": inline_json_schema(GeoJSONFeature)}
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

    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db)
    _require_feature_table(dataset)

    try:
        row = await update_feature(
            db,
            dataset.table_name,
            gid,
            body.geometry.model_dump() if body.geometry else None,
            body.properties,
            dataset.column_info or [],
            # fix(#430 codex r7): generic for created datasets — see effective_geometry_type
            await effective_geometry_type(db, dataset),
            dataset_srid=dataset.srid,
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
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

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
    # fix(#TBD B-038): roll the _v= URL cache-buster (see feature.insert above).
    dataset.bump_tile_cache_version()
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

    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db)
    _require_feature_table(dataset)

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
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

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
    # fix(#TBD B-038): roll the _v= URL cache-buster (see feature.insert above).
    dataset.bump_tile_cache_version()
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
