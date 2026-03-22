"""Layer creation orchestration service.

Creates an empty PostGIS table with typed geometry column, runs the full
ingestion post-processing pipeline, and registers the layer as a catalog dataset.
"""

import uuid

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.datasets.models import AttributeMetadata, Dataset
from app.datasets.service import create_dataset
from app.ingest.metadata import (
    _humanize_column_name,
    _infer_domain_type,
    _infer_semantic_role,
    _infer_units,
    _validate_table_name,
    add_4326_column,
    compute_quality_score,
    get_column_info,
    grant_reader_access,
)
from app.ingest.service import generate_table_name
from app.layers.schemas import ALLOWED_COLUMN_TYPES, COLUMN_NAME_RE, RESERVED_COLUMNS

logger = structlog.stdlib.get_logger(__name__)


async def create_layer(
    session: AsyncSession,
    name: str,
    geometry_type: str,
    created_by: uuid.UUID,
    *,
    columns: list | None = None,
    description: str | None = None,
) -> Dataset:
    """Create an empty spatial layer with full post-processing.

    Steps mirror the ingest pipeline (tasks.py):
    1. Generate table name
    2. CREATE TABLE with typed geometry column (+ optional attribute columns)
    3. Add geom_4326 column + spatial index
    4. Grant geolens_reader SELECT
    5. Extract column info
    7. Create catalog dataset record
    8. Compute quality score

    Returns the created Dataset record.
    """
    # 1. Generate table name
    table_name, collision_warning = await generate_table_name(name, session)
    if collision_warning:
        logger.info("layer.table_name_collision", warning=collision_warning)

    # 2. Build and execute CREATE TABLE DDL
    col_defs = "gid SERIAL PRIMARY KEY, geom geometry({geom_type}, 4326)".format(
        geom_type=geometry_type,
    )
    if columns:
        for col in columns:
            # Double-check column name safety before interpolation
            if not COLUMN_NAME_RE.match(col.name):
                raise ValueError(f"Invalid column name: {col.name!r}")
            pg_type = ALLOWED_COLUMN_TYPES[col.type]
            col_defs += f", {col.name} {pg_type}"

    ddl = f"CREATE TABLE data.{table_name} ({col_defs})"
    await session.execute(text(ddl))

    # 3. Add geom_4326 column + spatial index (source is already 4326)
    await add_4326_column(session, table_name, 4326)

    # 4. Grant geolens_reader SELECT
    await grant_reader_access(session, table_name)

    # 5. Get column info for catalog record
    column_info = await get_column_info(session, table_name)

    # 6. Create dataset in catalog
    dataset = await create_dataset(
        session,
        table_name=table_name,
        title=name,
        created_by=created_by,
        summary=description,
        srid=4326,
        geometry_type=geometry_type.upper(),
        feature_count=0,
        column_info=column_info,
        source_format="created",
        visibility="private",
    )

    # 7. Compute quality score
    quality_score = await compute_quality_score(
        session, table_name, column_info, dataset
    )
    dataset.quality_detail = quality_score
    await session.flush()

    return dataset


async def add_column(
    session: AsyncSession,
    dataset: Dataset,
    column_name: str,
    column_type: str,
) -> list[dict]:
    """Add a column to an existing layer's PostGIS table.

    Validates the table name, column name, and column type before executing
    ALTER TABLE. Refreshes column_info from information_schema afterwards.
    """
    _validate_table_name(dataset.table_name)

    # Validate column name
    if not COLUMN_NAME_RE.match(column_name):
        raise ValueError(
            f"Column name {column_name!r} must start with a lowercase letter "
            "and contain only lowercase letters, digits, and underscores "
            "(max 63 chars)."
        )
    if column_name in RESERVED_COLUMNS:
        raise ValueError(f"Column name {column_name!r} is reserved and cannot be used.")

    # Validate type
    if column_type not in ALLOWED_COLUMN_TYPES:
        raise ValueError(
            f"Column type {column_type!r} is not allowed. "
            f"Allowed types: {sorted(ALLOWED_COLUMN_TYPES.keys())}"
        )

    # Check for duplicate column name
    existing_names = {c["name"] for c in (dataset.column_info or [])}
    if column_name in existing_names:
        raise ValueError(f"Column {column_name!r} already exists on this layer.")

    pg_type = ALLOWED_COLUMN_TYPES[column_type]

    # Execute DDL
    ddl = f"ALTER TABLE data.{dataset.table_name} ADD COLUMN {column_name} {pg_type}"
    await session.execute(text(ddl))

    # Refresh column_info
    column_info = await get_column_info(session, dataset.table_name)
    dataset.column_info = column_info

    # Create AttributeMetadata row for the new column
    new_col = next((c for c in column_info if c["name"] == column_name), None)
    if new_col:
        data_type = new_col.get("type", "")
        am = AttributeMetadata(
            dataset_id=dataset.id,
            field_name=column_name,
            title=_humanize_column_name(column_name),
            data_type=data_type,
            units=_infer_units(column_name),
            semantic_role=_infer_semantic_role(column_name, data_type),
            domain_type=_infer_domain_type(data_type),
            ordinal_position=new_col.get("ordinal_position"),
            is_nullable=new_col.get("is_nullable"),
            is_current=True,
        )
        session.add(am)

    await session.flush()

    return column_info


async def drop_column(
    session: AsyncSession,
    dataset: Dataset,
    column_name: str,
) -> list[dict]:
    """Drop a column from an existing layer's PostGIS table.

    Validates the table name, column name (rejects reserved columns),
    and verifies the column exists before executing ALTER TABLE.
    Refreshes column_info from information_schema afterwards.
    """
    _validate_table_name(dataset.table_name)

    # Validate column name format
    if not COLUMN_NAME_RE.match(column_name):
        raise ValueError(f"Column name {column_name!r} is not a valid column name.")

    # Reject reserved columns
    if column_name in RESERVED_COLUMNS:
        raise ValueError(f"Column {column_name!r} is reserved and cannot be removed.")

    # Verify column exists in current column_info
    existing_names = {c["name"] for c in (dataset.column_info or [])}
    if column_name not in existing_names:
        raise ValueError(f"Column {column_name!r} does not exist on this layer.")

    # Execute DDL
    ddl = f"ALTER TABLE data.{dataset.table_name} DROP COLUMN {column_name}"
    await session.execute(text(ddl))

    # Refresh column_info
    column_info = await get_column_info(session, dataset.table_name)
    dataset.column_info = column_info

    # Mark AttributeMetadata row as removed
    result = await session.execute(
        select(AttributeMetadata).where(
            AttributeMetadata.dataset_id == dataset.id,
            AttributeMetadata.field_name == column_name,
        )
    )
    am = result.scalar_one_or_none()
    if am:
        am.is_current = False

    await session.flush()

    return column_info
