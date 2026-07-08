"""Shared maps service contracts and query helpers."""

import uuid
from datetime import datetime
from typing import NamedTuple

import structlog
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.identity import Identity
from app.modules.auth.models import User
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.style_json import (
    DEFAULT_FILL_COLOR,
    DEFAULT_STROKE_COLOR,
)
from app.platform.extensions import get_catalog_port

logger = structlog.stdlib.get_logger(__name__)


class DatasetMeta(NamedTuple):
    """Metadata returned by get_dataset_meta — one row per dataset."""

    record_type: str | None
    title: str | None
    geometry_type: str | None
    table_name: str | None
    extent: object | None
    column_info: list | None
    feature_count: int | None
    sample_values: dict | None
    is_3d: bool | None
    is_dem: bool | None
    dem_vertical_units: str | None
    band_count: int | None
    tile_version: int | None
    # fix(V-17): dataset visibility/status so the builder can flag layers hidden
    # from a public map's anonymous audience.
    visibility: str | None
    record_status: str | None


class LayerRow(NamedTuple):
    """One joined row from the map-layer SELECT in _fetch_layer_rows_ordered.

    Used by ``get_map_with_layers`` (read path) and ``update_map`` /
    ``duplicate_map`` (save path) to denormalize layer + record + dataset
    metadata into a single response.
    """

    layer: MapLayer
    title: str | None
    geometry_type: str | None
    table_name: str | None
    spatial_extent: object | None
    column_info: list | None
    feature_count: int | None
    sample_values: dict | None
    record_type: str | None
    is_3d: bool | None
    is_dem: bool | None
    dem_vertical_units: str | None
    band_count: int | None
    tile_version: int | None
    visibility: str | None = None  # fix(V-17): dataset visibility for audience-badge
    record_status: str | None = None


def _extract_dem_vertical_units(band_info: object) -> str | None:
    if not isinstance(band_info, list):
        return None
    for band in band_info:
        if not isinstance(band, dict):
            continue
        for key in ("unit", "units", "unit_name"):
            value = band.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


