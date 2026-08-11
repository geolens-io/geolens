"""Attribute metadata rows derived from a table's column list.

Split out of ``metadata.py`` (#1042). Name-and-type inference (title, units,
semantic role, domain type) plus the two writers that apply it: one for the
initial ingest, one for re-upload, which differ only in that the re-upload path
must leave user-edited fields alone.
"""

import re
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.core.processing_port import Attribute


def _humanize_column_name(field_name: str) -> str:
    """Convert column name to human-readable title.

    Examples:
        pop_2020 -> Pop 2020
        land_use_type -> Land Use Type
        AREA_SQ_KM -> Area Sq Km
        objectid -> Objectid
        camelCaseField -> Camel Case Field
    """
    # Replace underscores with spaces
    name = re.sub(r"_+", " ", field_name)
    # Split camelCase boundaries
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return name.strip().title()


_UNIT_SUFFIX_MAP = {
    "_m": "meters",
    "_ft": "feet",
    "_km": "kilometers",
    "_mi": "miles",
    "_sqm": "square meters",
    "_sqft": "square feet",
    "_sqkm": "square kilometers",
    "_ha": "hectares",
    "_ac": "acres",
    "_pct": "percent",
    "_deg": "degrees",
    "_rad": "radians",
    "_kg": "kilograms",
    "_lb": "pounds",
    "_l": "liters",
    "_gal": "gallons",
    "_s": "seconds",
    "_min": "minutes",
    "_hr": "hours",
}


def _infer_units(field_name: str) -> str | None:
    """Infer units from column name suffix."""
    lower = field_name.lower()
    # Check longer suffixes first to avoid false matches (e.g. _sqm before _m)
    for suffix, unit in sorted(_UNIT_SUFFIX_MAP.items(), key=lambda x: -len(x[0])):
        if lower.endswith(suffix):
            return unit
    return None


def _infer_semantic_role(field_name: str, data_type: str) -> str:
    """Infer semantic role from column name and PostgreSQL data type."""
    lower = field_name.lower()

    # Geometry detection
    if "geometry" in data_type.lower() or data_type == "USER-DEFINED":
        return "geometry"

    # Identifier patterns
    if lower in ("id", "fid", "objectid", "gid", "ogc_fid") or lower.endswith("_id"):
        return "identifier"

    # Temporal patterns
    if data_type in ("date", "timestamp without time zone", "timestamp with time zone"):
        return "temporal"
    if any(kw in lower for kw in ("date", "time", "year", "month", "day")):
        return "temporal"

    # Numeric -> measure
    if data_type in (
        "integer",
        "bigint",
        "smallint",
        "numeric",
        "double precision",
        "real",
    ):
        return "measure"

    # Label patterns
    if lower in ("name", "label", "title", "display_name"):
        return "label"

    # Text -> categorical
    if data_type in ("character varying", "text", "character"):
        return "categorical"

    return "other"


_PG_TYPE_TO_DOMAIN = {
    "integer": "discrete",
    "bigint": "discrete",
    "smallint": "discrete",
    "numeric": "continuous",
    "double precision": "continuous",
    "real": "continuous",
    "boolean": "boolean",
    "date": "temporal",
    "timestamp without time zone": "temporal",
    "timestamp with time zone": "temporal",
    "character varying": "categorical",
    "character": "categorical",
    "text": "text",
    "USER-DEFINED": "geometry",
    "ARRAY": "text",
    "jsonb": "text",
    "json": "text",
    "uuid": "categorical",
}


def _infer_domain_type(data_type: str) -> str:
    """Map PostgreSQL data_type to domain classification."""
    return _PG_TYPE_TO_DOMAIN.get(data_type, "text")


def _build_attribute_metadata(
    AttributeMetadata: type,
    dataset_id: uuid.UUID,
    col_name: str,
    col_type: str,
    *,
    sample_values: dict | None = None,
    ordinal_position: int | None = None,
    is_nullable: bool | None = None,
) -> "Attribute":
    """Factory for creating a new AttributeMetadata row with inferred fields.

    Shared by generate_attribute_metadata (initial ingest) and
    refresh_attribute_metadata (re-upload new columns). Callers resolve
    the AttributeMetadata ORM class once via the Port and pass it in so
    we don't re-do that lookup on every iteration of a per-column loop
    (Phase 225 review fix W-03).
    """
    example_vals = None
    if sample_values and col_name in sample_values:
        example_vals = sample_values[col_name]

    return AttributeMetadata(
        dataset_id=dataset_id,
        field_name=col_name,
        title=_humanize_column_name(col_name),
        data_type=col_type,
        units=_infer_units(col_name),
        semantic_role=_infer_semantic_role(col_name, col_type),
        domain_type=_infer_domain_type(col_type),
        example_values=example_vals,
        ordinal_position=ordinal_position,
        is_nullable=is_nullable,
        is_current=True,
    )


