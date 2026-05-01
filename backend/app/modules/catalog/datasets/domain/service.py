"""Dataset service layer.

Handles CRUD operations for dataset records in the catalog.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.schemas import (
        CreateEmptyDatasetRequest,
        DatasetResponse,
    )

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
)

logger = structlog.stdlib.get_logger(__name__)

_COLUMN_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_RESERVED_COLUMNS = {"gid", "geom", "geom_4326"}

_TYPE_MAP = {
    "text": "TEXT",
    "integer": "INTEGER",
    "float": "DOUBLE PRECISION",
    "date": "DATE",
    "boolean": "BOOLEAN",
}


async def create_empty_dataset(
    session: AsyncSession,
    request: "CreateEmptyDatasetRequest",
    user: Identity,
) -> Dataset:
    """Create an empty PostGIS table with user-defined columns and a catalog record.

    ``request`` should be a CreateEmptyDatasetRequest with ``title`` and ``columns``.
    """
    from app.processing.ingest.metadata import grant_reader_access
    from app.processing.ingest.service import generate_table_name

    # Validate column names
    seen_names: set[str] = set()
    for col in request.columns:
        lower_name = col.name.lower()
        if not _COLUMN_NAME_RE.match(col.name):
            raise ValueError(
                f"Invalid column name: {col.name!r}. "
                "Must start with a letter or underscore and contain only alphanumeric characters and underscores."
            )
        if lower_name in _RESERVED_COLUMNS:
            raise ValueError(
                f"Column name {col.name!r} is reserved. "
                f"Reserved names: {', '.join(sorted(_RESERVED_COLUMNS))}"
            )
        if lower_name in seen_names:
            raise ValueError(f"Duplicate column name: {col.name!r}")
        seen_names.add(lower_name)

    if not request.columns:
        raise ValueError("At least one column is required.")

    # Generate table name
    table_name, _collision_warning = await generate_table_name(request.title, session)

    # Build column definitions SQL
    col_defs = []
    for col in request.columns:
        pg_type = _TYPE_MAP[col.type]
        # Column name already validated against regex
        col_defs.append(f"{col.name.lower()} {pg_type}")

    columns_sql = ", ".join(col_defs)
    create_sql = (
        f"CREATE TABLE {_safe_table_ref(table_name)} ("
        f"gid SERIAL PRIMARY KEY, "
        f"geom geometry(Geometry, 4326), "
        f"geom_4326 geometry(Geometry, 4326), "
        f"{columns_sql}"
        f")"
    )
    await session.execute(text(create_sql))

    # Grant reader access
    await grant_reader_access(session, table_name)

    # Build column_info in standard format
    column_info = []
    for i, col in enumerate(request.columns, start=1):
        column_info.append(
            {
                "name": col.name.lower(),
                "type": _TYPE_MAP[col.type],
                "ordinal_position": i,
                "is_nullable": True,
            }
        )

    # Create catalog record
    dataset = await create_dataset(
        session,
        table_name,
        request.title,
        user.id,
        column_info=column_info,
        source_format="created",
        srid=4326,
        geometry_type="POINT",
        feature_count=0,
        visibility="private",
    )

    return dataset


async def create_dataset(
    session: AsyncSession,
    table_name: str,
    title: str,
    created_by: uuid.UUID,
    *,
    summary: str | None = None,
    srid: int | None = None,
    geometry_type: str | None = None,
    feature_count: int | None = None,
    extent_wkt: str | None = None,
    column_info: list[dict] | None = None,
    sample_values: dict | None = None,
    source_format: str | None = None,
    source_filename: str | None = None,
    original_srid: int | None = None,
    source_url: str | None = None,
    is_3d: bool | None = None,
    n_dims: int | None = None,
    z_min: float | None = None,
    z_max: float | None = None,
    visibility: str = "private",
) -> Dataset:
    """Create a record + dataset pair from ingestion results.

    Creates a Record first (shared metadata), then a Dataset linked via record_id.
    If extent_wkt is provided, converts it to a PostGIS Geometry value.
    """
    spatial_extent_value = None
    if extent_wkt and extent_wkt.startswith("POLYGON"):
        spatial_extent_value = func.ST_GeomFromText(extent_wkt, 4326)

    # Determine record_type: non-spatial datasets are 'table'
    record_type = "table" if geometry_type is None else "vector_dataset"

    record = Record(
        title=title,
        summary=summary,
        visibility=visibility,
        record_status="published",
        record_type=record_type,
        spatial_extent=spatial_extent_value,
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=feature_count,
        column_info=column_info,
        sample_values=sample_values,
        source_format=source_format,
        source_filename=source_filename,
        original_srid=original_srid,
        source_url=source_url,
        is_3d=is_3d,
        n_dims=n_dims,
        z_min=z_min,
        z_max=z_max,
    )
    session.add(dataset)
    await session.flush()

    # Eager-load the record relationship
    await session.refresh(dataset, ["record"])

    # Auto-generate standard distribution records (6 for spatial, 2 for non-spatial).
    # IMPORTANT: dataset.id is the Dataset PK (used in URL paths),
    # record.id is the Record PK (used as FK in record_distributions).
    from app.modules.catalog.records.service import generate_distributions

    await generate_distributions(
        session, dataset.id, record.id, table_name, geometry_type=geometry_type
    )

    # Auto-generate attribute metadata from column_info
    if column_info:
        from app.processing.ingest.metadata import generate_attribute_metadata

        await generate_attribute_metadata(
            session,
            dataset.id,
            column_info,
            geometry_type=geometry_type,
            sample_values=sample_values,
        )

    # Auto-detect FK relationships based on column name matching
    if column_info:
        await auto_detect_relationships(session, dataset.id, record.id, column_info)

    return dataset


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
    from app.processing.raster.models import RasterAsset

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
    raster_assets_by_dataset_id: dict[uuid.UUID, Any] = {}
    if raster_ids:
        ra_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id.in_(raster_ids))
        )
        for ra in ra_result.scalars().all():
            raster_assets_by_dataset_id[ra.dataset_id] = ra

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
    from app.processing.raster.models import DatasetAsset, RasterAsset

    if dataset is None:
        dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        return None

    actors_by_id = await _load_actor_identities(
        db,
        [dataset.record.created_by, dataset.record.updated_by],
    )

    # Fetch RasterAsset, vrt_source_links count, and DatasetAsset rows in
    # parallel (dataset detail page is a hot path; serial awaits add ~30 ms
    # of unnecessary roundtrip latency per render). All three queries run
    # against the same async session — SQLAlchemy serializes them, but
    # asyncio.gather still removes the inter-await scheduling overhead.
    record_type = getattr(dataset.record, "record_type", None)
    needs_raster = record_type in ("raster_dataset", "vrt_dataset")
    needs_vrt_count = record_type == "vrt_dataset"

    ra_coro = (
        db.execute(select(RasterAsset).where(RasterAsset.dataset_id == dataset.id))
        if needs_raster
        else None
    )
    sc_coro = (
        db.execute(
            text(
                "SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"
            ),
            {"id": str(dataset.id)},
        )
        if needs_vrt_count
        else None
    )
    da_coro = db.execute(
        select(DatasetAsset).where(DatasetAsset.dataset_id == dataset.id)
    )

    raster_asset = None
    source_count = None
    if ra_coro is not None and sc_coro is not None:
        ra_result, sc_result, da_result = await asyncio.gather(
            ra_coro, sc_coro, da_coro
        )
        raster_asset = ra_result.scalar_one_or_none()
        source_count = sc_result.scalar()
    elif ra_coro is not None:
        ra_result, da_result = await asyncio.gather(ra_coro, da_coro)
        raster_asset = ra_result.scalar_one_or_none()
    else:
        da_result = await da_coro

    dataset_asset_rows = da_result.scalars().all()
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
    if not re.match(r"^[a-z0-9_]+$", table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    # Build non-geometry column list from column_info
    geom_names = {"geom", "geom_4326", "wkb_geometry"}
    cols = column_info or []
    select_cols: list[str] = []
    has_gid = False
    for c in cols:
        name = c["name"]
        if not re.match(r"^[a-z0-9_]+$", name):
            continue
        if c.get("type") == "USER-DEFINED" or name in geom_names:
            continue
        select_cols.append(name)
        if name == "gid":
            has_gid = True
    if not has_gid:
        select_cols.insert(0, "gid")
    select_sql = ", ".join(select_cols) if select_cols else "*"

    # Build WHERE clause: always start with gid > :after_gid
    where_clauses: list[str] = ["gid > :after_gid"]
    bind_params: dict[str, object] = {"limit": limit, "after_gid": after_gid}
    valid_columns = {c["name"] for c in cols}

    for col_name, search_term in (filters or {}).items():
        if not re.match(r"^[a-z0-9_]+$", col_name):
            continue
        if col_name not in valid_columns:
            continue
        param_key = f"f_{col_name}"
        where_clauses.append(f"CAST({col_name} AS text) ILIKE :{param_key}")
        bind_params[param_key] = f"%{search_term}%"

    where_sql = " WHERE " + " AND ".join(where_clauses)

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


# ---------------------------------------------------------------------------
# Re-exports from sibling sub-modules (Phase 224 extraction — DECOUPLE-01
# preservation). Consumers continue to import these names from
# `app.modules.catalog.datasets.domain.service` unchanged. The bodies live in
# sibling modules.
# ---------------------------------------------------------------------------
from app.modules.catalog.datasets.domain.service_lifecycle import (  # noqa: E402,F401
    DependentVrtError,
    _safe_table_ref,
    delete_dataset,
    get_dataset_versions,
)
from app.modules.catalog.datasets.domain.service_metadata import (  # noqa: E402,F401
    compute_schema_diff,
    get_attribute,
    list_attributes,
    reset_attribute,
    update_attribute,
    update_auto_metadata,
    update_user_metadata,
)
from app.modules.catalog.datasets.domain.service_relationships import (  # noqa: E402,F401
    auto_detect_relationships,
    create_relationship,
    delete_relationship,
    get_related_datasets,
    get_related_records,
    list_relationships,
)
