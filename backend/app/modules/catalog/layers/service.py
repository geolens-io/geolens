"""Layer creation orchestration service.

Creates an empty PostGIS table with typed geometry column, runs the full
ingestion post-processing pipeline, and registers the layer as a catalog dataset.
"""

import uuid

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema, tenant_reader_role
from app.core.db.tenant_session import current_tenant_var
from app.modules.catalog.datasets.domain.models import AttributeMetadata, Dataset
from app.modules.catalog.datasets.domain.service import create_dataset
from app.modules.catalog.layers.schemas import (
    ALLOWED_COLUMN_TYPES,
    COLUMN_NAME_RE,
    RESERVED_COLUMNS,
)
from app.platform.extensions import get_catalog_port
from app.modules.catalog.features.service import lock_catalog_rows_for_write

logger = structlog.stdlib.get_logger(__name__)


def _qcol(name: str) -> str:
    """Return a double-quoted column identifier for DDL interpolation.

    fix(#458): a reserved-word name (``desc``, ``order`` — routine ogr2ogr
    DBF output) passes COLUMN_NAME_RE but breaks unquoted DDL. Names are
    already regex-validated, so this is belt-and-braces, not an injection guard.
    """
    return '"' + name.replace('"', '""') + '"'


async def _compute_quality_detail(
    session: AsyncSession, dataset: Dataset, column_info: list[dict]
) -> object:
    """The quality score for a schema change, WITHOUT storing it.

    fix(#458): column DDL didn't recompute quality_detail like
    reupload does, so attribute_completeness went stale until the next
    reupload. Returns rather than assigns so the caller can run it before
    taking the catalog rows; `no_autoflush` because those rows aren't held yet.
    """
    with session.no_autoflush:
        return await get_catalog_port().compute_quality_score(
            session,
            dataset.table_name,
            column_info,
            dataset,
        )


async def create_layer(
    session: AsyncSession,
    name: str,
    geometry_type: str,
    created_by: uuid.UUID,
    *,
    columns: list | None = None,
    description: str | None = None,
) -> Dataset:
    """Create an empty spatial layer with full post-processing, mirroring the
    ingest pipeline (tasks.py): table + geom_4326 + index, reader grant,
    column info, catalog dataset record, quality score.

    Returns the created Dataset record.
    """
    table_name, collision_warning = await get_catalog_port().generate_table_name(
        name, session
    )
    if collision_warning:
        logger.info("layer.table_name_collision", warning=collision_warning)

    tenant_id = current_tenant_var.get()
    data_schema = tenant_data_schema(tenant_id)
    reader_role = tenant_reader_role(tenant_id)
    table_ref = get_catalog_port().quote_table(table_name, schema=data_schema)

    col_defs = "gid SERIAL PRIMARY KEY, geom geometry({geom_type}, 4326)".format(
        geom_type=geometry_type,
    )
    if columns:
        for col in columns:
            if not COLUMN_NAME_RE.match(col.name):
                raise ValueError(f"Invalid column name: {col.name!r}")
            pg_type = ALLOWED_COLUMN_TYPES[col.type]
            col_defs += f", {_qcol(col.name)} {pg_type}"

    ddl = f"CREATE TABLE {table_ref} ({col_defs})"
    await session.execute(text(ddl))

    # Adds geom_4326 and its index; source is already 4326, so the copy needs
    # no ST_Transform.
    await get_catalog_port().add_4326_column(
        session, table_name, 4326, schema=data_schema
    )

    await get_catalog_port().grant_reader_access(
        session,
        table_name,
        schema=data_schema,
        role=reader_role,
    )

    column_info = await get_catalog_port().get_column_info(
        session, table_name, schema=data_schema
    )

    from app.modules.catalog.datasets.domain.schemas import IngestionResult

    dataset = await create_dataset(
        session,
        table_name=table_name,
        title=name,
        created_by=created_by,
        summary=description,
        visibility="private",
        ingestion=IngestionResult(
            srid=4326,
            geometry_type=geometry_type.upper(),
            feature_count=0,
            column_info=column_info,
            source_format="created",
        ),
    )

    quality_score = await get_catalog_port().compute_quality_score(
        session,
        table_name,
        column_info,
        dataset,
        schema=data_schema,
    )
    dataset.quality_detail = quality_score
    await session.flush()

    return dataset


