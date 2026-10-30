"""Feature-serving endpoints: paginated GeoJSON from PostGIS data tables."""

import uuid
from contextlib import asynccontextmanager
from typing import NamedTuple
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
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.db.sqlstate import (
    BAD_QUERY_INPUT,
    TABLE_ABSENT,
    is_caller_type_fault,
    is_lock_conflict,
    is_operational,
    sqlstate,
)
from app.core.identity import Identity
from app.platform.request_credential import api_key_audit_details
from app.platform.catalog_locks import (
    CatalogLockConflict,
    bump_tile_cache_version_on,
    lock_request_key,
    record_live_data_write,
)
from app.core.record_types import capabilities
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_optional_user_fail_open,
    reject_unresolvable_credentials,
    require_permission,
)
from app.modules.catalog.authorization import (
    check_dataset_access,
    check_dataset_access_or_anonymous,
    check_dataset_write_access,
    may_read_dataset,
    readable_columns,
    require_dataset_editing_enabled,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.embed_tokens.service import validate_embed_token_access
from app.core.dependencies import get_db
from app.modules.catalog.features.idempotency import (
    IDEMPOTENCY_ATTEMPT_HEADER,
    IDEMPOTENCY_ATTEMPT_MAX,
    IDEMPOTENCY_KEY_HEADER,
    IDEMPOTENCY_KEY_MAX_LENGTH,
    IDEMPOTENCY_KEY_PATTERN,
    CreatedRow,
    KeyedFeature,
    claim_create_key,
    credential_key,
    current_row_xmin,
    current_table_oid,
    find_live_key,
    held_table_oid,
    is_append_only,
    record_attempt,
)
from app.modules.catalog.features.schemas import (
    TILE_CACHE_VERSION_DESCRIPTION,
    TILE_CACHE_VERSION_HEADER,
    FeatureBatchDelete,
    FeatureBatchDeleted,
    FeatureCollectionCreate,
    FeatureCreate,
    FeatureCreateBody,
    FeatureReplace,
    FeatureUpdate,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONFeatureCollectionDryRun,
    GeoJSONFeatureCollectionWrite,
    GeoJSONFeatureDryRun,
    GeoJSONFeatureRead,
    GeoJSONFeatureWrite,
    inline_json_schema,
)
from app.modules.catalog.features.service import (
    Bounds,
    FeatureBatchError,
    FeatureNotFoundError,
    MissingFeaturesError,
    UnwritablePropertyError,
    delete_feature,
    delete_features,
    dry_run_blocker,
    effective_geometry_type,
    geojson_bounds,
    get_feature_by_id,
    get_features,
    get_features_geojson_z,
    insert_feature,
    insert_features,
    lock_catalog_rows_for_write,
    number_matched_headers,
    parse_bbox,
    refresh_dataset_metadata,
    replace_feature,
    update_feature,
)
from app.standards.ogc.errors import (
    ERROR_RESPONSES_AUTH,
    ERROR_RESPONSES_WRITE,
    PAYLOAD_TOO_LARGE_RESPONSE,
)
from app.standards.ogc.utils import build_url
from app.core.public_urls import get_public_api_url

logger = structlog.get_logger()

features_router = APIRouter(prefix="/datasets", tags=["Features"])


def _require_feature_table(dataset) -> None:
    """Reject feature writes to datasets with no writable feature geometry.

    Mirrors the read handlers' 404 on raster/VRT datasets (else 500 on a
    missing `data.<table>`). Also rejects tabular datasets
    (`geometry_type is None`), whose table has no `geom`/`geom_4326` column.
    """
    if not capabilities(dataset.record.record_type).feature_table:
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


_TABLE_UNAVAILABLE = "Dataset table is temporarily unavailable."


def _feature_write_db_error(exc: DBAPIError) -> HTTPException:
    """Classify a DB error raised by a feature write.

    Feature values bind raw, so classify by SQLSTATE instead of
    an unhandled 500 (400 caller fault, missing table 503, unrecognized
    state a real 500). A lock conflict raises
    ``CatalogLockConflict``, mapped in ``app/api/main.py``.
    """
    if is_lock_conflict(exc):
        raise CatalogLockConflict(
            "Another operation is updating this dataset's catalog entry."
        ) from exc
    if is_operational(exc):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        )
    state = sqlstate(exc)
    if state in TABLE_ABSENT:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_TABLE_UNAVAILABLE,
        )
    if state in BAD_QUERY_INPUT or (state or "")[:2] in ("22", "23"):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feature could not be written: a value is incompatible with a "
            "column's type or constraints.",
        )
    logger.error("feature.write unexpected DB error", sqlstate=state, exc_info=exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Feature write failed unexpectedly.",
    )


async def _guard(db: AsyncSession, step) -> None:
    """Run one post-write catalog step with its database errors classified.

    Narrower than the handlers' own guards on purpose: only `DBAPIError` is
    caught, so a `ValueError` still surfaces as itself.
    """
    try:
        await step
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)


