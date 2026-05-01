"""Dataset metadata + attribute operations (extracted from service.py — Phase 224)."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.schemas import DatasetMeta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
)

logger = structlog.stdlib.get_logger(__name__)


__all__ = [
    "compute_schema_diff",
    "get_attribute",
    "list_attributes",
    "reset_attribute",
    "update_attribute",
    "update_auto_metadata",
    "update_user_metadata",
]


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
    # Function-local import to avoid circular import: service.py imports from
    # this module (re-export shim) at module top, so we cannot reciprocally
    # import from service.py at module top. Matches the pattern established
    # in service_relationships.py (Phase 224-02).
    from app.modules.catalog.datasets.domain.service import get_dataset

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
    # Function-local import to break circular dependency (see update_user_metadata).
    from app.modules.catalog.datasets.domain.service import get_dataset

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