async def get_dataset_meta(
    session: AsyncSession,
    dataset_id: uuid.UUID,
) -> DatasetMeta | None:
    """Fetch dataset metadata for building a layer response. Single query."""
    RasterAsset = get_catalog_port().raster_asset_orm_class()
    result = await session.execute(
        select(
            Record.record_type,
            Record.title,
            Dataset.geometry_type,
            Dataset.table_name,
            Record.spatial_extent,
            Dataset.column_info,
            Dataset.feature_count,
            Dataset.sample_values,
            Dataset.is_3d,
            RasterAsset.is_dem,
            RasterAsset.band_info,
            RasterAsset.band_count,
            Dataset.current_version,
            Record.visibility,
            Record.record_status,
        )
        .join(Record, Dataset.record_id == Record.id)
        .outerjoin(RasterAsset, RasterAsset.dataset_id == Dataset.id)
        .where(Dataset.id == dataset_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return DatasetMeta(
        record_type=row[0],
        title=row[1],
        geometry_type=row[2],
        table_name=row[3],
        extent=row[4],
        column_info=row[5],
        feature_count=row[6],
        sample_values=row[7],
        is_3d=row[8],
        is_dem=bool(row[9]) if row[9] is not None else None,
        dem_vertical_units=_extract_dem_vertical_units(row[10]),
        band_count=row[11],
        tile_version=row[12],
        visibility=row[13],
        record_status=row[14],
    )


def normalize_dem_style_config(
    style_config: dict | None,
    *,
    is_dem: bool | None,
) -> dict | None:
    """Persist canonical DEM render modes so backend exports match the builder UI."""
    if is_dem is not True:
        return style_config
    if not isinstance(style_config, dict):
        return {"render_mode": "hillshade"}

    render_mode = style_config.get("render_mode")
    if render_mode in {"terrain", "hillshade"}:
        return style_config

    normalized = dict(style_config)
    normalized["render_mode"] = "hillshade"
    return normalized


def generate_default_style(geometry_type: str | None) -> dict[str, dict | None]:
    """Generate MapLibre-native default paint/layout for a geometry type.

    Returns paint/layout plus optional builder style_config ready to store in
    map_layers.
    """
    gt = (geometry_type or "").upper()
    if not gt:
        logger.warning(
            "generate_default_style called with null geometry_type; defaulting to fill"
        )

    # builder-audit #338 STYLE-07: use the shared GeoLens-blue palette constants from
    # style_json so storage defaults cannot silently diverge from export defaults.
    if "POINT" in gt:
        return {
            "paint": {
                "circle-radius": 5,
                "circle-color": DEFAULT_FILL_COLOR,
                "circle-stroke-color": DEFAULT_STROKE_COLOR,
                "circle-stroke-width": 1,
                "circle-opacity": 1,
            },
            "layout": {},
        }
    elif "LINE" in gt:
        return {
            "paint": {
                "line-color": DEFAULT_FILL_COLOR,
                "line-width": 2,
                "line-opacity": 1,
            },
            "layout": {
                "line-cap": "round",
                "line-join": "round",
            },
        }
    else:
        # Default to fill (polygon, geometry collection, unknown)
        return {
            "paint": {
                "fill-color": DEFAULT_FILL_COLOR,
                "fill-opacity": 0.3,
            },
            "layout": {},
            "style_config": {
                "builder": {
                    "outline_color": DEFAULT_STROKE_COLOR,
                    "outline_width": 1,
                }
            },
        }


async def _fetch_layer_rows_ordered(
    session: AsyncSession, map_id: uuid.UUID
) -> list[LayerRow]:
    """Fetch the joined layer-row tuples for a map, ordered by sort_order.

    Map has no relationship() to MapLayer, so the .order_by(MapLayer.sort_order)
    clause MUST live in the explicit SELECT — there is no relationship-level
    ordering to leverage.
    """
    RasterAsset = get_catalog_port().raster_asset_orm_class()
    stmt = (
        select(
            MapLayer,
            Record.title,
            Dataset.geometry_type,
            Dataset.table_name,
            Record.spatial_extent,
            Dataset.column_info,
            Dataset.feature_count,
            Dataset.sample_values,
            Record.record_type,
            Dataset.is_3d,
            RasterAsset.is_dem,
            RasterAsset.band_info,
            RasterAsset.band_count,
            Dataset.current_version,
            Record.visibility,
            Record.record_status,
        )
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .outerjoin(RasterAsset, RasterAsset.dataset_id == Dataset.id)
        .where(MapLayer.map_id == map_id)
        # fix(BA-21): concurrent adds can collide on sort_order (non-atomic RMW);
        # break ties by id so stacking order is at least deterministic.
        .order_by(MapLayer.sort_order, MapLayer.id)
    )
    result = await session.execute(stmt)
    return [
        LayerRow(
            layer=row[0],
            title=row[1],
            geometry_type=row[2],
            table_name=row[3],
            spatial_extent=row[4],
            column_info=row[5],
            feature_count=row[6],
            sample_values=row[7],
            record_type=row[8],
            is_3d=row[9],
            is_dem=bool(row[10]) if row[10] is not None else None,
            dem_vertical_units=_extract_dem_vertical_units(row[11]),
            band_count=row[12],
            tile_version=row[13],
            visibility=row[14],
            record_status=row[15],
        )
        for row in result.all()
    ]


async def filter_layer_rows_by_dataset_visibility(
    session: AsyncSession,
    layer_rows: list[LayerRow],
    user: Identity | None,
) -> list[LayerRow]:
    """Drop layer rows whose backing dataset is not visible to ``user``.

    SEC-A: ``GET /maps/{id}`` and ``/style.json`` gate only the MAP, so a public
    map referencing a private dataset would otherwise leak that dataset's metadata
    (and, via the signed tile URL in style.json, its actual tiles) to anonymous
    callers. This mirrors ``get_shared_map`` (service_public.py), which filters each
    layer's dataset through ``apply_visibility_filter``. Layer order is preserved.

    Do NOT swap this for ``bulk_check_dataset_access``: that dereferences ``user.id``
    (crashes on anonymous ``user is None``) and lacks the published-status nuance.
    """
    if not layer_rows:
        return layer_rows
    user_roles = await get_user_roles(session, user) if user is not None else set()
    layer_dataset_ids = {row.layer.dataset_id for row in layer_rows}
    stmt = (
        select(Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id.in_(layer_dataset_ids))
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    visible_ids = set((await session.execute(stmt)).scalars().all())
    return [row for row in layer_rows if row.layer.dataset_id in visible_ids]


async def _resolve_save_response_metadata(
    session: AsyncSession, map_obj: Map
) -> tuple[str | None, str | None, datetime | None]:
    """Resolve forked_from_name + owner_username + DB-side updated_at via one LEFT JOIN.

    One atomic query (matches the pre-PERF-6 get_map_with_layers semantics
    under READ COMMITTED). Used by update_map / duplicate_map where map_obj
    is already in-session — get_map_with_layers issues its own combined
    query inline to keep the read path at 2 queries total.

    ``Map.updated_at`` is included so callers don't need a separate
    ``session.refresh(map_obj)`` round-trip to read the DB-side
    ``onupdate=func.now()`` value (PERF: saves one round-trip per save).
    """
    ForkedMap = aliased(Map)
    stmt = (
        select(ForkedMap.name, User.username, Map.updated_at)
        .select_from(Map)
        .outerjoin(ForkedMap, Map.forked_from == ForkedMap.id)
        .outerjoin(User, Map.created_by == User.id)
        .where(Map.id == map_obj.id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None, None, None
    return row[0], row[1], row[2]


def _apply_map_visibility_filter(
    stmt: Select,
    user_id: uuid.UUID | None,
    is_admin: bool,
) -> Select:
    """Apply RBAC visibility filter to a Map query.

    - Admins see everything (no filter).
    - Authenticated users see: their own private maps + all internal + all public.
    - Anonymous users see public only.
    """
    if is_admin:
        return stmt
    if user_id is not None:
        return stmt.where(
            or_(
                Map.created_by == user_id,
                Map.visibility.in_(["internal", "public"]),
            )
        )
    return stmt.where(Map.visibility == "public")


def _infer_layer_type(record_type: str | None) -> str:
    """Infer layer_type from record_type."""
    return (
        "raster_geolens"
        if record_type in ("raster_dataset", "vrt_dataset")
        else "vector_geolens"
    )