async def count_maps_referencing_column(
    session: AsyncSession, dataset_id: uuid.UUID, column_name: str
) -> int:
    """Count distinct saved maps whose layer config references the column.

    fix(#458): warns before a rename/drop breaks a saved map's
    data-driven style, filter, label, or popup. Text-scans the JSONB configs
    for the quoted column name — approximate, but scoped to this dataset.
    """
    if not COLUMN_NAME_RE.match(column_name):
        return 0
    pattern = f'%"{column_name}"%'
    result = await session.execute(
        text(
            "SELECT COUNT(DISTINCT map_id) FROM catalog.map_layers "
            "WHERE dataset_id = :ds AND ("
            "COALESCE(style_config::text, '') LIKE :pat "
            "OR COALESCE(paint::text, '') LIKE :pat "
            "OR COALESCE(layout::text, '') LIKE :pat "
            "OR COALESCE(\"filter\"::text, '') LIKE :pat "
            "OR COALESCE(label_config::text, '') LIKE :pat "
            "OR COALESCE(popup_config::text, '') LIKE :pat)"
        ).bindparams(ds=dataset_id, pat=pattern)
    )
    return int(result.scalar_one())


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
    get_catalog_port().validate_table_name(dataset.table_name)

    if not COLUMN_NAME_RE.match(column_name):
        raise ValueError(
            f"Column name {column_name!r} must start with a lowercase letter "
            "and contain only lowercase letters, digits, and underscores "
            "(max 63 chars)."
        )
    if column_name in RESERVED_COLUMNS:
        raise ValueError(f"Column name {column_name!r} is reserved and cannot be used.")

    if column_type not in ALLOWED_COLUMN_TYPES:
        raise ValueError(
            f"Column type {column_type!r} is not allowed. "
            f"Allowed types: {sorted(ALLOWED_COLUMN_TYPES.keys())}"
        )

    existing_names = {c["name"] for c in (dataset.column_info or [])}
    if column_name in existing_names:
        raise ValueError(f"Column {column_name!r} already exists on this layer.")

    pg_type = ALLOWED_COLUMN_TYPES[column_type]

    table_ref = get_catalog_port().quote_table(dataset.table_name)
    ddl = f"ALTER TABLE {table_ref} ADD COLUMN {_qcol(column_name)} {pg_type}"
    await session.execute(text(ddl))

    column_info = await get_catalog_port().get_column_info(session, dataset.table_name)
    # fix(#1847): scan, then lock, then assign — the scan needs neither
    # catalog row, and the lock must follow the ALTER since the reupload swap
    # takes its data-table ACCESS EXCLUSIVE before its catalog rows.
    quality_detail = await _compute_quality_detail(session, dataset, column_info)
    await lock_catalog_rows_for_write(session, dataset)
    dataset.column_info = column_info
    dataset.quality_detail = quality_detail

    # fix(#458): (dataset_id, field_name) is unique, so re-adding a
    # previously dropped name must revive the historical is_current=False row
    # instead of inserting a duplicate (UniqueViolation -> 500).
    new_col = next((c for c in column_info if c["name"] == column_name), None)
    if new_col:
        data_type = new_col.get("type", "")
        result = await session.execute(
            select(AttributeMetadata).where(
                AttributeMetadata.dataset_id == dataset.id,
                AttributeMetadata.field_name == column_name,
            )
        )
        am = result.scalar_one_or_none()
        if am is None:
            am = AttributeMetadata(
                dataset_id=dataset.id,
                field_name=column_name,
                title=get_catalog_port().humanize_column_name(column_name),
            )
            session.add(am)
        am.data_type = data_type
        # fix(#458): the revive path (drop → re-add the same name) used to
        # overwrite user-customized inferred fields with fresh inference while
        # user_modified_fields still claimed the customization. Honor it.
        user_modified = set(am.user_modified_fields or [])
        if "units" not in user_modified:
            am.units = get_catalog_port().infer_units(column_name)
        if "semantic_role" not in user_modified:
            am.semantic_role = get_catalog_port().infer_semantic_role(
                column_name, data_type
            )
        if "domain_type" not in user_modified:
            am.domain_type = get_catalog_port().infer_domain_type(data_type)
        am.ordinal_position = new_col.get("ordinal_position")
        am.is_nullable = new_col.get("is_nullable")
        am.is_current = True

    await session.flush()

    return column_info