async def _refresh_metadata_guarded(db: AsyncSession, dataset, **kwargs) -> None:
    """Recompute feature_count and extent, holding the catalog rows.

    Takes the pair itself, so a handler that reaches this needs nothing else.
    """
    await _guard(db, refresh_dataset_metadata(db, dataset, **kwargs))


async def _lock_catalog_rows_guarded(db: AsyncSession, dataset) -> None:
    """Take the (datasets, records) pair for a write that skips the refresh.

    Every handler stamps `record.updated_by` and rolls `tile_cache_version`,
    which dirties both rows even when nothing is recomputed. Same helper as the
    refresh path, so the two cannot drift.
    """
    await _guard(db, lock_catalog_rows_for_write(db, dataset))


def _written_feature(
    row: dict, tile_version: int | None, table_oid: int | None, masked: bool
) -> GeoJSONFeatureWrite:
    """A written feature as a create answers with it.

    ``masked`` is for an append-only key, which may not read features: the
    stored row can hold defaults and values the caller never sent, and the
    tile version and table id move with other writers, so only the id is kept.
    """
    if masked:
        return GeoJSONFeatureWrite(id=row["gid"], geometry=None, properties={})
    return GeoJSONFeatureWrite(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
        table_id=str(table_oid),
        tile_cache_version=tile_version,
    )


def _created_feature_response(
    row: dict, tile_version: int | None, table_oid: int | None, masked: bool
) -> JSONResponse:
    feature = _written_feature(row, tile_version, table_oid, masked)
    return JSONResponse(
        content=feature.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
        media_type="application/geo+json",
    )


_DRY_RUN_REFUSALS = {
    "missing_table": (status.HTTP_503_SERVICE_UNAVAILABLE, _TABLE_UNAVAILABLE),
    "not_a_table": (
        status.HTTP_409_CONFLICT,
        "A dry run is only available for a dataset stored in an ordinary table.",
    ),
    "insert_side_effects": (
        status.HTTP_409_CONFLICT,
        "A dry run is not available for this dataset: its table has an INSERT "
        "trigger or rule, whose effects a dry run cannot undo.",
    ),
    "user_code": (
        status.HTTP_409_CONFLICT,
        "A dry run is only available for a table without check constraints, "
        "foreign keys, row security, partitions, expression or partial indexes, "
        "generated columns, custom access methods, domain, enum, composite or "
        "other user-defined column types, user-defined JSON casts, or index "
        "operator classes with volatile functions, since a dry run cannot undo "
        "their effects.",
    ),
}


@asynccontextmanager
async def _insert_scope(db: AsyncSession, dry_run: bool, table_name: str):
    """Run a create's inserts as they are, or in a savepoint rolled back on exit.

    A dry run keeps the real inserts so the database's own casts and
    constraints refuse a bad value as they would for a real create. Deferred
    constraints are checked before the rollback, since a real create meets
    them at commit. The rest of the request's transaction is left as it was.
    A table whose insert could reach past the transaction is refused with 409
    first; see ``dry_run_blocker``.
    """
    if not dry_run:
        yield
        return
    blocker = await dry_run_blocker(db, table_name)
    if blocker is not None:
        code, detail = _DRY_RUN_REFUSALS[blocker]
        raise HTTPException(status_code=code, detail=detail)
    async with db.begin_nested() as savepoint:
        yield
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await savepoint.rollback()


def _dry_run_response(rows: list[dict], collection: bool) -> JSONResponse:
    features = [
        GeoJSONFeatureDryRun(geometry=row["geometry"], properties=row["properties"])
        for row in rows
    ]
    content = (
        GeoJSONFeatureCollectionDryRun(features=features) if collection else features[0]
    )
    return JSONResponse(
        content=content.model_dump(mode="json"),
        status_code=status.HTTP_200_OK,
        media_type="application/geo+json",
    )


def _batch_feature_refused(error: FeatureBatchError) -> HTTPException:
    """The refusal a single create would get, naming the feature that failed."""
    cause = error.cause
    if isinstance(cause, DBAPIError):
        refusal = _feature_write_db_error(cause)
    elif isinstance(cause, UnwritablePropertyError):
        refusal = HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(cause)
        )
    else:
        refusal = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(cause)
        )
    if refusal.status_code >= 500:
        return refusal
    return HTTPException(
        status_code=refusal.status_code,
        detail={
            "code": "feature_refused",
            "index": error.index,
            "message": refusal.detail,
        },
    )