def _build_geometry_attribute_row(
    AttributeMetadata: type,
    dataset_id: uuid.UUID,
    geometry_type: str | None,
) -> "Attribute":
    """Factory for the special ``geom`` attribute metadata row.

    Callers pass the resolved ORM class to avoid redundant Port lookups
    in tight loops (Phase 225 review fix W-03).
    """
    return AttributeMetadata(
        dataset_id=dataset_id,
        field_name="geom",
        title="Geometry",
        data_type=geometry_type or "geometry",
        semantic_role="geometry",
        domain_type="geometry",
        example_values=None,
        is_current=True,
    )


async def generate_attribute_metadata(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    column_info: list[dict],
    *,
    geometry_type: str | None = None,
    sample_values: dict | None = None,
) -> list["Attribute"]:
    """Auto-populate attribute_metadata rows from column_info.

    Creates one row per column plus a geometry row if geometry_type is provided.
    Uses check-then-insert to be idempotent (skips existing field_names).
    Does NOT query the data table -- sample_values are passed in by the caller.
    """
    from app.platform.extensions import get_processing_port

    AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()

    # Load existing field names to skip duplicates
    result = await session.execute(
        select(AttributeMetadata.field_name).where(
            AttributeMetadata.dataset_id == dataset_id
        )
    )
    existing_fields = {row[0] for row in result.all()}

    created: list[AttributeMetadata] = []

    for col in column_info:
        field_name = col["name"]
        if field_name in existing_fields:
            continue

        am = _build_attribute_metadata(
            AttributeMetadata,
            dataset_id,
            field_name,
            col.get("type", ""),
            sample_values=sample_values,
            ordinal_position=col.get("ordinal_position"),
            is_nullable=col.get("is_nullable"),
        )
        session.add(am)
        created.append(am)
        existing_fields.add(field_name)

    # Geometry row
    if geometry_type is not None and "geom" not in existing_fields:
        am = _build_geometry_attribute_row(AttributeMetadata, dataset_id, geometry_type)
        session.add(am)
        created.append(am)

    if created:
        await session.flush()

    return created


async def refresh_attribute_metadata(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    column_info: list[dict],
    *,
    geometry_type: str | None = None,
    sample_values: dict | None = None,
) -> None:
    """Refresh attribute metadata on re-upload, preserving user edits.

    - Always refreshes system fields: data_type, example_values, ordinal_position,
      is_nullable. Sets is_current=True.
    - Per-field check: only refreshes title/semantic_role/domain_type/units/description
      if that specific field name is NOT in user_modified_fields.
    - New columns get auto-populated metadata.
    - Removed columns are marked is_current=False.
    """
    from app.platform.extensions import get_processing_port

    AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()

    # Load existing attribute rows keyed by field_name
    result = await session.execute(
        select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
    )
    existing: dict[str, AttributeMetadata] = {
        am.field_name: am for am in result.scalars().all()
    }

    current_field_names = {col["name"] for col in column_info}

    for col in column_info:
        field_name = col["name"]
        data_type = col.get("type", "")

        example_vals = None
        if sample_values and field_name in sample_values:
            example_vals = sample_values[field_name]

        if field_name in existing:
            am = existing[field_name]
            # Always refresh system fields
            am.data_type = data_type
            am.example_values = example_vals
            am.ordinal_position = col.get("ordinal_position")
            am.is_nullable = col.get("is_nullable")
            am.is_current = True

            # Per-field check for user-editable fields
            modified = set(am.user_modified_fields or [])
            if "title" not in modified:
                am.title = _humanize_column_name(field_name)
            if "semantic_role" not in modified:
                am.semantic_role = _infer_semantic_role(field_name, data_type)
            if "domain_type" not in modified:
                am.domain_type = _infer_domain_type(data_type)
            if "units" not in modified:
                am.units = _infer_units(field_name)
            if "description" not in modified:
                am.description = None  # No auto-inferred description
        else:
            # New column -- create fresh row via shared factory
            am = _build_attribute_metadata(
                AttributeMetadata,
                dataset_id,
                field_name,
                data_type,
                sample_values=sample_values,
                ordinal_position=col.get("ordinal_position"),
                is_nullable=col.get("is_nullable"),
            )
            session.add(am)

    # Handle geometry row
    if geometry_type is not None:
        if "geom" in existing:
            geom_am = existing["geom"]
            geom_am.data_type = geometry_type or "geometry"
            geom_am.is_current = True
            modified = set(geom_am.user_modified_fields or [])
            if "title" not in modified:
                geom_am.title = "Geometry"
            if "semantic_role" not in modified:
                geom_am.semantic_role = "geometry"
            if "domain_type" not in modified:
                geom_am.domain_type = "geometry"
        else:
            session.add(
                _build_geometry_attribute_row(
                    AttributeMetadata, dataset_id, geometry_type
                )
            )

    # Mark removed columns as is_current=False
    for field_name, am in existing.items():
        if field_name not in current_field_names and field_name != "geom":
            am.is_current = False

    await session.flush()