async def rename_column(
    session: AsyncSession,
    dataset: Dataset,
    column_name: str,
    new_name: str,
) -> list[dict]:
    """Rename a column on an existing layer's PostGIS table.

    Validates names, rejects reserved columns, and ensures the destination
    name is not already in use. Refreshes ``column_info`` and migrates the
    matching ``AttributeMetadata`` row to the new name afterwards.
    """
    get_catalog_port().validate_table_name(dataset.table_name)

    if not COLUMN_NAME_RE.match(column_name):
        raise ValueError(f"Column name {column_name!r} is not a valid column name.")
    if not COLUMN_NAME_RE.match(new_name):
        raise ValueError(f"Column name {new_name!r} is not a valid column name.")
    if column_name in RESERVED_COLUMNS:
        raise ValueError(f"Column {column_name!r} is reserved and cannot be renamed.")
    if new_name in RESERVED_COLUMNS:
        raise ValueError(f"Column {new_name!r} is reserved and cannot be used.")
    if column_name == new_name:
        raise ValueError("New column name must differ from the current name.")

    existing_names = {c["name"] for c in (dataset.column_info or [])}
    if column_name not in existing_names:
        raise ValueError(f"Column {column_name!r} does not exist on this layer.")
    if new_name in existing_names:
        raise ValueError(f"Column {new_name!r} already exists on this layer.")

    table_ref = get_catalog_port().quote_table(dataset.table_name)
    ddl = f"ALTER TABLE {table_ref} RENAME COLUMN {_qcol(column_name)} TO {_qcol(new_name)}"
    await session.execute(text(ddl))

    column_info = await get_catalog_port().get_column_info(session, dataset.table_name)
    # fix(#1847): lock follows the ALTER — the reupload swap takes its
    # data-table ACCESS EXCLUSIVE before its catalog rows.
    await lock_catalog_rows_for_write(session, dataset)
    dataset.column_info = column_info

    # fix(#458): keep the cached sample-values snapshot keyed by the new
    # name; the builder reads this dict and an old-name entry looks like an
    # empty column after a rename.
    if dataset.sample_values and column_name in dataset.sample_values:
        samples = dict(dataset.sample_values)
        samples[new_name] = samples.pop(column_name)
        dataset.sample_values = samples

    # Migrate in place so attribute history follows the rename, not orphaned.
    result = await session.execute(
        select(AttributeMetadata).where(
            AttributeMetadata.dataset_id == dataset.id,
            AttributeMetadata.field_name == column_name,
            AttributeMetadata.is_current.is_(True),
        )
    )
    am = result.scalar_one_or_none()
    if am:
        am.field_name = new_name

    await session.flush()
    return column_info