async def _create_features(
    db: AsyncSession,
    dataset,
    user: Identity,
    dataset_id: uuid.UUID,
    body: FeatureCollectionCreate,
    dry_run: bool,
) -> JSONResponse:
    """Insert every feature of a FeatureCollection in this transaction, or none."""
    geometries = [feature.geometry.model_dump() for feature in body.features]
    try:
        async with _insert_scope(db, dry_run, dataset.table_name):
            rows = await insert_features(
                db,
                dataset.table_name,
                [
                    (geometry, feature.properties)
                    for geometry, feature in zip(geometries, body.features)
                ],
                dataset.column_info or [],
                await effective_geometry_type(db, dataset),
                dataset_srid=dataset.srid,
            )
        if dry_run:
            return _dry_run_response(rows, collection=True)
        table_oid = await current_table_oid(db, dataset.table_name)
    except FeatureBatchError as e:
        await db.rollback()
        raise _batch_feature_refused(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

    gids = [row["gid"] for row in rows]
    geometry_types = {feature.geometry.type for feature in body.features}
    await _refresh_metadata_guarded(
        db,
        dataset,
        count_delta=len(gids),
        touched_bounds=[geojson_bounds(geometry) for geometry in geometries],
        added_geometry_type=(
            next(iter(geometry_types)) if len(geometry_types) == 1 else None
        ),
    )
    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="feature.bulk_insert",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "gids": gids,
                "count": len(gids),
                "property_fields": sorted(
                    {key for f in body.features for key in (f.properties or {})}
                ),
                **api_key_audit_details(db),
            },
        ),
    )
    tile_version = await record_live_data_write(db, dataset)
    await db.commit()

    logger.info(
        "feature.bulk_insert",
        dataset_id=str(dataset_id),
        tile_cache_version=tile_version,
        count=len(gids),
        user_id=str(user.id),
    )
    masked = is_append_only(db)
    written = GeoJSONFeatureCollectionWrite(
        features=[
            _written_feature(row, tile_version, table_oid, masked) for row in rows
        ],
        table_id=None if masked else str(table_oid),
        tile_cache_version=None if masked else tile_version,
    )
    return JSONResponse(
        content=written.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
        media_type="application/geo+json",
    )


def _feature_gone(tile_version: int | None = None) -> HTTPException:
    detail = {
        "code": "feature_gone",
        "message": (
            "The feature created with this Idempotency-Key is gone. "
            "Use a new key to create another."
        ),
    }
    if tile_version is not None:
        detail["tile_cache_version"] = tile_version
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _feature_changed(
    row: dict, tile_version: int | None, table_oid: int
) -> HTTPException:
    """The refusal for a later attempt that would overwrite another writer's edit."""
    feature = GeoJSONFeatureWrite(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
        table_id=str(table_oid),
        tile_cache_version=tile_version,
    )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "feature_changed",
            "message": (
                "Someone else changed this feature after the last attempt was "
                "saved, so this attempt was not applied."
            ),
            "feature": feature.model_dump(mode="json"),
        },
    )


def _dataset_replaced(tile_version: int | None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "dataset_replaced",
            "message": (
                "The dataset's data was replaced after this feature was read, "
                "so nothing was written. Read the feature again."
            ),
            "tile_cache_version": tile_version,
        },
    )


async def _roll_tile_generation(db: AsyncSession, dataset) -> int | None:
    """Commit a new tile cache version for a dataset found with a replaced table.

    An overwrite made outside GeoLens moves no version, so tiles cached from
    the old table would go on being served. Nothing else is written.
    """
    await _lock_catalog_rows_guarded(db, dataset)
    tile_version = await bump_tile_cache_version_on(db, dataset)
    await db.commit()
    return tile_version


async def _hold_table(db: AsyncSession, dataset, table_id: str | None) -> int | None:
    """Hold the dataset's table for this write, refusing a stale ``table_id``."""
    table_oid = await held_table_oid(db, dataset.table_name)
    if table_id is not None and table_id != str(table_oid):
        raise _dataset_replaced(await _roll_tile_generation(db, dataset))
    return table_oid


# The writes type it `str`, not an optional type, for the reason given on the
# create route's headers.
_TABLE_ID_PARAM_DESCRIPTION = (
    "The `table_id` the feature was read with. If the dataset's data has been "
    "replaced since, the request is refused with 409 and code "
    "`dataset_replaced`, and nothing is written."
)


class _Repeat(NamedTuple):
    """The feature a repeated create answers with, and whether it was written."""

    row: dict
    prior_bounds: Bounds | None
    wrote: bool
    key_id: uuid.UUID
    attempt: int
    row_xmin: int | None
    # An append-only key's answer, the feature's id alone.
    masked: bool = False


