"""Dataset metadata + attribute operations (extracted from service.py — Phase 224)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.core.identity import Identity
    from app.modules.catalog.datasets.domain.schemas import DatasetMeta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain._sql_safety import SAFE_TABLE_NAME_RE
from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    RecordTranslation,
)
from app.modules.catalog.datasets.domain.service_query import get_dataset
from app.platform.extensions import get_catalog_port, get_workflow_extension
from app.platform.extensions.protocols import WorkflowTransitionContext

logger = structlog.stdlib.get_logger(__name__)


__all__ = [
    "compute_schema_diff",
    "get_attribute",
    "list_attributes",
    "reset_attribute",
    "update_attribute",
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
        # fix(#1746 B2b review r24): `None` on either side is UNKNOWN, not
        # zero. Coercing it invented a delta the size of whichever count was
        # known, and the case that reaches this most often is a service preview
        # whose collection size the service never published. An unknown
        # difference is reported as unknown.
        "row_count_delta": (
            None
            if old_feature_count is None or new_feature_count is None
            else new_feature_count - old_feature_count
        ),
    }


# Field maps for the simple-assignment portion of update_user_metadata.
# Defined at module scope so they aren't rebuilt per call (and so
# _apply_simple_field_assignments can read them without parameters).
_RECORD_FIELD_MAP: dict[str, str] = {
    "title": "title",
    "summary": "summary",
    "license": "license",
    "attribution": "attribution",
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


# Never clearable to NULL via the PATCH: records.title is NOT NULL.
_NON_CLEARABLE_FIELDS = {"title"}


def _apply_simple_field_assignments(
    record: Any, dataset: Dataset, meta: "DatasetMeta"
) -> bool:
    """Apply scalar fields present in the request body, including explicit
    nulls — fix(#458 E-04): clears were silently dropped before. Absent fields
    keep PATCH semantics; _NON_CLEARABLE_FIELDS (title, NOT NULL) drop nulls."""
    mutated = False
    targets = ((record, _RECORD_FIELD_MAP), (dataset, _DATASET_FIELD_MAP))
    for target, field_map in targets:
        for meta_field, attr in field_map.items():
            if meta_field not in meta.model_fields_set:
                continue
            value = getattr(meta, meta_field)
            if value is None and meta_field in _NON_CLEARABLE_FIELDS:
                continue
            setattr(target, attr, value)
            mutated = True
    return mutated


def _apply_tile_columns(dataset: Dataset, meta: "DatasetMeta") -> bool:
    """Persist the vector-tile attribute allowlist, including explicit null clears."""
    if "tile_columns" not in meta.model_fields_set:
        return False
    if dataset.tile_columns == meta.tile_columns:
        return False
    dataset.tile_columns = meta.tile_columns
    return True


async def _apply_visibility_change(
    session: AsyncSession,
    record: Any,
    dataset_id: uuid.UUID,
    new_visibility: str,
) -> bool:
    """Set record.visibility, blocking a change that would strand a shared map.

    fix(#931): the gate used to be ``new != public and old == public``, matching
    a query that only knew about public maps. An internal map using the dataset
    was invisible to both, so the flip succeeded and every signed-in viewer of
    that map silently lost the layer. The helper now compares the before and
    after audiences itself and returns nothing when the change strands nothing,
    so no gate is needed here.
    """
    from app.modules.catalog.maps.service import (
        find_maps_broken_by_dataset_visibility,
    )

    broken_maps = await find_maps_broken_by_dataset_visibility(
        session,
        dataset_id,
        old_visibility=record.visibility,
        new_visibility=new_visibility,
        record_status=record.record_status,
        record_id=record.id,
        owner_id=record.created_by,
    )
    if broken_maps:
        raise ValueError(
            "Cannot restrict visibility: dataset is used in shared maps: "
            f"{', '.join(broken_maps)}"
        )
    record.visibility = new_visibility
    return True


async def _apply_record_status_change(
    session: AsyncSession,
    record: Any,
    dataset: Dataset,
    new_status: str,
    actor: "Identity | None" = None,
) -> bool:
    """Set record.record_status; on transition TO published, validate metadata."""
    current_status = record.record_status
    if new_status == current_status:
        record.record_status = new_status
        return True

    workflow = get_workflow_extension()
    context = WorkflowTransitionContext(
        session=session,
        dataset=dataset,
        actor=actor,
        from_status=current_status,
        to_status=new_status,
        mode="metadata_patch",
    )
    allowed = await workflow.allowed_transitions(context)
    if new_status not in allowed:
        raise ValueError(
            f"Cannot transition from '{current_status}' to '{new_status}'. "
            f"Allowed: {allowed}"
        )

    if new_status == "published" and current_status != "published":
        from app.core.persistent_config import REQUIRE_METADATA_FOR_PUBLISH

        require_metadata = await REQUIRE_METADATA_FOR_PUBLISH.get(session)
        if require_metadata:
            from app.modules.catalog.validation.service import validate_record

            result = await validate_record(session, record, dataset)
            if not result.is_valid:
                error_msgs = [f"{e.field}: {e.message}" for e in result.errors]
                raise ValueError(f"Cannot publish: {'; '.join(error_msgs)}")
        record.published_at = func.now()
    record.record_status = new_status
    await workflow.on_transition(context)
    return True


async def _apply_is_dem(
    session: AsyncSession, dataset_id: uuid.UUID, is_dem: bool
) -> bool:
    """Set is_dem on the dataset's RasterAsset row, if one exists."""
    ra = await get_catalog_port().get_raster_asset(session, dataset_id)
    if ra is None:
        return False
    ra.is_dem = is_dem
    return True


async def _maybe_defer_embedding(record_id: uuid.UUID, dataset_id: uuid.UUID) -> None:
    """Best-effort defer of embedding regeneration. Failures are logged, not raised."""
    try:
        await get_catalog_port().defer_embed_record(record_id)
    except (
        Exception
    ):  # broad: defer is non-fatal; embedding will catch up on next edit or backfill
        # Non-fatal -- embedding will catch up on next edit or backfill.
        # Log with traceback so operators can notice if this fails consistently
        # (e.g., broker down) instead of silently dropping edits from the index.
        logger.warning(
            "Failed to defer embed_record task for record %s (dataset %s)",
            record_id,
            dataset_id,
            exc_info=True,
        )


async def update_user_metadata(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    meta: "DatasetMeta",
    *,
    actor_id: uuid.UUID | None = None,
    actor: "Identity | None" = None,
    warnings_out: list[str] | None = None,
) -> Dataset:
    """Update user-editable fields including extended metadata.

    Accepts a DatasetMeta Pydantic model. Only updates fields that are
    explicitly set (not None). Raises ValueError if dataset not found.
    Does not commit; caller controls transaction scope.

    ``warnings_out``, when provided, collects advisory (non-blocking) warnings
    for the caller to surface — currently the inherited-keyword disclosure
    check below (feat #1070).

    Decomposed into 5 step helpers for readability:
    simple field assignments, visibility, record_status, is_dem, embedding-defer.
    """
    dataset = await get_dataset(session, dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id} not found.")

    from app.modules.catalog.features.service import lock_catalog_rows_for_write

    record = dataset.record

    # fix(#1847 review r2): BEFORE the first assignment below. This function
    # writes record fields (title, visibility, record_status, updated_by) and
    # dataset fields (quality_statement, source_url, tile_columns) and then
    # flushes them together, so without this the flush took catalog.records
    # ahead of catalog.datasets and deadlocked against any writer holding the
    # dataset row. See app.platform.catalog_locks.lock_catalog_rows.
    await lock_catalog_rows_for_write(session, dataset)

    if "language" in meta.model_fields_set:
        effective_language = meta.language or "en"
        collision = await session.scalar(
            select(RecordTranslation.id).where(
                RecordTranslation.record_id == record.id,
                func.lower(RecordTranslation.language) == effective_language.casefold(),
            )
        )
        if collision is not None:
            raise ValueError(
                "Primary language duplicates an existing record translation"
            )

    mutated_flags = [
        _apply_simple_field_assignments(record, dataset, meta),
        _apply_tile_columns(dataset, meta),
    ]

    if meta.visibility is not None:
        mutated_flags.append(
            await _apply_visibility_change(session, record, dataset_id, meta.visibility)
        )
    if meta.record_status is not None:
        mutated_flags.append(
            await _apply_record_status_change(
                session, record, dataset, meta.record_status, actor
            )
        )
    if meta.is_dem is not None:
        mutated_flags.append(await _apply_is_dem(session, dataset_id, meta.is_dem))

    # feat(#1070): after the visibility/record_status helpers resolve, ask —
    # of the RESOLVED state, so both widening axes route through this one
    # check — whether keywords inherited from the analysis source now reach
    # anyone who cannot open that source. Advisory, never blocking: exposure
    # requires the owner's deliberate act on metadata they can already edit,
    # so the owner is told, not stopped. fix(#1178 review): the check is a
    # shared helper because the publication-status endpoints write
    # record_status without coming through here — see its docstring for the
    # writer enumeration.
    if meta.visibility is not None or meta.record_status is not None:
        from app.modules.catalog.records.inherited import (
            inherited_keyword_disclosure_warning,
        )

        warning = await inherited_keyword_disclosure_warning(
            session, record, dataset_id, actor=actor
        )
        if warning is not None and warnings_out is not None:
            warnings_out.append(warning)

    if actor_id is not None and any(mutated_flags):
        record.updated_by = actor_id

    await session.flush()

    # Trigger embedding regeneration if relevant fields changed.
    # model_fields_set, not is-not-None: an explicit clear must also re-embed.
    if {"title", "summary", "lineage_summary"} & meta.model_fields_set:
        await _maybe_defer_embedding(record.id, dataset.id)

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
    attr = await get_attribute(session, attribute_id)
    if attr is None:
        raise ValueError("Attribute not found")

    # Re-compute inferred values
    port = get_catalog_port()
    attr.title = port.humanize_column_name(attr.field_name)
    attr.semantic_role = port.infer_semantic_role(attr.field_name, attr.data_type or "")
    attr.domain_type = port.infer_domain_type(attr.data_type or "")
    attr.units = port.infer_units(attr.field_name)
    attr.description = None
    attr.user_modified_fields = []

    # Re-sample example_values from data table. Default to None on every
    # rejected/error path so the inverted guards stay flat.
    attr.example_values = None
    col_name = attr.field_name

    if not attr.data_type or "geometry" in attr.data_type.lower():
        await session.flush()
        return attr

    if not (
        SAFE_TABLE_NAME_RE.match(col_name) and SAFE_TABLE_NAME_RE.match(table_name)
    ):
        await session.flush()
        return attr

    try:
        table_ref = port.quote_table(table_name)
        result = await session.execute(
            text(
                f"SELECT DISTINCT {col_name}::text AS val "
                f"FROM (SELECT {col_name} FROM {table_ref} "
                f"WHERE {col_name} IS NOT NULL LIMIT 1000) sub LIMIT 10"
            )
        )
        values = [row[0] for row in result.all() if row[0] is not None]
        attr.example_values = values if values else None
    except Exception:  # broad: example-value sampling is best-effort; any DB error degrades to no examples
        # Sampling is best-effort; don't fail the reset because we
        # couldn't gather example values, but do log so operators can
        # notice if this breaks consistently (RES-N9).
        logger.warning(
            "Failed to sample example_values for %s.%s",
            table_name,
            col_name,
            exc_info=True,
        )

    await session.flush()
    return attr
