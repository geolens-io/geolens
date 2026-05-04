"""Shared maps service contracts and query helpers."""

import uuid
from datetime import datetime
from typing import NamedTuple

import structlog
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer

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


async def get_dataset_meta(
    session: AsyncSession,
    dataset_id: uuid.UUID,
) -> DatasetMeta | None:
    """Fetch dataset metadata for building a layer response. Single query."""
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
        )
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    row = result.one_or_none()
    return DatasetMeta(*row) if row else None


def generate_default_style(geometry_type: str | None) -> dict[str, dict]:
    """Generate MapLibre-native default paint/layout for a geometry type.

    Returns {"paint": {...}, "layout": {...}} ready to store in map_layers.
    """
    gt = (geometry_type or "").upper()
    if not gt:
        logger.warning(
            "generate_default_style called with null geometry_type; defaulting to fill"
        )

    if "POINT" in gt:
        return {
            "paint": {
                "circle-radius": 5,
                "circle-color": "#3b82f6",
                "circle-stroke-color": "#1d4ed8",
                "circle-stroke-width": 1,
                "circle-opacity": 1,
            },
            "layout": {},
        }
    elif "LINE" in gt:
        return {
            "paint": {
                "line-color": "#3b82f6",
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
                "fill-color": "#3b82f6",
                "fill-opacity": 0.3,
                # GeoLens-private keys consumed by the frontend layer-adapter;
                # not valid MapLibre paint properties.
                "_outline-color": "#1d4ed8",
                "_outline-width": 1,
            },
            "layout": {},
        }


async def _fetch_layer_rows_ordered(
    session: AsyncSession, map_id: uuid.UUID
) -> list[LayerRow]:
    """Fetch the joined layer-row tuples for a map, ordered by sort_order.

    Map has no relationship() to MapLayer, so the .order_by(MapLayer.sort_order)
    clause MUST live in the explicit SELECT — there is no relationship-level
    ordering to leverage.
    """
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
        )
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(MapLayer.map_id == map_id)
        .order_by(MapLayer.sort_order)
    )
    result = await session.execute(stmt)
    return [LayerRow(*row) for row in result.all()]


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
