"""Dataset creation paths: empty + materialized (extracted from service.py — Phase 224)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.schemas import CreateEmptyDatasetRequest

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.datasets.domain._sql_safety import (
    SAFE_COLUMN_NAME_RE,
    _safe_table_ref,
)
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
)
from app.modules.catalog.datasets.domain.service_relationships import (
    auto_detect_relationships,
)

__all__ = ["create_empty_dataset", "create_dataset"]


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
        if not SAFE_COLUMN_NAME_RE.match(col.name):
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