async def _settle_repeat(
    db: AsyncSession,
    dataset,
    keyed: KeyedFeature,
    attempt: int,
    body: FeatureCreate,
    append_only: bool,
) -> _Repeat:
    """Settle a create whose key already names a feature.

    The feature is read first, so this transaction holds its table, and the
    table's oid is compared after: a swap or overwrite cannot commit between
    the two, and a matching oid means the row is the one the key was written
    for. A higher attempt number than any applied has its body written through
    the update path, which validates it as a create does; an equal or lower one
    gets the feature as stored. A higher attempt number is refused with 409 and
    the stored feature if anyone else has written the feature since the last
    attempt was applied. The feature is written before the catalog rows are
    taken, the order every other feature write uses. For an ``append_only``
    caller, which may neither read nor change features, the answer is the
    feature's id alone and nothing is applied. Its feature being deleted and
    its table being replaced get the same bare 409, and neither rolls the tile
    version: a probe must not show, or move, what other writers did.
    """
    row = await get_feature_by_id(db, dataset.table_name, keyed.gid)
    replaced = keyed.table_oid != await current_table_oid(db, dataset.table_name)
    if append_only:
        if replaced or row is None:
            raise _feature_gone()
        return _Repeat(row, None, False, keyed.id, attempt, None, masked=True)
    if replaced:
        raise _feature_gone(await _roll_tile_generation(db, dataset))
    if row is None:
        raise _feature_gone()
    if attempt <= keyed.attempt:
        return _Repeat(row, None, False, keyed.id, attempt, None)
    # The row is taken before the version is read, so a writer still in flight
    # is waited out and its version is what gets compared.
    current = await current_row_xmin(db, dataset.table_name, keyed.gid, lock=True)
    if current is None:
        raise _feature_gone()
    if current != keyed.row_xmin:
        await db.refresh(dataset, ["tile_cache_version"])
        stored = await get_feature_by_id(db, dataset.table_name, keyed.gid)
        raise _feature_changed(
            stored or row, dataset.tile_cache_version, keyed.table_oid
        )
    try:
        written = await update_feature(
            db,
            dataset.table_name,
            keyed.gid,
            body.geometry.model_dump(),
            body.properties,
            dataset.column_info or [],
            await effective_geometry_type(db, dataset),
            dataset_srid=dataset.srid,
        )
    except FeatureNotFoundError as exc:
        raise _feature_gone() from exc
    return _Repeat(
        written.feature,
        written.prior_bounds,
        True,
        keyed.id,
        attempt,
        await current_row_xmin(db, dataset.table_name, keyed.gid),
    )


async def _finish_repeat(
    db: AsyncSession,
    dataset,
    user: Identity,
    dataset_id: uuid.UUID,
    body: FeatureCreate,
    repeat: _Repeat,
    table_oid: int,
) -> JSONResponse:
    """Commit a settled repeat and answer with the feature as stored."""
    if repeat.wrote:
        await _refresh_metadata_guarded(
            db,
            dataset,
            count_delta=0,
            touched_bounds=[
                repeat.prior_bounds,
                geojson_bounds(body.geometry.model_dump()),
            ],
        )
        await record_attempt(db, repeat.key_id, repeat.attempt, repeat.row_xmin)
        dataset.record.updated_by = user.id
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="feature.update",
                resource_type="dataset",
                resource_id=dataset_id,
                details={
                    "gid": repeat.row["gid"],
                    "geometry_updated": True,
                    "property_fields": sorted((body.properties or {}).keys()),
                    **api_key_audit_details(db),
                },
            ),
        )
        tile_version = await record_live_data_write(db, dataset)
    else:
        await db.refresh(dataset, ["tile_cache_version"])
        tile_version = dataset.tile_cache_version
    # Ends the transaction, so the locks go before the answer does.
    await db.commit()

    return _created_feature_response(repeat.row, tile_version, table_oid, repeat.masked)


# A typed object, not a binary body: the generated Python client parses any
# `+json` media type with response.json(), which would hand bytes() a dict.
_FEATURES_GEOJSON_Z_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["FeatureCollection"]},
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["Feature"]},
                    "id": {"type": "integer"},
                    "geometry": {
                        "anyOf": [
                            {"type": "object", "additionalProperties": True},
                            {"type": "null"},
                        ]
                    },
                    "properties": {"type": "object", "additionalProperties": True},
                },
                "required": ["type", "id", "geometry", "properties"],
            },
        },
        "truncated": {"type": "boolean"},
        "total_count": {"type": "integer"},
    },
    "required": ["type", "features", "truncated", "total_count"],
}


