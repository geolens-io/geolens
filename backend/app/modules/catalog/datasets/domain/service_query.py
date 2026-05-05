"""Dataset read-side queries: lookup, list, detail, rows (extracted from service.py — Phase 224)."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.schemas import DatasetResponse

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain._sql_safety import SAFE_TABLE_NAME_RE
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
)
from app.platform.extensions import get_catalog_port

logger = structlog.stdlib.get_logger(__name__)


__all__ = [
    "get_dataset",
    "list_datasets",
    "get_datasets_list",
    "get_dataset_detail",
    "get_dataset_rows",
]


async def get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> Dataset | None:
    """Fetch a single dataset by ID with its record eager-loaded."""
    result = await session.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id == dataset_id)
    )
    return result.scalar_one_or_none()


async def list_datasets(
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Dataset], int]:
    """List datasets with visibility filtering.

    Returns a tuple of (datasets, total_count).
    """
    # Build base query joining Record for visibility filtering
    base_stmt = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(joinedload(Dataset.record))
    )
    filtered_stmt = apply_visibility_filter(
        base_stmt, user, user_roles, Record, DatasetGrant
    )

    # Get total count
    count_stmt = select(func.count()).select_from(filtered_stmt.subquery())
    total = await session.execute(count_stmt)
    total_count = total.scalar_one()

    # Get paginated results
    paginated_stmt = (
        filtered_stmt.offset(skip).limit(limit).order_by(Record.created_at.desc())
    )
    result = await session.execute(paginated_stmt)
    datasets = list(result.scalars().unique().all())

    return datasets, total_count


async def get_datasets_list(
    db: AsyncSession,
    user: Identity,
    user_roles: set[str],
    *,
    skip: int = 0,
    limit: int = 50,
    base_url: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch paginated dataset list with raster assets, VRT source counts, and actor info.

    Returns (dataset_response_list, total_count) ready for the API response.
    """
    from app.modules.catalog.datasets.domain.helpers import (
        _load_actor_identities,
        dataset_to_response,
    )

    is_admin = "admin" in user_roles
    datasets, total = await list_datasets(db, user, user_roles, skip=skip, limit=limit)

    actors_by_id = await _load_actor_identities(
        db,
        [
            actor_id
            for dataset in datasets
            for actor_id in (dataset.record.created_by, dataset.record.updated_by)
        ],
    )

    # Batch-fetch RasterAssets for all raster and VRT datasets in the page
    raster_ids = [
        d.id
        for d in datasets
        if getattr(d.record, "record_type", None) in ("raster_dataset", "vrt_dataset")
    ]
    raster_assets_by_dataset_id = await get_catalog_port().list_raster_assets(
        db, raster_ids
    )

    # Batch source_count query for VRT datasets
    vrt_ids = [
        d.id
        for d in datasets
        if getattr(d.record, "record_type", None) == "vrt_dataset"
    ]
    source_counts: dict[str, int] = {}
    if vrt_ids:
        sc_result = await db.execute(
            text(
                "SELECT vrt_dataset_id, COUNT(*) AS cnt FROM catalog.vrt_source_links WHERE vrt_dataset_id = ANY(:ids) GROUP BY vrt_dataset_id"
            ),
            {"ids": [str(v) for v in vrt_ids]},
        )
        for row in sc_result.all():
            source_counts[row.vrt_dataset_id] = row.cnt

    response_list = [
        dataset_to_response(
            d,
            actors_by_id=actors_by_id,
            raster_asset=raster_assets_by_dataset_id.get(d.id),
            is_admin=is_admin,
            source_count=source_counts.get(str(d.id)),
            base_url=base_url,
        )
        for d in datasets
    ]

    return response_list, total


async def get_dataset_detail(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    user: Identity | None,
    *,
    base_url: str | None = None,
    collections_data: list[dict] | None = None,
    dataset: "Dataset | None" = None,
    user_roles: set[str] | None = None,
) -> "DatasetResponse | None":
    """Fetch full dataset detail including raster assets, STAC assets, and collections.

    Returns a DatasetResponse or None if not found.
    The caller is responsible for visibility checks and audit logging.
    """
    from app.modules.catalog.datasets.domain.helpers import (
        _load_actor_identities,
        dataset_to_response,
    )
    from app.modules.catalog.datasets.domain.schemas import StacAsset

    if dataset is None:
        dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        return None

    actors_by_id = await _load_actor_identities(
        db,
        [dataset.record.created_by, dataset.record.updated_by],
    )

    # Fetch RasterAsset, vrt_source_links count, and DatasetAsset rows in
    # parallel through CatalogPort so catalog does not import processing-owned
    # raster ORM classes directly.
    record_type = getattr(dataset.record, "record_type", None)
    needs_raster = record_type in ("raster_dataset", "vrt_dataset")
    needs_vrt_count = record_type == "vrt_dataset"

    # Build a labeled-coro list and gather only the ones we need; collapsing
    # the three explicit branch shapes that previously existed here.
    coros: list[tuple[str, Any]] = []
    if needs_raster:
        coros.append(
            (
                "ra",
                get_catalog_port().get_raster_asset(db, dataset.id),
            )
        )
    if needs_vrt_count:
        coros.append(
            (
                "sc",
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"
                    ),
                    {"id": str(dataset.id)},
                ),
            )
        )
    coros.append(
        (
            "da",
            get_catalog_port().get_dataset_assets(db, dataset.id),
        )
    )

    results = dict(
        zip([k for k, _ in coros], await asyncio.gather(*(c for _, c in coros)))
    )
    raster_asset = results["ra"] if "ra" in results else None
    source_count = results["sc"].scalar() if "sc" in results else None

    dataset_asset_rows = results["da"]
    stac_assets_dict = {}
    for da in dataset_asset_rows:
        stac_assets_dict[da.key] = StacAsset(
            href=da.href,
            type=da.media_type,
            title=da.title,
            description=da.description,
            roles=da.roles,
            size_bytes=da.size_bytes,
        )

    if user_roles is None:
        from app.modules.catalog.authorization import get_user_roles

        user_roles = await get_user_roles(db, user) if user is not None else set()
    is_admin = "admin" in user_roles

    return dataset_to_response(
        dataset,
        collections=collections_data,
        actors_by_id=actors_by_id,
        raster_asset=raster_asset,
        is_admin=is_admin,
        source_count=source_count,
        base_url=base_url,
        stac_assets=stac_assets_dict or None,
    )


