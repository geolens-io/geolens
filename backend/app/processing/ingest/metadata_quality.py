"""Dataset quality scoring.

Split out of ``metadata.py`` (#1042). Four weighted dimensions over a landed
table and its record. Every database-backed dimension degrades to a passing
score on any error: the score is descriptive, and a failure to compute it must
never fail the ingest that produced the data.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ingest.metadata_sql import (
    _qtable,
    _sql_quote_ident,
    _validate_table_name,
)

if TYPE_CHECKING:
    from app.core.processing_port import Dataset, Record


async def _score_metadata_completeness(
    session: AsyncSession,
    record: "Record",
) -> float:
    """Percentage of optional metadata fields that are populated (0-100)."""
    from app.platform.extensions import get_processing_port

    port = get_processing_port()
    kw_count = await port.get_record_keyword_count(session, record.id)
    has_keywords = True if kw_count and kw_count > 0 else None

    optional_fields = [
        record.summary,
        has_keywords,
        record.license,
        record.source_organization,
        record.temporal_start,
        record.lineage_summary,
        record.update_frequency,
        record.usage_constraints,
        record.access_constraints,
        record.theme_category if record.theme_category else None,
    ]
    filled = sum(1 for f in optional_fields if f is not None)
    return round(filled / len(optional_fields) * 100, 1)


def _score_crs(srid: int | None, geometry_type: str | None) -> float:
    """100 if SRID is defined or dataset has no geometry, else 0."""
    return 100.0 if (srid is not None or geometry_type is None) else 0.0


async def _score_geometry_validity(
    session: AsyncSession,
    table_name: str,
    has_geometry: bool,
    max_rows: int,
    *,
    schema: str = "data",
) -> float:
    """Percentage of valid geometries (0-100). Degrades to 100 on error."""
    if not has_geometry:
        return 100.0
    try:
        async with session.begin_nested():
            result = await session.execute(
                text(
                    f"SELECT COUNT(*) FILTER (WHERE ST_IsValid(geom)) * 100.0 / NULLIF(COUNT(*), 0) "
                    f"FROM (SELECT geom FROM "
                    f"{_qtable(table_name, schema=schema)} LIMIT :max_rows) sub"
                ).bindparams(max_rows=max_rows)
            )
            val = result.scalar_one_or_none()
            if val is not None:
                return round(float(val), 1)
    except (
        Exception
    ):  # broad: ST_IsValid quality score is non-fatal; degrade to 100.0 on any DB error
        pass
    return 100.0


async def _score_attribute_completeness(
    session: AsyncSession,
    table_name: str,
    column_info: list[dict],
    *,
    schema: str = "data",
) -> float:
    """Average non-null percentage across non-geometry columns (0-100)."""
    non_geom_cols = [
        c
        for c in column_info
        if "geometry" not in c.get("type", "").lower() and c.get("name")
    ]
    if not non_geom_cols:
        return 100.0
    col_exprs = ", ".join(
        f"COUNT({_sql_quote_ident(col['name'])}) "
        f'* 100.0 / NULLIF(COUNT(*), 0) AS "s_{i}"'
        for i, col in enumerate(non_geom_cols)
    )
    try:
        async with session.begin_nested():
            result = await session.execute(
                text(f"SELECT {col_exprs} FROM {_qtable(table_name, schema=schema)}")
            )
            row = result.one_or_none()
            if row is not None:
                col_scores: list[float] = [float(v) for v in row if v is not None]
                if col_scores:
                    return round(sum(col_scores) / len(col_scores), 1)
    except Exception:  # broad: attribute completeness score is non-fatal; degrade to 100.0 on any DB error
        pass
    return 100.0


async def compute_quality_score(
    session: AsyncSession,
    table_name: str,
    column_info: list[dict],
    dataset: "Dataset",
    max_validity_rows: int = 10000,
    *,
    schema: str = "data",
) -> dict:
    """:func:`score_quality` for ``dataset`` as it is stored."""
    return await score_quality(
        session,
        table_name,
        column_info,
        record=dataset.record,
        record_type=getattr(dataset.record, "record_type", None),
        geometry_type=dataset.geometry_type,
        srid=dataset.srid,
        max_validity_rows=max_validity_rows,
        schema=schema,
    )


async def score_quality(
    session: AsyncSession,
    table_name: str,
    column_info: list[dict],
    *,
    record: "Record",
    record_type: str | None,
    geometry_type: str | None,
    srid: int | None,
    max_validity_rows: int = 10000,
    schema: str = "data",
) -> dict:
    """Compute a weighted quality score for a table and the record describing it.

    Dimensions:
    - Metadata completeness (30%): non-empty optional fields on the record
    - Geometry validity (30%): percentage of valid geometries
    - Attribute completeness (25%): average non-null percentage across columns
    - CRS defined (15%): 100 if srid is set, else 0

    ``record_type``, ``geometry_type`` and ``srid`` are arguments so a
    measurement can be scored before it is written. Returns a dict with the
    overall score and the per-dimension scores. A 3D Tiles dataset is scored on
    its metadata alone: its ``table_name`` names no table.
    """
    _validate_table_name(table_name)
    has_geometry = geometry_type is not None

    metadata_score = await _score_metadata_completeness(session, record)
    if record_type == "tiles3d_dataset":
        return {
            "overall": round(metadata_score),
            "metadata_completeness": metadata_score,
            "geometry_validity": None,
            "attribute_completeness": None,
            "crs_defined": None,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
    crs_score = _score_crs(srid, geometry_type)
    geometry_score = await _score_geometry_validity(
        session,
        table_name,
        has_geometry,
        max_validity_rows,
        schema=schema,
    )
    attribute_score = await _score_attribute_completeness(
        session,
        table_name,
        column_info,
        schema=schema,
    )

    # Table records have no geometry_validity/crs_defined; re-normalize
    # weights to metadata (30) + attribute (25) = 55 total.
    if record_type == "table":
        overall = round(metadata_score * (30 / 55) + attribute_score * (25 / 55))
        return {
            "overall": overall,
            "metadata_completeness": metadata_score,
            "attribute_completeness": attribute_score,
            "geometry_validity": None,
            "crs_defined": None,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    overall = round(
        metadata_score * 0.30
        + geometry_score * 0.30
        + attribute_score * 0.25
        + crs_score * 0.15
    )

    return {
        "overall": overall,
        "metadata_completeness": metadata_score,
        "geometry_validity": geometry_score,
        "attribute_completeness": attribute_score,
        "crs_defined": crs_score,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