async def alter_column_type(
    session: AsyncSession,
    dataset: Dataset,
    column_name: str,
    new_type: str,
) -> list[dict]:
    """Change a column's type on an existing layer's PostGIS table.

    Uses ``ALTER COLUMN ... TYPE ... USING column::TYPE`` so PostgreSQL applies
    the standard cast — incompatible existing values raise the underlying
    Postgres error and abort the transaction.
    """
    get_catalog_port().validate_table_name(dataset.table_name)

    if not COLUMN_NAME_RE.match(column_name):
        raise ValueError(f"Column name {column_name!r} is not a valid column name.")
    if column_name in RESERVED_COLUMNS:
        raise ValueError(
            f"Column {column_name!r} is reserved and its type cannot be altered."
        )
    if new_type not in ALLOWED_COLUMN_TYPES:
        raise ValueError(
            f"Column type {new_type!r} is not allowed. "
            f"Allowed types: {sorted(ALLOWED_COLUMN_TYPES.keys())}"
        )

    existing = {c["name"]: c for c in (dataset.column_info or [])}
    if column_name not in existing:
        raise ValueError(f"Column {column_name!r} does not exist on this layer.")

    pg_type = ALLOWED_COLUMN_TYPES[new_type]
    table_ref = get_catalog_port().quote_table(dataset.table_name)
    ddl = (
        f"ALTER TABLE {table_ref} ALTER COLUMN {_qcol(column_name)} TYPE {pg_type} "
        f"USING {_qcol(column_name)}::{pg_type}"
    )
    await session.execute(text(ddl))

    column_info = await get_catalog_port().get_column_info(session, dataset.table_name)
    # fix(#1847): scan, then lock, then assign — the scan needs neither
    # catalog row, and the lock must follow the ALTER since the reupload swap
    # takes its data-table ACCESS EXCLUSIVE before its catalog rows.
    quality_detail = await _compute_quality_detail(session, dataset, column_info)
    await lock_catalog_rows_for_write(session, dataset)
    dataset.column_info = column_info
    dataset.quality_detail = quality_detail

    # Refresh AttributeMetadata.data_type so quality metrics + UI labels match.
    result = await session.execute(
        select(AttributeMetadata).where(
            AttributeMetadata.dataset_id == dataset.id,
            AttributeMetadata.field_name == column_name,
            AttributeMetadata.is_current.is_(True),
        )
    )
    am = result.scalar_one_or_none()
    if am:
        new_col = next((c for c in column_info if c["name"] == column_name), None)
        if new_col:
            am.data_type = new_col.get("type", am.data_type)
            am.domain_type = get_catalog_port().infer_domain_type(am.data_type)

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
    get_catalog_port().validate_table_name(dataset.table_name)

    if not COLUMN_NAME_RE.match(column_name):
        raise ValueError(f"Column name {column_name!r} is not a valid column name.")

    if column_name in RESERVED_COLUMNS:
        raise ValueError(f"Column {column_name!r} is reserved and cannot be removed.")

    existing_names = {c["name"] for c in (dataset.column_info or [])}
    if column_name not in existing_names:
        raise ValueError(f"Column {column_name!r} does not exist on this layer.")

    table_ref = get_catalog_port().quote_table(dataset.table_name)
    ddl = f"ALTER TABLE {table_ref} DROP COLUMN {_qcol(column_name)}"
    await session.execute(text(ddl))

    column_info = await get_catalog_port().get_column_info(session, dataset.table_name)
    # fix(#1847): scan, then lock, then assign — the scan needs neither
    # catalog row, and the lock must follow the ALTER since the reupload swap
    # takes its data-table ACCESS EXCLUSIVE before its catalog rows.
    quality_detail = await _compute_quality_detail(session, dataset, column_info)
    await lock_catalog_rows_for_write(session, dataset)
    dataset.column_info = column_info
    dataset.quality_detail = quality_detail

    # fix(#458): drop the removed column's cached sample values too.
    if dataset.sample_values and column_name in dataset.sample_values:
        samples = dict(dataset.sample_values)
        samples.pop(column_name)
        dataset.sample_values = samples

    # fix(#458): filter on is_current like rename/alter do — a
    # drop→re-add→drop of the same name leaves historical rows, and an
    # unfiltered scalar_one_or_none() raised MultipleResultsFound (500).
    result = await session.execute(
        select(AttributeMetadata).where(
            AttributeMetadata.dataset_id == dataset.id,
            AttributeMetadata.field_name == column_name,
            AttributeMetadata.is_current.is_(True),
        )
    )
    am = result.scalar_one_or_none()
    if am:
        am.is_current = False

    await session.flush()

    return column_info
