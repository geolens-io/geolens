"""Dataset creation paths for empty and materialized datasets."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.schemas import CreateEmptyDatasetRequest

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema, tenant_reader_role
from app.core.db.tenant_session import current_tenant_var
from app.core.identity import Identity
from app.modules.catalog.datasets.domain._sql_safety import (
    SAFE_COLUMN_NAME_RE,
    _safe_table_ref,
)
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
)
from app.modules.catalog.datasets.domain.schemas import IngestionResult
from app.modules.catalog.features.service import is_writable_feature_column
from app.modules.catalog.datasets.domain.service_relationships import (
    auto_detect_relationships,
)
from app.platform.extensions import get_catalog_port

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
    seen_names: set[str] = set()
    for col in request.columns:
        lower_name = col.name.lower()
        if not SAFE_COLUMN_NAME_RE.match(col.name):
            raise ValueError(
                f"Invalid column name: {col.name!r}. "
                "Must start with a letter or underscore and contain only alphanumeric characters and underscores."
            )
        # fix(#1778): SAFE_COLUMN_NAME_RE allows a leading underscore and no
        # length bound, but the feature write path can address neither: a
        # column like `_notes` was created but silently dropped every write,
        # and a name over 63 chars gets truncated by Postgres DDL while
        # column_info keeps the full string. Refuse at creation instead.
        if not is_writable_feature_column(lower_name):
            raise ValueError(
                f"Invalid column name: {col.name!r}. "
                "A column name is at most 63 characters, starts with a letter, "
                "and holds only letters, digits and underscores."
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

    table_name, _collision_warning = await get_catalog_port().generate_table_name(
        request.title, session
    )
    tenant_id = current_tenant_var.get()
    data_schema = tenant_data_schema(tenant_id)
    reader_role = tenant_reader_role(tenant_id)

    col_defs = []
    for col in request.columns:
        pg_type = _TYPE_MAP[col.type]
        col_defs.append(f"{col.name.lower()} {pg_type}")

    columns_sql = ", ".join(col_defs)
    create_sql = (
        f"CREATE TABLE {_safe_table_ref(table_name, schema=data_schema)} ("
        f"gid SERIAL PRIMARY KEY, "
        f"geom geometry(Geometry, 4326), "
        f"geom_4326 geometry(Geometry, 4326), "
        f"{columns_sql}"
        f")"
    )
    await session.execute(text(create_sql))

    await get_catalog_port().grant_reader_access(
        session,
        table_name,
        schema=data_schema,
        role=reader_role,
    )

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

    dataset = await create_dataset(
        session,
        table_name,
        request.title,
        user.id,
        column_info=column_info,
        source_format="created",
        srid=4326,
        # fix(#430): the table column is generic geometry(Geometry, 4326); storing
        # POINT here rejected Polygon/LineString inserts the column accepts.
        geometry_type="GEOMETRY",
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
    visibility: str = "private",
    record_status: str = "published",
    ingestion: IngestionResult | None = None,
    # Legacy kwargs, kept for call sites that still pass ingestion fields
    # directly. New call sites should use `ingestion=IngestionResult(...)`.
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
) -> Dataset:
    """Create a record + dataset pair from ingestion results.

    Creates a Record first (shared metadata), then a Dataset linked via
    record_id. If ``ingestion.extent_wkt`` is provided, converts it to a
    PostGIS Geometry. Pass ``ingestion=None`` for ad-hoc creations like
    empty layers -- the dataset is created with all ingestion fields None.
    """
    if ingestion is None:
        ing = IngestionResult(
            srid=srid,
            geometry_type=geometry_type,
            feature_count=feature_count,
            extent_wkt=extent_wkt,
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
    else:
        ing = ingestion

    spatial_extent_value = None
    # fix(#934): an antimeridian-crossing source produces a two-ring
    # MULTIPOLYGON extent; accepting only POLYGON here silently nulled
    # Record.spatial_extent on first ingest. Both satisfy
    # chk_records_spatial_extent_type.
    if ing.extent_wkt and ing.extent_wkt.startswith(("POLYGON", "MULTIPOLYGON")):
        spatial_extent_value = func.ST_GeomFromText(ing.extent_wkt, 4326)

    record_type = "table" if ing.geometry_type is None else "vector_dataset"

    # fix(#302): authoritative count-cap check at the point the Record row is
    # created — the upload-time check_upload_quota cannot be atomic because
    # this row only comes to exist here, after the pre-check passed.
    from app.modules.quota.service import reserve_dataset_slot

    await reserve_dataset_slot(session, created_by)

    record = Record(
        title=title,
        summary=summary,
        visibility=visibility,
        record_status=record_status,
        record_type=record_type,
        spatial_extent=spatial_extent_value,
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        # fix(#1218): first ingest IS the first successful materialization,
        # so stamp it here rather than leaving every dataset reporting null.
        #
        # A Python datetime, NOT func.now(): a SQL expression leaves the
        # attribute EXPIRED after flush, so the next read issues a lazy
        # SELECT that explodes once the session is closed, exactly where
        # dataset_to_response reads it. Every stamping site does the same.
        last_refreshed_at=datetime.now(timezone.utc),
        srid=ing.srid,
        geometry_type=ing.geometry_type,
        feature_count=ing.feature_count,
        column_info=ing.column_info,
        sample_values=ing.sample_values,
        source_format=ing.source_format,
        source_filename=ing.source_filename,
        original_srid=ing.original_srid,
        source_url=ing.source_url,
        is_3d=ing.is_3d,
        n_dims=ing.n_dims,
        z_min=ing.z_min,
        z_max=ing.z_max,
    )
    session.add(dataset)
    await session.flush()

    await session.refresh(dataset, ["record"])

    # Standard distribution records: 6 for spatial, 2 for non-spatial.
    # dataset.id is the Dataset PK (URL paths); record.id is the Record PK
    # (FK in record_distributions).
    from app.modules.catalog.records.service import generate_distributions

    await generate_distributions(
        session, dataset.id, record.id, table_name, geometry_type=ing.geometry_type
    )

    if ing.column_info:
        await get_catalog_port().generate_attribute_metadata(
            session,
            dataset.id,
            ing.column_info,
            geometry_type=ing.geometry_type,
            sample_values=ing.sample_values,
        )

    if ing.column_info:
        await auto_detect_relationships(session, dataset.id, record.id, ing.column_info)

    # fix(#1230): dataset.create was invisible in the audit trail -- emitted
    # here, not per-router, so every creation path funnels through one
    # emit site instead of risking a missed call at each call site.
    # No ip_address: a domain-layer function with no Request, matching the
    # reupload.commit precedent (tasks_common.py).
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — preserved per D-17

    await audit_emit(
        session,
        AuditEvent(
            user_id=created_by,
            action="dataset.create",
            resource_type="dataset",
            resource_id=dataset.id,
            details={"title": title, "source_format": ing.source_format},
        ),
    )

    return dataset