# Geometry column names excluded from SELECT in get_dataset_rows.
_GEOM_COLUMN_NAMES = frozenset({"geom", "geom_4326", "wkb_geometry"})


def _build_select_cols(column_info: list[dict]) -> list[str]:
    """Return the non-geometry columns to project, with `gid` always present."""
    select_cols: list[str] = []
    has_gid = False
    for c in column_info:
        name = c["name"]
        if not SAFE_TABLE_NAME_RE.match(name):
            continue
        if c.get("type") == "USER-DEFINED" or name in _GEOM_COLUMN_NAMES:
            continue
        select_cols.append(name)
        if name == "gid":
            has_gid = True
    if not has_gid:
        select_cols.insert(0, "gid")
    return select_cols


def _build_where_filters(
    filters: dict[str, str] | None,
    valid_columns: set[str],
    *,
    after_gid: int,
    limit: int,
) -> tuple[str, dict[str, object]]:
    """Compose the WHERE clause + bind params for keyset pagination + ILIKE filters."""
    where_clauses: list[str] = ["gid > :after_gid"]
    bind_params: dict[str, object] = {"limit": limit, "after_gid": after_gid}
    for col_name, search_term in (filters or {}).items():
        if not SAFE_TABLE_NAME_RE.match(col_name):
            continue
        if col_name not in valid_columns:
            continue
        param_key = f"f_{col_name}"
        where_clauses.append(f"CAST({col_name} AS text) ILIKE :{param_key}")
        bind_params[param_key] = f"%{search_term}%"
    return " WHERE " + " AND ".join(where_clauses), bind_params


async def get_dataset_rows(
    db: AsyncSession,
    table_name: str,
    *,
    limit: int = 50,
    after_gid: int = 0,
    column_info: list[dict] | None = None,
    filters: dict[str, str] | None = None,
) -> tuple[list[dict], int, list[dict], int | None]:
    """Fetch keyset-paginated rows from a dataset's data table.

    Returns (rows, approximate_total, column_info, next_cursor). Uses keyset
    pagination (WHERE gid > :after_gid) for constant-time page access at any
    depth. Geometry columns are excluded from SELECT to avoid transferring
    large binary data. Count uses pg_class.reltuples for O(1) estimation.

    ``filters`` is a dict of {column_name: search_term} for ILIKE filtering.
    Column names are validated against column_info to prevent injection.
    """
    if not SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    cols = column_info or []
    select_cols = _build_select_cols(cols)
    select_sql = ", ".join(select_cols) if select_cols else "*"
    where_sql, bind_params = _build_where_filters(
        filters,
        valid_columns={c["name"] for c in cols},
        after_gid=after_gid,
        limit=limit,
    )

    try:
        result = await db.execute(
            text(
                f"SELECT {select_sql} FROM data.{table_name}{where_sql}"
                " ORDER BY gid LIMIT :limit"
            ).bindparams(**bind_params)
        )
        rows = [dict(row._mapping) for row in result.all()]

        # Approximate count via pg_class.reltuples (O(1), no table scan)
        count_result = await db.execute(
            text(
                "SELECT reltuples::bigint FROM pg_class"
                " WHERE relname = :tbl"
                " AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'data')"
            ).bindparams(tbl=table_name)
        )
        rel = count_result.scalar_one_or_none()
        approx_total = max(0, rel) if rel is not None else 0

        # Compute next_cursor from last row's gid (None when no more pages)
        next_cursor = rows[-1]["gid"] if rows and len(rows) == limit else None
    except Exception:
        # Table may not exist (dropped, migration issue, etc.). Log the
        # failure so consistent errors are visible instead of silently
        # returning empty results on every request (RES-N9).
        logger.warning(
            "Failed to query rows from data table %s",
            table_name,
            exc_info=True,
        )
        return [], 0, column_info or [], None

    return rows, approx_total, column_info or [], next_cursor
