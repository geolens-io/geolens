"""Dataset service layer.

Handles CRUD operations for dataset records in the catalog.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import TYPE_CHECKING

import logging

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.schemas import (
        CreateEmptyDatasetRequest,
        DatasetMeta,
        DatasetResponse,
    )

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.auth.models import User
from app.modules.auth.visibility import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    DatasetGrant,
    Record,
)

logger = logging.getLogger(__name__)

_COLUMN_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SAFE_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _safe_table_ref(table_name: str) -> str:
    """Return a safely quoted 'data.table_name' SQL identifier.

    Validates that the name contains only safe characters and quotes it
    to prevent SQL injection in DDL statements (CREATE/DROP/ALTER).
    """
    if not _SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")
    return f'"data"."{table_name}"'


class DependentVrtError(Exception):
    """Raised when attempting to delete a COG referenced by VRT datasets."""

    def __init__(self, dependents: list[dict]):
        self.dependents = dependents
        names = ", ".join(d["vrt_dataset_title"] for d in dependents)
        super().__init__(
            f"Cannot delete: this dataset is used as a source in "
            f"{len(dependents)} virtual raster(s): {names}"
        )


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
    user: User,
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
    user: User,
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
    user: User,
    user_roles: set[str],
    *,
    skip: int = 0,
    limit: int = 50,
    base_url: str | None = None,
) -> tuple[list[dict], int]:
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
    raster_assets_by_dataset_id: dict = {}
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
    source_counts: dict = {}
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
    user: User | None,
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

    # Fetch RasterAsset for raster and VRT datasets
    raster_asset = None
    source_count = None
    if getattr(dataset.record, "record_type", None) in (
        "raster_dataset",
        "vrt_dataset",
    ):
        ra_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
        )
        raster_asset = ra_result.scalar_one_or_none()

    if getattr(dataset.record, "record_type", None) == "vrt_dataset":
        sc_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"
            ),
            {"id": str(dataset.id)},
        )
        source_count = sc_result.scalar()

    # Query DatasetAsset rows for STAC assets
    da_result = await db.execute(
        select(DatasetAsset).where(DatasetAsset.dataset_id == dataset.id)
    )
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
        from app.modules.auth.visibility import get_user_roles

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


async def delete_dataset(
    session: AsyncSession, dataset_id: uuid.UUID, confirm_title: str
) -> str:
    """Delete a dataset: drop data table (vector) or clean storage artifacts (raster).

    Deleting the record cascades to the dataset via FK.
    Returns the table_name for logging. Does NOT commit.
    Raises ValueError if dataset not found, name mismatch, or invalid table name.
    For raster datasets, storage cleanup happens before DB deletion so that a
    storage failure prevents any DB changes (no orphaned records).
    """
    dataset = await get_dataset(session, dataset_id)
    if dataset is None:
        raise ValueError("Dataset not found")

    if dataset.record.title != confirm_title:
        raise ValueError("Dataset title does not match confirmation")

    table_name = dataset.table_name
    if not re.match(r"^[a-z0-9_]+$", table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    record_type = dataset.record.record_type

    if record_type in ("raster_dataset", "vrt_dataset"):
        from app.platform.storage.provider import get_storage

        if record_type == "raster_dataset":
            # Guard: prevent deletion if any VRT still references this COG
            refs_result = await session.execute(
                text(
                    """
                    SELECT d.id, r.title
                    FROM catalog.vrt_source_links vsl
                    JOIN catalog.datasets d ON d.id = vsl.vrt_dataset_id
                    JOIN catalog.records r ON r.id = d.record_id
                    WHERE vsl.source_dataset_id = :dataset_id
                    """
                ).bindparams(dataset_id=dataset_id)
            )
            refs = refs_result.all()
            if refs:
                raise DependentVrtError(
                    [
                        {"vrt_dataset_id": str(row.id), "vrt_dataset_title": row.title}
                        for row in refs
                    ]
                )
            # COG: clean both rasters/ and originals/ storage prefixes
            prefixes = [f"rasters/{dataset_id}/", f"originals/{dataset_id}/"]
        else:
            # VRT: only rasters/ prefix (no originals -- VRTs are generated, not uploaded)
            # vrt_source_links cascade-deleted via ON DELETE CASCADE on vrt_dataset_id FK
            prefixes = [f"rasters/{dataset_id}/"]

        # Clean up managed storage artifacts before touching the DB.
        # If any storage delete fails the exception propagates and the
        # caller's transaction rolls back, leaving the DB record intact.
        storage = get_storage()
        for prefix in prefixes:
            keys = await storage.list(prefix)
            if keys:
                await asyncio.gather(*(storage.delete(key) for key in keys))
    else:
        # Vector datasets: drop the PostGIS data table
        await session.execute(
            text(f"DROP TABLE IF EXISTS {_safe_table_ref(table_name)}")
        )

    # Delete the record (CASCADE handles dataset deletion)
    await session.delete(dataset.record)

    return table_name


async def update_user_metadata(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    meta: "DatasetMeta",
    *,
    actor_id: uuid.UUID | None = None,
) -> Dataset:
    """Update user-editable fields including extended metadata.

    Accepts a DatasetMeta Pydantic model. Only updates fields that are
    explicitly set (not None). Raises ValueError if dataset not found.
    Does not commit; caller controls transaction scope.
    """
    dataset = await get_dataset(session, dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id} not found.")

    record = dataset.record
    metadata_mutated = False

    # --- Data-driven simple assignments (meta field -> record/dataset attr) ---
    _RECORD_FIELD_MAP: dict[str, str] = {
        "title": "title",
        "summary": "summary",
        "license": "license",
        "source_organization": "source_organization",
        "data_vintage_start": "temporal_start",
        "data_vintage_end": "temporal_end",
        "lineage_summary": "lineage_summary",
        "update_frequency": "update_frequency",
        "usage_constraints": "usage_constraints",
        "access_constraints": "access_constraints",
        "sensitivity_classification": "sensitivity_classification",
        "theme_category": "theme_category",
        "owner_org": "owner_org",
        "language": "language",
    }
    _DATASET_FIELD_MAP: dict[str, str] = {
        "quality_statement": "quality_statement",
        "source_url": "source_url",
    }

    for meta_field, record_attr in _RECORD_FIELD_MAP.items():
        value = getattr(meta, meta_field)
        if value is not None:
            setattr(record, record_attr, value)
            metadata_mutated = True

    for meta_field, dataset_attr in _DATASET_FIELD_MAP.items():
        value = getattr(meta, meta_field)
        if value is not None:
            setattr(dataset, dataset_attr, value)
            metadata_mutated = True

    # --- Special-case fields requiring extra logic ---

    # Visibility: block restricting a dataset used in public maps
    if meta.visibility is not None:
        if meta.visibility != "public" and record.visibility == "public":
            from app.modules.catalog.maps.service import find_public_maps_using_dataset

            public_maps = await find_public_maps_using_dataset(session, dataset_id)
            if public_maps:
                raise ValueError(
                    f"Cannot restrict visibility: dataset is used in public maps: {', '.join(public_maps)}"
                )
        record.visibility = meta.visibility
        metadata_mutated = True

    # Record status: validate on transition TO published
    if meta.record_status is not None:
        if meta.record_status == "published" and record.record_status != "published":
            from app.core.persistent_config import REQUIRE_METADATA_FOR_PUBLISH

            require_metadata = await REQUIRE_METADATA_FOR_PUBLISH.get(session)
            if require_metadata:
                from app.modules.catalog.validation.service import validate_record

                result = await validate_record(session, record, dataset)
                if not result.is_valid:
                    error_msgs = [f"{e.field}: {e.message}" for e in result.errors]
                    raise ValueError(f"Cannot publish: {'; '.join(error_msgs)}")
            record.published_at = func.now()
        record.record_status = meta.record_status
        metadata_mutated = True

    # Raster-specific: is_dem flag on RasterAsset
    if meta.is_dem is not None:
        from app.processing.raster.models import RasterAsset

        ra_result = await session.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
        )
        ra = ra_result.scalar_one_or_none()
        if ra is not None:
            ra.is_dem = meta.is_dem
            metadata_mutated = True

    if actor_id is not None and metadata_mutated:
        record.updated_by = actor_id

    # Check if embedding-relevant fields changed
    embedding_fields_changed = any(
        getattr(meta, f) is not None for f in ("title", "summary", "lineage_summary")
    )

    await session.flush()

    # Trigger embedding regeneration if relevant fields changed
    if embedding_fields_changed:
        try:
            from app.processing.embeddings.tasks import embed_record

            await embed_record.defer_async(record_id=str(record.id))
        except Exception:
            # Non-fatal -- embedding will catch up on next edit or backfill.
            # Log with traceback so operators can notice if this fails consistently
            # (e.g., broker down) instead of silently dropping edits from the index.
            logger.warning(
                "Failed to defer embed_record task for record %s (dataset %s)",
                record.id,
                dataset.id,
                exc_info=True,
            )

    return dataset


async def update_auto_metadata(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    srid: int | None = None,
    geometry_type: str | None = None,
    feature_count: int | None = None,
    extent_wkt: str | None = None,
    column_info: list[dict] | None = None,
) -> Dataset:
    """Update only auto-extracted fields. Never touches title/summary.

    extent_wkt now updates Record.spatial_extent. srid, geometry_type,
    feature_count, column_info stay on Dataset.
    Only updates fields that are not None. Raises ValueError if dataset not found.
    """
    dataset = await get_dataset(session, dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id} not found.")

    if srid is not None:
        dataset.srid = srid
    if geometry_type is not None:
        dataset.geometry_type = geometry_type
    if feature_count is not None:
        dataset.feature_count = feature_count
    if extent_wkt is not None:
        dataset.record.spatial_extent = func.ST_GeomFromText(extent_wkt, 4326)
    if column_info is not None:
        dataset.column_info = column_info

    await session.commit()
    await session.refresh(dataset)
    return dataset


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


_TYPE_EQUIVALENCES = {
    "string": "character varying",
    "integer": "integer",
    "real": "double precision",
    "int": "integer",
    "int64": "bigint",
    "float": "double precision",
}


def _normalize_col_type(col_type: str) -> str:
    return _TYPE_EQUIVALENCES.get(col_type.lower(), col_type.lower())


def compute_schema_diff(
    old_columns: list[dict],
    new_columns: list[dict],
    old_feature_count: int | None,
    new_feature_count: int | None,
) -> dict:
    """Compute the difference between old and new column schemas.

    Column matching is case-insensitive (ogr2ogr lowercases on import,
    but remote sources report original case). Type comparison normalizes
    common OGR-to-PostgreSQL type mappings (e.g. String ↔ character varying).
    """
    old_by_lower = {c["name"].lower(): c for c in old_columns}
    new_by_lower = {c["name"].lower(): c for c in new_columns}
    old_keys = set(old_by_lower)
    new_keys = set(new_by_lower)

    return {
        "columns_added": [
            {"name": new_by_lower[n]["name"], "type": new_by_lower[n]["type"]}
            for n in sorted(new_keys - old_keys)
        ],
        "columns_removed": [
            {"name": old_by_lower[n]["name"], "type": old_by_lower[n]["type"]}
            for n in sorted(old_keys - new_keys)
        ],
        "type_changes": [
            {
                "name": new_by_lower[n]["name"],
                "old_type": old_by_lower[n]["type"],
                "new_type": new_by_lower[n]["type"],
            }
            for n in sorted(old_keys & new_keys)
            if _normalize_col_type(old_by_lower[n]["type"])
            != _normalize_col_type(new_by_lower[n]["type"])
        ],
        "row_count_old": old_feature_count,
        "row_count_new": new_feature_count,
        "row_count_delta": (new_feature_count or 0) - (old_feature_count or 0),
    }


async def get_dataset_versions(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """List version history for a dataset, ordered by version_number desc.

    Returns a tuple of (versions, total_count).
    """
    from app.modules.catalog.collections.models import DatasetVersion

    base_stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)

    # Get total count
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = await session.execute(count_stmt)
    total_count = total.scalar_one()

    # Get paginated results
    paginated_stmt = (
        base_stmt.order_by(DatasetVersion.version_number.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(paginated_stmt)
    versions = list(result.scalars().all())

    return versions, total_count


# ---------------------------------------------------------------------------
# Attribute metadata service functions
# ---------------------------------------------------------------------------


async def list_attributes(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    include_removed: bool = False,
) -> list[AttributeMetadata]:
    """List attribute metadata rows for a dataset.

    By default excludes is_current=False rows. Pass include_removed=True
    to return all rows including removed columns.
    """
    stmt = select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
    if not include_removed:
        stmt = stmt.where(AttributeMetadata.is_current == True)  # noqa: E712
    stmt = stmt.order_by(AttributeMetadata.ordinal_position.nulls_last())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_attribute(
    session: AsyncSession, attribute_id: uuid.UUID
) -> AttributeMetadata | None:
    """Fetch a single attribute metadata row by ID."""
    result = await session.execute(
        select(AttributeMetadata).where(AttributeMetadata.id == attribute_id)
    )
    return result.scalar_one_or_none()


async def update_attribute(
    session: AsyncSession, attribute_id: uuid.UUID, **kwargs
) -> AttributeMetadata:
    """Update user-editable attribute metadata fields.

    Tracks which fields the user has modified in user_modified_fields.
    Raises ValueError if attribute not found.
    """
    attr = await get_attribute(session, attribute_id)
    if attr is None:
        raise ValueError("Attribute not found")

    editable = {"title", "description", "units", "semantic_role", "domain_type"}
    modified_fields = set(attr.user_modified_fields or [])
    for key, value in kwargs.items():
        if key in editable:
            setattr(attr, key, value)
            modified_fields.add(key)
    attr.user_modified_fields = sorted(modified_fields)

    await session.flush()
    return attr


async def reset_attribute(
    session: AsyncSession, attribute_id: uuid.UUID, table_name: str
) -> AttributeMetadata:
    """Reset attribute metadata to auto-populated values.

    Re-infers title, semantic_role, domain_type, units from field_name/data_type.
    Re-samples example_values from the data table.
    Clears user_modified_fields and description.
    Raises ValueError if attribute not found.
    """
    import re

    from app.processing.ingest.metadata import (
        _humanize_column_name,
        _infer_domain_type,
        _infer_semantic_role,
        _infer_units,
    )

    attr = await get_attribute(session, attribute_id)
    if attr is None:
        raise ValueError("Attribute not found")

    # Re-compute inferred values
    attr.title = _humanize_column_name(attr.field_name)
    attr.semantic_role = _infer_semantic_role(attr.field_name, attr.data_type or "")
    attr.domain_type = _infer_domain_type(attr.data_type or "")
    attr.units = _infer_units(attr.field_name)
    attr.description = None
    attr.user_modified_fields = []

    # Re-sample example_values from data table (skip geometry columns)
    if attr.data_type and "geometry" not in attr.data_type.lower():
        col_name = attr.field_name
        _table_re = re.compile(r"^[a-z0-9_]+$")
        if _table_re.match(col_name) and _table_re.match(table_name):
            try:
                result = await session.execute(
                    text(
                        f"SELECT DISTINCT {col_name}::text AS val "
                        f"FROM (SELECT {col_name} FROM data.{table_name} "
                        f"WHERE {col_name} IS NOT NULL LIMIT 1000) sub LIMIT 10"
                    )
                )
                values = [row[0] for row in result.all() if row[0] is not None]
                attr.example_values = values if values else None
            except Exception:
                # Sampling is best-effort; don't fail the reset because we
                # couldn't gather example values, but do log so operators can
                # notice if this breaks consistently (RES-N9).
                logger.warning(
                    "Failed to sample example_values for %s.%s",
                    table_name,
                    col_name,
                    exc_info=True,
                )
                attr.example_values = None
        else:
            attr.example_values = None
    else:
        attr.example_values = None

    await session.flush()
    return attr


async def get_related_datasets(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    user: User | None,
    user_roles: set[str],
    *,
    limit: int = 5,
) -> list[dict]:
    """Return top-N datasets similar to the given dataset by embedding cosine distance.

    Returns an empty list when the dataset has no embedding or no neighbors
    exceed the similarity threshold (0.3, i.e. cosine distance <= 0.7).
    Results are RBAC-filtered to only include datasets visible to the requesting user.
    """
    from app.processing.embeddings.models import RecordEmbedding

    try:
        # Get the dataset's record_id
        record_id_row = (
            await db.execute(select(Dataset.record_id).where(Dataset.id == dataset_id))
        ).first()
        if record_id_row is None:
            return []
        record_id = record_id_row[0]

        # Get the dataset's embedding for distance calculation
        emb_row = (
            await db.execute(
                select(RecordEmbedding.embedding)
                .where(RecordEmbedding.record_id == record_id)
                .limit(1)
            )
        ).first()
        if emb_row is None:
            return []
        embedding = emb_row[0]

        # Find nearest neighbors using shared helper (over-fetch for RBAC filtering)
        from app.processing.embeddings.helpers import get_nearest_record_ids

        neighbor_record_ids = await get_nearest_record_ids(
            db, record_id, limit=limit * 3, max_distance=0.7
        )

        if not neighbor_record_ids:
            return []

        # Compute distances for the neighbors (needed for similarity score)
        nn_dist_stmt = select(
            RecordEmbedding.record_id,
            RecordEmbedding.embedding.cosine_distance(embedding).label("distance"),
        ).where(RecordEmbedding.record_id.in_(neighbor_record_ids))
        nn_dist_result = await db.execute(nn_dist_stmt)
        neighbor_map = {r.record_id: r.distance for r in nn_dist_result.all()}

        # Join to Dataset + Record to get metadata, apply visibility filter.
        # Use a fresh local `ds_stmt` so mypy re-infers `Dataset` as the row
        # type (the earlier `select(Dataset.record_id)` bound `ds_result` to
        # `Result[UUID]` which leaked into the reassignment).
        ds_stmt = (
            select(Dataset)
            .join(Record, Dataset.record_id == Record.id)
            .where(Record.id.in_(neighbor_record_ids))
            .options(joinedload(Dataset.record))
        )
        ds_stmt = apply_visibility_filter(
            ds_stmt, user, user_roles, Record, DatasetGrant
        )
        dataset_result = await db.execute(ds_stmt)
        datasets = list(dataset_result.scalars().unique().all())

        # Build response items sorted by similarity (descending). `similarity`
        # is always a float (the list is only appended to when distance is
        # not None), but mypy widens the dict value type to the union of all
        # keys; pin it on the sort key to keep the lambda return typed.
        items: list[dict] = []
        for ds in datasets:
            distance = neighbor_map.get(ds.record_id)
            if distance is not None:
                items.append(
                    {
                        "id": str(ds.id),
                        "name": ds.record.title,
                        "geometry_type": ds.geometry_type,
                        "similarity": round(1.0 - float(distance), 4),
                        "record_type": ds.record.record_type if ds.record else None,
                        "feature_count": ds.feature_count,
                    }
                )

        items.sort(key=lambda x: float(x["similarity"]), reverse=True)
        return items[:limit]

    except Exception:
        logger.exception("Error fetching related datasets for %s", dataset_id)
        return []


# ---------------------------------------------------------------------------
# Dataset FK relationships
# ---------------------------------------------------------------------------


async def create_relationship(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    rel,
):  # -> DatasetRelationship
    """Create FK relationship from source dataset to target dataset."""
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    obj = DatasetRelationship(
        source_dataset_id=dataset_id,
        target_dataset_id=rel.target_dataset_id,
        source_column=rel.source_column,
        target_column=rel.target_column,
        label=rel.label,
    )
    session.add(obj)
    await session.flush()
    await session.refresh(obj)
    return obj


async def list_relationships(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list:
    """List FK relationships where this dataset is the source.

    Joins with records table to include target_dataset_title. Supports
    optional ``skip``/``limit`` pagination (PERF-N16) to bound response
    size for datasets with hundreds of auto-detected relationships.
    """
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    stmt = (
        select(DatasetRelationship, Record.title)
        .outerjoin(Record, DatasetRelationship.target_dataset_id == Record.id)
        .where(DatasetRelationship.source_dataset_id == dataset_id)
        .order_by(DatasetRelationship.created_at)
    )
    if skip:
        stmt = stmt.offset(skip)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    rows = result.all()
    items = []
    for rel, title in rows:
        items.append(
            {
                "id": rel.id,
                "source_dataset_id": rel.source_dataset_id,
                "target_dataset_id": rel.target_dataset_id,
                "source_column": rel.source_column,
                "target_column": rel.target_column,
                "relationship_type": rel.relationship_type,
                "label": rel.label,
                "target_dataset_title": title,
            }
        )
    return items


async def delete_relationship(
    session: AsyncSession,
    relationship_id: uuid.UUID,
) -> None:
    """Delete a relationship by ID."""
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    result = await session.execute(
        select(DatasetRelationship).where(DatasetRelationship.id == relationship_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise ValueError("Relationship not found")
    await session.delete(obj)
    await session.flush()


# Primary-key column names to exclude from FK candidate detection
_PK_COLUMN_NAMES = {"gid", "ogc_fid", "fid", "objectid", "id"}


async def auto_detect_relationships(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    column_info: list[dict],
) -> list:
    """Auto-detect FK relationships based on *_id column name matching.

    For each column ending with ``_id`` (excluding common PK names), look for
    other datasets that have an attribute with the same name marked as
    ``semantic_role='identifier'``.  When a match is found a
    ``DatasetRelationship`` row is created (idempotently via ON CONFLICT DO
    NOTHING on the existing unique constraint).
    """
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    candidates = [
        col["name"]
        for col in column_info
        if col["name"].endswith("_id") and col["name"].lower() not in _PK_COLUMN_NAMES
    ]
    if not candidates:
        return []

    # PERF-N4: collapse the previous per-candidate loop (N queries for the
    # identifier match + N queries for the existence check) into two bulk
    # queries using IN (...). For a dataset with 30 *_id candidates that's
    # 60 round trips → 2 round trips.
    match_result = await session.execute(
        select(
            AttributeMetadata.field_name,
            Dataset.record_id,
        )
        .join(Dataset, AttributeMetadata.dataset_id == Dataset.id)
        .where(
            AttributeMetadata.field_name.in_(candidates),
            AttributeMetadata.semantic_role == "identifier",
            Dataset.record_id != record_id,  # skip self-references
        )
    )
    # Group matches by column name so we can produce one relationship per
    # (source_column, target_record_id).
    matches_by_col: dict[str, list[uuid.UUID]] = {}
    for field_name, target_record_id in match_result.all():
        matches_by_col.setdefault(field_name, []).append(target_record_id)

    if not matches_by_col:
        return []

    # Pre-fetch existing relationships in one query so the idempotency check
    # doesn't require another round trip per candidate match.
    existing_result = await session.execute(
        select(
            DatasetRelationship.source_column,
            DatasetRelationship.target_dataset_id,
        ).where(
            DatasetRelationship.source_dataset_id == record_id,
            DatasetRelationship.source_column.in_(matches_by_col.keys()),
        )
    )
    existing_keys: set[tuple[str, uuid.UUID]] = {
        (col, tgt) for col, tgt in existing_result.all()
    }

    created: list[DatasetRelationship] = []
    for col_name, target_record_ids in matches_by_col.items():
        for target_record_id in target_record_ids:
            if (col_name, target_record_id) in existing_keys:
                continue
            obj = DatasetRelationship(
                source_dataset_id=record_id,
                target_dataset_id=target_record_id,
                source_column=col_name,
                target_column=col_name,
                label=None,
            )
            session.add(obj)
            created.append(obj)
            existing_keys.add(
                (col_name, target_record_id)
            )  # avoid dup if same col/target

    if created:
        await session.flush()
        logger.info(
            "Auto-detected %d FK relationship(s) for dataset %s",
            len(created),
            dataset_id,
        )

    return created


async def get_related_records(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    feature_gid: int,
    relationship_id: uuid.UUID,
    *,
    limit: int = 50,
    after: int = 0,
) -> dict:
    """Get related records for a feature via FK relationship.

    Looks up the FK value in the source table, then queries the target table
    for matching rows.
    """
    import re as _re

    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    # 1. Load relationship
    result = await session.execute(
        select(DatasetRelationship).where(DatasetRelationship.id == relationship_id)
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        raise ValueError("Relationship not found")

    # 2. Load source dataset to get table_name
    source_ds = await get_dataset(session, dataset_id)
    if source_ds is None:
        raise ValueError("Source dataset not found")

    # 3. Load target dataset to get table_name
    # target_dataset_id points to a Record, need to find its Dataset
    target_result = await session.execute(
        select(Dataset).where(Dataset.record_id == rel.target_dataset_id)
    )
    target_ds = target_result.scalar_one_or_none()
    if target_ds is None:
        raise ValueError("Target dataset not found")

    # Validate column names
    safe_col = _re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    if not safe_col.match(rel.source_column) or not safe_col.match(rel.target_column):
        raise ValueError("Invalid column name in relationship")

    # 4. Get FK value from source table
    fk_result = await session.execute(
        text(
            f"SELECT {rel.source_column} FROM data.{source_ds.table_name} WHERE gid = :gid"
        ).bindparams(gid=feature_gid)
    )
    fk_value = fk_result.scalar_one_or_none()
    if fk_value is None:
        return {"rows": [], "approximate_total": 0, "next_cursor": None, "columns": []}

    # 5. Query target table for matching rows
    count_result = await session.execute(
        text(
            f"SELECT COUNT(*) FROM data.{target_ds.table_name} "
            f"WHERE {rel.target_column} = :fk_val"
        ).bindparams(fk_val=fk_value)
    )
    total = count_result.scalar_one()

    rows_result = await session.execute(
        text(
            f"SELECT gid, to_jsonb(t.*) - 'gid' - 'geom' - 'geom_4326' AS properties "
            f"FROM data.{target_ds.table_name} t "
            f"WHERE t.{rel.target_column} = :fk_val "
            f"ORDER BY gid LIMIT :lim OFFSET :off"
        ).bindparams(fk_val=fk_value, lim=limit, off=after)
    )
    rows = [
        {"gid": row[0], **(row[1] if isinstance(row[1], dict) else {})}
        for row in rows_result.all()
    ]

    # Get column info for target table
    from app.processing.ingest.metadata import get_column_info

    columns = await get_column_info(session, target_ds.table_name)
    col_list = [{"name": c["name"], "type": c["type"]} for c in columns]

    next_cursor = after + limit if after + limit < total else None

    return {
        "rows": rows,
        "approximate_total": total,
        "next_cursor": next_cursor,
        "columns": col_list,
    }