@features_router.get(
    "/{dataset_id}/features.geojson",
    response_class=JSONResponse,
    responses={
        200: {
            "description": "A GeoJSON FeatureCollection with Z coordinates preserved.",
            "content": {"application/geo+json": {"schema": _FEATURES_GEOJSON_Z_SCHEMA}},
        },
        **ERROR_RESPONSES_AUTH,
    },
)
async def get_features_geojson_z_endpoint(
    dataset_id: uuid.UUID,
    request: Request,
    user: Identity | None = Depends(get_optional_user_fail_open),
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

    ``X-Embed-Token`` authorizes private datasets in the token's scope through
    the same capability check used for tile requests. A request only the embed
    token authorizes gets only the properties in the dataset's tile column
    allowlist, when it has one.

    Anonymous callers can read public, published datasets. Private or
    restricted datasets return 404 unless user or embed credentials authorize
    access.

    Supplied credentials that are expired or revoked receive 401 so clients can
    refresh them. Requests without credentials use the anonymous access path.
    """
    # Checked before the dataset lookup so the capability rule covers every
    # later exit; the token validates against the path's dataset_id. This
    # handler defers the dead-credential 401 until the body runs, so
    # `reject_unresolvable_credentials` below re-applies it when the embed
    # token did not authorize the request.
    embed_ok = bool(embed_token) and await validate_embed_token_access(
        embed_token,  # type: ignore[arg-type]  # bool() guard above
        dataset_id,
        db,
        request,
    )
    if not embed_ok:
        # No capability authorized this request, so a supplied credential
        # that failed to resolve gets 401 rather than the anonymous 404.
        reject_unresolvable_credentials(request, user)

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    if not embed_ok:
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
    embed_only = embed_ok and not await may_read_dataset(db, dataset, dataset_id, user)

    # Raster/VRT datasets have no feature table: a query would raise
    # UndefinedTableError -> 500 and hold a DB connection.
    if not capabilities(dataset.record.record_type).feature_table:
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
            db,
            dataset.table_name,
            cap=5000,
            cached_feature_count=dataset.feature_count,
            property_columns=readable_columns(dataset, embed_authorized=embed_only),
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
            "Legacy offset-based pagination. The companion limit is capped "
            "at 200 per page, and a high offset is costly to serve."
        ),
    ),
    bbox: str | None = Query(None, description="Bounding box: minx,miny,maxx,maxy"),
    include_geometry: bool = Query(True, description="Include geometry in response"),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get paginated GeoJSON features for a dataset.

    Offset pagination can skip or duplicate rows during concurrent writes,
    though feature ids remain stable because rows are ordered by the primary
    key. Clients that need stable
    cursoring should use the OGC API Features endpoint, which supports keyset
    pagination via ``after_gid``.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access(db, dataset, dataset_id, user)

    # Raster/VRT datasets have no feature table. The ProgrammingError->503
    # catch below stays a backstop for missing tables on other datasets.
    if not capabilities(dataset.record.record_type).feature_table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Dataset '{dataset_id}' is a raster collection and has no "
                "feature items; use the tile/coverage endpoints instead."
            ),
        )

    parsed_bbox: list[float] | None = None
    if bbox is not None:
        try:
            parsed_bbox = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )

    reserved_params = {"limit", "offset", "bbox", "include_geometry", "api_key"}
    column_names = {col["name"] for col in (dataset.column_info or [])}
    property_filters: dict[str, str] = {}
    for key, value in request.query_params.items():
        if key not in reserved_params and key in column_names:
            property_filters[key] = value

    has_geometry = dataset.geometry_type is not None

    try:
        page = await get_features(
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
    except ValueError as e:
        # An unparseable property-filter value is rejected before the query.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except DBAPIError as exc:
        # A type-shaped sqlstate with a property filter active is the filter
        # value, not an outage, and a retryable 503 would loop the client.
        # Catches DBAPIError because asyncpg reports a value it can't encode
        # as a bare DBAPIError with SQLSTATE 22000, neither Programming nor
        # OperationalError. An unrecognized state stays a 500.
        if property_filters and is_caller_type_fault(exc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Property filter is not evaluable against this dataset's "
                    "column types"
                ),
            )
        if isinstance(exc, (ProgrammingError, OperationalError)):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dataset table is unavailable",
            )
        raise

    features = [
        GeoJSONFeature(
            id=row["gid"],
            geometry=row["geometry"],
            properties=row["properties"],
        )
        for row in page.rows
    ]

    base_path = f"/datasets/{dataset_id}/features/"
    public_api_url = await get_public_api_url(db, request=request)

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

    # `next` follows the over-fetched row, not the count —
    # numberMatched may be the planner's estimate, and an estimate at or
    # below `offset + limit` would otherwise drop the link on a full page.
    if page.has_more:
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
        numberMatched=page.total,
        numberReturned=len(features),
        features=features,
        links=links,
    )

    return JSONResponse(
        content=response.model_dump(mode="json"),
        media_type="application/geo+json",
        headers=number_matched_headers(page.total_is_estimate),
    )


@features_router.get(
    "/{dataset_id}/features/{gid}",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": inline_json_schema(GeoJSONFeatureRead)
                }
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
    """Get a single GeoJSON feature by gid.

    `table_id` identifies the data table the feature was read from. Send it
    with a later PUT, PATCH or DELETE of the feature so that write is refused
    if the dataset's data has been replaced in between.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access(db, dataset, dataset_id, user)

    # Raster/VRT datasets have no feature table: the lookup would raise
    # UndefinedTableError -> an unhandled 500 any authenticated user could hit.
    if not capabilities(dataset.record.record_type).feature_table:
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

    feature = GeoJSONFeatureRead(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
        # Read after the row, which holds the table until this transaction ends.
        table_id=str(await current_table_oid(db, dataset.table_name)),
    )

    return JSONResponse(
        content=feature.model_dump(mode="json"),
        media_type="application/geo+json",
    )


@features_router.post(
    "/{dataset_id}/features/",
    response_class=JSONResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "content": {
                "application/geo+json": {
                    "schema": {
                        "oneOf": [
                            inline_json_schema(GeoJSONFeatureWrite),
                            inline_json_schema(GeoJSONFeatureCollectionWrite),
                        ]
                    }
                },
            }
        },
        **ERROR_RESPONSES_WRITE,
    },
)
async def create_feature(
    dataset_id: uuid.UUID,
    body: FeatureCreateBody,
    # Annotated `str` and `int`, not optional types: a nullable optional header
    # becomes a generated-client parameter that accepts None and then sends it.
    idempotency_key: str = Header(
        default=None,
        alias=IDEMPOTENCY_KEY_HEADER,
        min_length=1,
        max_length=IDEMPOTENCY_KEY_MAX_LENGTH,
        pattern=IDEMPOTENCY_KEY_PATTERN,
        description=(
            "Optional key that makes a retried create safe. Any visible ASCII "
            "character (`!` to `~`, no spaces), 1 to 128 characters. The key "
            "is compared exactly as sent, so a quoted key and the same key "
            "unquoted are different keys. For example "
            "`device-42:2026-10-17T16:09:33.123000+00:00`."
        ),
    ),
    idempotency_attempt: int = Header(
        default=None,
        alias=IDEMPOTENCY_ATTEMPT_HEADER,
        ge=1,
        le=IDEMPOTENCY_ATTEMPT_MAX,
        description=(
            "Attempt number sent with `Idempotency-Key`, counting up by one "
            "each time the body is sent again. Counts as 1 when omitted."
        ),
    ),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Insert a new GeoJSON feature into a dataset.

    Send the same `Idempotency-Key` on every attempt to create one feature, and
    `Idempotency-Attempt` numbering the attempts 1, 2, 3 and so on. A repeat
    from the same user on the same dataset never inserts a second feature. It
    answers with the feature as stored, with the same 201 status and body
    shape. If its attempt number is higher than any applied so far, it first
    applies its geometry and the properties it names to that feature, with the
    validation a create gets, unless anyone else has written the feature since
    the last attempt was applied: then it is refused with 409, the stored
    feature in `detail.feature`, and nothing is overwritten. If it is equal or
    lower, the stored feature comes back unchanged, so a request that arrives
    late cannot undo a later one. Two requests with one key never both insert. A key is honored for 24 hours. If
    the feature it created has been deleted since, or the dataset's data has
    been replaced by a reupload or an overwrite, the repeat is refused with 409
    rather than creating another. Without the key every request inserts, and
    an attempt number sent without one is ignored.

    Through an append-only dataset key, every created feature, single or in a
    FeatureCollection, is answered with its `id`, a null `geometry`, empty
    `properties`, and null `table_id` and `tile_cache_version`, since the
    stored row can hold values the key didn't send and the others move with
    other writers. A repeat through one matches only that key's own creates,
    applies nothing and answers the same way. If the feature was deleted or
    the dataset's data replaced, the repeat gets 409 `feature_gone` with no
    `tile_cache_version`.

    A GeoJSON FeatureCollection body inserts up to 1,000 features in one
    transaction: all of them or none. A feature the schema refuses is named
    by its position under `features` in the 422. One refused while writing
    gets the status a single create would, with `detail.code`
    `feature_refused`, `detail.index` (counting from 0) and
    `detail.message`. The 201 answer is a FeatureCollection of the stored
    features in request order, each as a single create returns it, with
    `table_id` and `tile_cache_version` also on the collection. It has no
    `Location` header since there is no single new resource.
    `Idempotency-Key` is refused with 422 for a FeatureCollection.
    """
    return await _create(
        db, dataset_id, body, user, idempotency_key, idempotency_attempt, False
    )


@features_router.post(
    "/{dataset_id}/features/dry-run/",
    response_class=JSONResponse,
    responses={
        200: {
            "description": (
                "The feature or features as they would be stored. Nothing was written."
            ),
            "content": {
                "application/geo+json": {
                    "schema": {
                        "oneOf": [
                            inline_json_schema(GeoJSONFeatureDryRun),
                            inline_json_schema(GeoJSONFeatureCollectionDryRun),
                        ]
                    }
                },
            },
        },
        **ERROR_RESPONSES_WRITE,
        413: PAYLOAD_TOO_LARGE_RESPONSE,
    },
)
async def dry_run_create_feature(
    dataset_id: uuid.UUID,
    body: FeatureCreateBody,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Check a feature create without writing it.

    Takes the body `POST /datasets/{dataset_id}/features/` takes and runs
    every check that create runs, the database's own casts and constraints
    included, so a body it would refuse is refused here with the same status
    and body. A deferred constraint is checked here too: a create that breaks
    one fails at commit with a 500, and this answers 400. Nothing is written.
    A body that passes gets 200 with the feature as it would be stored, or a
    FeatureCollection of them in request order, with no `id`, `table_id` or
    `tile_cache_version`.

    A dataset whose table has a shape that lets an insert run code with
    effects outside the transaction, such as a trigger, a CHECK constraint or
    a user-defined column type, is refused with 409, and the detail names
    those shapes. The insert still runs column defaults, type input functions
    and index support functions, volatile defaults included, so a dry run can
    consume sequence values and stored ids can have gaps.
    """
    return await _create(db, dataset_id, body, user, None, None, True)


async def _create(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    body: FeatureCreateBody,
    user: Identity,
    idempotency_key: str | None,
    idempotency_attempt: int | None,
    dry_run: bool,
) -> JSONResponse:
    """A feature create, or for a dry run its checks and inserts rolled back."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db, dataset_id)
    _require_feature_table(dataset)

    if isinstance(body, FeatureCollectionCreate):
        if idempotency_key is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Idempotency-Key is not supported with a FeatureCollection.",
            )
        return await _create_features(db, dataset, user, dataset_id, body, dry_run)

    keyed = None
    try:
        if idempotency_key is not None:
            idempotency_key = credential_key(db, idempotency_key)
            # Requests on one key run one at a time. The key's lock comes
            # before the feature is touched, so waiting on it holds nothing a
            # PATCH, a replacement or a delete could be waiting for.
            await lock_request_key(
                db, scope=f"feature-create:{dataset_id}:{user.id}:{idempotency_key}"
            )
            keyed = await find_live_key(db, dataset_id, user.id, idempotency_key)
        if keyed is not None:
            repeat = await _settle_repeat(
                db, dataset, keyed, idempotency_attempt or 1, body, is_append_only(db)
            )
        else:
            async with _insert_scope(db, dry_run, dataset.table_name):
                row = await insert_feature(
                    db,
                    dataset.table_name,
                    body.geometry.model_dump(),
                    body.properties,
                    dataset.column_info or [],
                    # Generic for created datasets — see effective_geometry_type
                    await effective_geometry_type(db, dataset),
                    dataset_srid=dataset.srid,
                )
            if dry_run:
                return _dry_run_response([row], collection=False)
            table_oid = await current_table_oid(db, dataset.table_name)
            if idempotency_key is not None:
                # The catalog rows go before the key row: its foreign key
                # takes a shared lock on the dataset that the metadata
                # refresh's exclusive one would wait behind.
                await _lock_catalog_rows_guarded(db, dataset)
                if not await claim_create_key(
                    db,
                    dataset_id,
                    user.id,
                    idempotency_key,
                    CreatedRow(
                        row["gid"],
                        table_oid,
                        await current_row_xmin(db, dataset.table_name, row["gid"]),
                    ),
                    idempotency_attempt or 1,
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Another request is using this Idempotency-Key. Retry.",
                    )
    except UnwritablePropertyError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

    if keyed is not None:
        return await _finish_repeat(
            db, dataset, user, dataset_id, body, repeat, keyed.table_oid
        )

    # One row added, at a known envelope. No table scan when that
    # envelope is already inside the stored extent.
    await _refresh_metadata_guarded(
        db,
        dataset,
        count_delta=1,
        touched_bounds=[geojson_bounds(body.geometry.model_dump())],
        added_geometry_type=body.geometry.type,
    )
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
                **api_key_audit_details(db),
            },
        ),
    )
    tile_version = await record_live_data_write(db, dataset)
    await db.commit()

    logger.info(
        "feature.insert",
        dataset_id=str(dataset_id),
        tile_cache_version=tile_version,
        gid=row["gid"],
        user_id=str(user.id),
    )

    return _created_feature_response(row, tile_version, table_oid, is_append_only(db))


@features_router.put(
    "/{dataset_id}/features/{gid}",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": inline_json_schema(GeoJSONFeatureWrite)
                }
            }
        },
        **ERROR_RESPONSES_WRITE,
    },
)
async def replace_single_feature(
    dataset_id: uuid.UUID,
    gid: int,
    body: FeatureReplace,
    table_id: str = Query(
        default=None,
        min_length=1,
        max_length=20,
        description=_TABLE_ID_PARAM_DESCRIPTION,
    ),
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
    await require_dataset_editing_enabled(db, dataset_id)
    _require_feature_table(dataset)

    try:
        table_oid = await _hold_table(db, dataset, table_id)
        written = await replace_feature(
            db,
            dataset.table_name,
            gid,
            body.geometry.model_dump(),
            body.properties,
            dataset.column_info or [],
            # Generic for created datasets — see effective_geometry_type
            await effective_geometry_type(db, dataset),
            dataset_srid=dataset.srid,
        )
    except UnwritablePropertyError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except FeatureNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

    row = written.feature

    # Row count unchanged; the extent is unchanged too when both
    # the old and new envelope sit strictly inside it. The old envelope comes
    # back from the UPDATE that overwrote it.
    await _refresh_metadata_guarded(
        db,
        dataset,
        count_delta=0,
        touched_bounds=[
            written.prior_bounds,
            geojson_bounds(body.geometry.model_dump()),
        ],
    )
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
                **api_key_audit_details(db),
            },
        ),
    )
    tile_version = await record_live_data_write(db, dataset)
    await db.commit()

    feature = GeoJSONFeatureWrite(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
        table_id=str(table_oid),
        tile_cache_version=tile_version,
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
                "application/geo+json": {
                    "schema": inline_json_schema(GeoJSONFeatureWrite)
                }
            }
        },
        **ERROR_RESPONSES_WRITE,
    },
)
async def patch_single_feature(
    dataset_id: uuid.UUID,
    gid: int,
    body: FeatureUpdate,
    table_id: str = Query(
        default=None,
        min_length=1,
        max_length=20,
        description=_TABLE_ID_PARAM_DESCRIPTION,
    ),
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
    await require_dataset_editing_enabled(db, dataset_id)
    _require_feature_table(dataset)

    try:
        table_oid = await _hold_table(db, dataset, table_id)
        written = await update_feature(
            db,
            dataset.table_name,
            gid,
            body.geometry.model_dump() if body.geometry else None,
            body.properties,
            dataset.column_info or [],
            # Generic for created datasets — see effective_geometry_type
            await effective_geometry_type(db, dataset),
            dataset_srid=dataset.srid,
        )
    except UnwritablePropertyError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except FeatureNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

    row = written.feature

    # Only refresh metadata if geometry changed (extent may change)
    if body.geometry is not None:
        # Same reasoning as replace.
        await _refresh_metadata_guarded(
            db,
            dataset,
            count_delta=0,
            touched_bounds=[
                written.prior_bounds,
                geojson_bounds(body.geometry.model_dump()),
            ],
        )
    else:
        # Nothing to recompute, but the lines below still dirty
        # both rows, so the pair has to be taken in the house order first.
        await _lock_catalog_rows_guarded(db, dataset)
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
                **api_key_audit_details(db),
            },
        ),
    )
    tile_version = await record_live_data_write(db, dataset)
    await db.commit()

    feature = GeoJSONFeatureWrite(
        id=row["gid"],
        geometry=row["geometry"],
        properties=row["properties"],
        table_id=str(table_oid),
        tile_cache_version=tile_version,
    )
    return JSONResponse(
        content=feature.model_dump(mode="json"),
        media_type="application/geo+json",
    )


@features_router.delete(
    "/{dataset_id}/features/{gid}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {
            "description": "Feature deleted.",
            "headers": {
                TILE_CACHE_VERSION_HEADER: {
                    "description": TILE_CACHE_VERSION_DESCRIPTION,
                    "schema": {"type": "integer"},
                },
            },
        },
        **ERROR_RESPONSES_WRITE,
    },
)
async def delete_single_feature(
    dataset_id: uuid.UUID,
    gid: int,
    table_id: str = Query(
        default=None,
        min_length=1,
        max_length=20,
        description=_TABLE_ID_PARAM_DESCRIPTION,
    ),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a feature by gid (hard delete).

    The X-GeoLens-Tile-Cache-Version response header carries the dataset's
    tile_cache_version after the delete committed; a 204 response has no
    body to carry it in, unlike the create, replace and patch endpoints,
    which return it as a field of the written feature.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db, dataset_id)
    _require_feature_table(dataset)

    try:
        await _hold_table(db, dataset, table_id)
        # The DELETE returns the envelope it removed, so the
        # metadata refresh reasons about the version actually deleted.
        prior_bounds = await delete_feature(db, dataset.table_name, gid)
    except FeatureNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

    # One row removed. A row strictly inside the stored extent was
    # not defining any side of it, so the extent cannot shrink.
    await _refresh_metadata_guarded(
        db, dataset, count_delta=-1, touched_bounds=[prior_bounds]
    )
    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="feature.delete",
            resource_type="dataset",
            resource_id=dataset_id,
            details={"gid": gid, **api_key_audit_details(db)},
        ),
    )
    tile_version = await record_live_data_write(db, dataset)
    await db.commit()

    logger.info(
        "feature.delete",
        dataset_id=str(dataset_id),
        tile_cache_version=tile_version,
        gid=gid,
        user_id=str(user.id),
    )

    headers = (
        {TILE_CACHE_VERSION_HEADER: str(tile_version)}
        if tile_version is not None
        else None
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)


@features_router.post(
    "/{dataset_id}/features/delete/",
    response_model=FeatureBatchDeleted,
    responses=ERROR_RESPONSES_WRITE,
)
async def delete_features_batch(
    dataset_id: uuid.UUID,
    body: FeatureBatchDelete,
    table_id: str = Query(
        default=None,
        min_length=1,
        max_length=20,
        description=_TABLE_ID_PARAM_DESCRIPTION,
    ),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> FeatureBatchDeleted:
    """Delete up to 1,000 features by gid in one transaction (hard delete).

    Either every listed feature is deleted or none is. If any gid does not
    exist, the request is refused with 404, `detail.code` `feature_not_found`
    and the missing ids in `detail.gids`. A gid listed twice is deleted once.
    Takes the checks and the `table_id` a single delete takes, and writes one
    `feature.bulk_delete` audit entry.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db, dataset_id)
    _require_feature_table(dataset)

    try:
        await _hold_table(db, dataset, table_id)
        gids, prior_bounds = await delete_features(db, dataset.table_name, body.gids)
    except MissingFeaturesError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "feature_not_found", "message": str(e), "gids": e.gids},
        )
    except DBAPIError as exc:
        await db.rollback()
        raise _feature_write_db_error(exc)

    await _refresh_metadata_guarded(
        db, dataset, count_delta=-len(gids), touched_bounds=prior_bounds
    )
    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="feature.bulk_delete",
            resource_type="dataset",
            resource_id=dataset_id,
            details={"gids": gids, "count": len(gids), **api_key_audit_details(db)},
        ),
    )
    tile_version = await record_live_data_write(db, dataset)
    await db.commit()

    logger.info(
        "feature.bulk_delete",
        dataset_id=str(dataset_id),
        tile_cache_version=tile_version,
        count=len(gids),
        user_id=str(user.id),
    )
    return FeatureBatchDeleted(deleted=len(gids), tile_cache_version=tile_version)
