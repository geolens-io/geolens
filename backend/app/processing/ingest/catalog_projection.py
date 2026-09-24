"""Catalog facts derived from a dataset's feature table.

``measure`` reads a table and writes nothing. ``project`` writes a measurement
onto the dataset and its record under catalog locks its caller already holds,
and returns the schema diff between the values it replaced and the measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, text, update

from app.core.record_types import capabilities

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.processing.ingest.tasks_staging import StagingResult

# What PostGIS records in ``geometry_columns.type`` for an untyped column. A
# specific value describes what the column will accept; this one says only
# that the table is spatial.
_GENERIC_GEOMETRY_TYPE = "GEOMETRY"


class ProjectionRefused(Exception):
    """The dataset's record type has no feature table to project onto."""


@dataclass(frozen=True, slots=True)
class Measurement:
    """What one read of a feature table establishes about its dataset."""

    # As extract_metadata returns it. Its geometry_type is the sampled one;
    # the field below is the type the catalog records.
    metadata: dict
    sample_values: dict
    # is_3d, n_dims, z_min and z_max, as detect_3d_metadata returns them.
    three_d: dict
    # Measured from a row, else declared by the column, else the stored value.
    geometry_type: str | None
    quality_detail: dict


async def measure(
    session: AsyncSession,
    dataset: Any,
    *,
    table: str,
    schema: str,
    staged: StagingResult | None = None,
) -> Measurement:
    """Measure ``table`` as ``dataset``'s feature table, writing nothing.

    ``staged`` supplies the metadata, samples and 3D facts the staging pipeline
    already read. Without it they are read here, and no ``elev`` column is added.
    """
    from app.processing.ingest.metadata import (
        detect_3d_metadata,
        extract_metadata,
        get_sample_values,
        score_quality,
    )

    if staged is not None:
        metadata = staged.metadata
        sample_values = staged.sample_values
        three_d = staged.three_d
    else:
        metadata = await extract_metadata(session, table, schema=schema)
        sample_values = await get_sample_values(
            session, table, metadata.get("column_info") or [], schema=schema
        )
        three_d = await detect_3d_metadata(session, table, schema=schema)

    geometry_type = _effective_geometry_type(
        measured=metadata.get("geometry_type"),
        declared=await _declared_geometry_type(session, schema=schema, table=table),
        stored=dataset.geometry_type,
    )
    quality_detail = await score_quality(
        session,
        table,
        metadata.get("column_info") or [],
        record=dataset.record,
        record_type=_record_type_for(dataset.record.record_type, geometry_type),
        geometry_type=geometry_type,
        srid=metadata.get("srid"),
        schema=schema,
    )
    return Measurement(
        metadata=metadata,
        sample_values=sample_values,
        three_d=three_d,
        geometry_type=geometry_type,
        quality_detail=quality_detail,
    )


def schema_diff(dataset: Any, measurement: Measurement) -> dict:
    """The dataset's stored columns and feature count against the measurement's."""
    from app.platform.extensions import get_processing_port

    return get_processing_port().compute_schema_diff(
        dataset.column_info or [],
        measurement.metadata.get("column_info") or [],
        dataset.feature_count,
        measurement.metadata.get("feature_count"),
    )


async def project(
    session: AsyncSession, dataset: Any, measurement: Measurement
) -> dict:
    """Write ``measurement`` onto ``dataset`` and its record; return the schema diff.

    The caller holds the job row and the catalog rows, in the order
    ``lock_catalog_rows`` takes them. The diff compares the measurement with the
    stored values it replaces, read under that lock. A record type without a
    feature table is refused before anything is written.
    """
    current_type = dataset.record.record_type
    if not capabilities(current_type).feature_table:
        raise ProjectionRefused(
            f"A {current_type!r} dataset has no feature table to derive its "
            "catalog entry from."
        )

    from app.platform.extensions import get_processing_port
    from app.processing.ingest.metadata import refresh_attribute_metadata

    await session.refresh(dataset, ["column_info", "feature_count", "geometry_type"])
    diff = schema_diff(dataset, measurement)
    was_spatial = dataset.geometry_type is not None

    metadata = measurement.metadata
    geometry_type = measurement.geometry_type
    column_info = metadata.get("column_info") or []
    extent_wkt = metadata.get("extent_wkt")
    dataset.srid = metadata.get("srid")
    dataset.geometry_type = geometry_type
    dataset.record.record_type = _record_type_for(current_type, geometry_type)
    dataset.feature_count = metadata.get("feature_count")
    dataset.record.spatial_extent = (
        None if extent_wkt is None else func.ST_GeomFromText(extent_wkt, 4326)
    )
    dataset.column_info = column_info
    dataset.sample_values = measurement.sample_values
    dataset.is_3d = measurement.three_d.get("is_3d")
    dataset.n_dims = measurement.three_d.get("n_dims")
    dataset.z_min = measurement.three_d.get("z_min")
    dataset.z_max = measurement.three_d.get("z_max")
    dataset.quality_detail = measurement.quality_detail

    await refresh_attribute_metadata(
        session,
        dataset.id,
        column_info,
        geometry_type=geometry_type,
        sample_values=measurement.sample_values,
    )
    await _retire_geometry_attribute_row(
        session, dataset.id, geometry_type=geometry_type
    )
    # Reconciling also normalizes is_primary, so it runs on a modality flip only.
    if was_spatial != (geometry_type is not None):
        await get_processing_port().reconcile_distributions(
            session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type=geometry_type,
        )
    return diff


def _record_type_for(current: str | None, geometry_type: str | None) -> str | None:
    """``current``, or the type the geometry implies when ``current`` follows it."""
    if not capabilities(current).geometry_derived:
        return current
    return "table" if geometry_type is None else "vector_dataset"


async def _declared_geometry_type(
    session: AsyncSession, *, schema: str, table: str
) -> str | None:
    """The type the ``geom`` column is declared as; None when there is no column.

    Unlike a sampled row, the declaration still answers for an empty table.
    """
    return await session.scalar(
        text(
            "SELECT type FROM geometry_columns "
            "WHERE f_table_schema = :schema AND f_table_name = :table "
            "AND f_geometry_column = 'geom'"
        ),
        {"schema": schema, "table": table},
    )


def _effective_geometry_type(
    *, measured: str | None, declared: str | None, stored: str | None
) -> str | None:
    """The geometry type the best evidence supports.

    A sampled row wins, then a specific declared type. An empty generic column
    keeps the stored type, or reports the generic type when none is stored, so
    a table with a geometry column always counts as spatial.
    """
    if measured is not None:
        return measured
    if declared is None:
        return None
    if declared != _GENERIC_GEOMETRY_TYPE:
        return declared
    return stored if stored is not None else _GENERIC_GEOMETRY_TYPE


async def _retire_geometry_attribute_row(
    session: AsyncSession, dataset_id: uuid.UUID, *, geometry_type: str | None
) -> None:
    """Mark the synthetic ``geom`` attribute row not current once geometry is gone.

    ``refresh_attribute_metadata`` skips that row without a geometry type, and
    its removed-column sweep excludes it by name.
    """
    if geometry_type is not None:
        return

    from app.platform.extensions import get_processing_port

    AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()
    await session.execute(
        update(AttributeMetadata)
        .where(
            AttributeMetadata.dataset_id == dataset_id,
            AttributeMetadata.field_name == "geom",
        )
        .values(is_current=False)
    )
