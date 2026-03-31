"""PostGIS metadata extraction functions.

All functions take an AsyncSession and a table name. Table names are validated
against a strict pattern to prevent SQL injection (they are identifiers, not
parameterizable values).
"""

import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.datasets.models import AttributeMetadata

logger = structlog.stdlib.get_logger(__name__)

_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _validate_table_name(table_name: str) -> None:
    """Validate table name matches safe identifier pattern."""
    if not _TABLE_NAME_RE.match(table_name):
        raise ValueError(
            f"Invalid table name: {table_name!r}. "
            "Must contain only lowercase letters, digits, and underscores."
        )


def _qtable(table_name: str) -> str:
    """Return quoted 'data.table_name' identifier after validation."""
    _validate_table_name(table_name)
    return f'"data"."{table_name}"'


async def construct_point_geometry(
    session: AsyncSession,
    table_name: str,
    x_column: str,
    y_column: str,
    srid: int = 4326,
) -> int:
    """Add geometry column from x/y coordinate columns.

    Returns count of rows with valid geometry.
    """
    _validate_table_name(table_name)
    if not _TABLE_NAME_RE.match(x_column) or not _TABLE_NAME_RE.match(y_column):
        raise ValueError("Invalid column name")

    await session.execute(
        text(f"ALTER TABLE data.{table_name} ADD COLUMN geom geometry(Point, {srid})")
    )
    result = await session.execute(
        text(
            f"UPDATE data.{table_name} SET geom = ST_SetSRID("
            f"  ST_MakePoint({x_column}::double precision, {y_column}::double precision), "
            f"  {srid}) "
            f"WHERE {x_column} IS NOT NULL AND {y_column} IS NOT NULL"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX idx_{table_name}_geom ON data.{table_name} USING GIST (geom)"
        )
    )
    return result.rowcount


async def construct_wkt_geometry(
    session: AsyncSession,
    table_name: str,
    wkt_column: str,
    srid: int = 4326,
) -> int:
    """Add geometry column from a WKT text column.

    Returns count of rows with valid geometry.
    """
    _validate_table_name(table_name)
    if not _TABLE_NAME_RE.match(wkt_column):
        raise ValueError("Invalid column name")

    # Detect geometry type from sample row
    sample = await session.execute(
        text(
            f"SELECT GeometryType(ST_GeomFromText({wkt_column}, {srid})) "
            f"FROM data.{table_name} WHERE {wkt_column} IS NOT NULL LIMIT 1"
        )
    )
    geom_type = sample.scalar_one_or_none() or "GEOMETRY"

    await session.execute(
        text(
            f"ALTER TABLE data.{table_name} ADD COLUMN geom geometry({geom_type}, {srid})"
        )
    )
    result = await session.execute(
        text(
            f"UPDATE data.{table_name} SET geom = ST_GeomFromText({wkt_column}, {srid}) "
            f"WHERE {wkt_column} IS NOT NULL"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX idx_{table_name}_geom ON data.{table_name} USING GIST (geom)"
        )
    )
    return result.rowcount


async def get_table_srid(session: AsyncSession, table_name: str) -> int | None:
    """Get the SRID of the geom column for a table in the data schema."""
    _validate_table_name(table_name)
    result = await session.execute(
        text("SELECT Find_SRID('data', :table_name, 'geom')").bindparams(
            table_name=table_name
        )
    )
    row = result.scalar_one_or_none()
    return int(row) if row is not None else None


async def get_geometry_type(session: AsyncSession, table_name: str) -> str | None:
    """Get the geometry type of the first feature in the table.

    Returns the type in uppercase for consistent casing across all sources.
    """
    result = await session.execute(
        text(f"SELECT GeometryType(geom) FROM {_qtable(table_name)} LIMIT 1")
    )
    value = result.scalar_one_or_none()
    return value.upper() if value else None


async def get_feature_count(session: AsyncSession, table_name: str) -> int:
    """Count the number of features (rows) in the table."""
    result = await session.execute(text(f"SELECT COUNT(*) FROM {_qtable(table_name)}"))
    return result.scalar_one()


async def get_extent(session: AsyncSession, table_name: str) -> str | None:
    """Get the 4326 bbox extent as POLYGON WKT (or None for empty tables)."""
    _validate_table_name(table_name)
    result = await session.execute(
        text(
            f"SELECT CASE "
            f"  WHEN ext IS NULL THEN NULL "
            f"  ELSE ST_AsText(ST_SetSRID(ext::geometry, 4326)) "
            f"END "
            f"FROM (SELECT ST_Extent(geom_4326) AS ext FROM data.{table_name}) s"
        )
    )
    return result.scalar_one_or_none()


async def get_column_info(session: AsyncSession, table_name: str) -> list[dict]:
    """Get column names, types, ordinal position, and nullability.

    Excludes internal columns (gid, geom, geom_4326).
    Returns list of dicts with keys: name, type, ordinal_position, is_nullable.
    """
    _validate_table_name(table_name)
    result = await session.execute(
        text(
            "SELECT column_name, data_type, ordinal_position, "
            "       (is_nullable = 'YES') AS is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :table_name "
            "ORDER BY ordinal_position"
        ).bindparams(table_name=table_name)
    )
    excluded = {"gid", "geom", "geom_4326"}
    return [
        {
            "name": row[0],
            "type": row[1],
            "ordinal_position": row[2],
            "is_nullable": row[3],
        }
        for row in result.all()
        if row[0] not in excluded
    ]


async def get_sample_values(
    session: AsyncSession,
    table_name: str,
    column_info: list[dict],
    sample_size: int = 1000,
) -> dict:
    """Extract distinct sample values per column from a data table.

    Returns a dict mapping column name to a list of up to 10 distinct
    string values. Skips geometry-type columns and columns with no
    non-null values.
    """
    _validate_table_name(table_name)
    result: dict[str, list[str]] = {}

    for col in column_info:
        col_name = col.get("name", "")
        col_type = col.get("type", "")

        # Skip geometry columns
        if "geometry" in col_type.lower():
            continue

        # Validate column name (same safety pattern as other functions)
        if not _TABLE_NAME_RE.match(col_name):
            continue

        rows = await session.execute(
            text(
                f"SELECT DISTINCT {col_name}::text AS val "
                f"FROM ("
                f"  SELECT {col_name} FROM data.{table_name} "
                f"  WHERE {col_name} IS NOT NULL LIMIT :sample_size"
                f") sub LIMIT 10"
            ).bindparams(sample_size=sample_size)
        )
        values = [row[0] for row in rows.all() if row[0] is not None]
        if values:
            result[col_name] = values

    return result


async def compute_quality_score(
    session: AsyncSession,
    table_name: str,
    column_info: list[dict],
    dataset: "Dataset",  # noqa: F821
    max_validity_rows: int = 10000,
) -> dict:
    """Compute a weighted quality score for a dataset.

    Dimensions:
    - Metadata completeness (30%): non-empty optional fields on dataset
    - Geometry validity (30%): percentage of valid geometries
    - Attribute completeness (25%): average non-null percentage across columns
    - CRS defined (15%): 100 if srid is set, else 0

    Returns a dict with overall score and per-dimension scores.
    """

    _validate_table_name(table_name)

    # 1. Metadata completeness (weight 0.30)
    record = dataset.record

    # Check keyword presence via explicit query (avoids lazy-load in async context)
    from app.datasets.models import RecordKeyword

    kw_count = await session.scalar(
        select(func.count()).where(RecordKeyword.record_id == record.id)
    )
    has_keywords = True if kw_count and kw_count > 0 else None

    optional_fields = [
        record.summary,
        has_keywords,  # replaces old tags field (Issue 5 -- use keywords, not theme_category)
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
    metadata_score = round(filled / len(optional_fields) * 100, 1)

    # 2. CRS defined (weight 0.15)
    has_geometry = dataset.geometry_type is not None
    crs_score: float = 100.0 if (dataset.srid is not None or not has_geometry) else 0.0

    # 3. Geometry validity (weight 0.30)
    geometry_score: float = 100.0
    if has_geometry:
        try:
            result = await session.execute(
                text(
                    f"SELECT COUNT(*) FILTER (WHERE ST_IsValid(geom)) * 100.0 / NULLIF(COUNT(*), 0) "
                    f"FROM (SELECT geom FROM data.{table_name} LIMIT :max_rows) sub"
                ).bindparams(max_rows=max_validity_rows)
            )
            val = result.scalar_one_or_none()
            if val is not None:
                geometry_score = round(float(val), 1)
        except Exception:
            geometry_score = 100.0

    # 4. Attribute completeness (weight 0.25)
    attribute_score: float = 100.0
    non_geom_cols = [
        c
        for c in column_info
        if "geometry" not in c.get("type", "").lower()
        and _TABLE_NAME_RE.match(c.get("name", ""))
    ]
    if non_geom_cols:
        col_scores: list[float] = []
        for col in non_geom_cols:
            col_name = col["name"]
            try:
                result = await session.execute(
                    text(
                        f"SELECT COUNT({col_name}) * 100.0 / NULLIF(COUNT(*), 0) "
                        f"FROM data.{table_name}"
                    )
                )
                val = result.scalar_one_or_none()
                if val is not None:
                    col_scores.append(float(val))
            except Exception:
                continue
        if col_scores:
            attribute_score = round(sum(col_scores) / len(col_scores), 1)

    # 5. Composite
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


async def _table_has_geometry(session: AsyncSession, table_name: str) -> bool:
    """Check whether a data table has a 'geom' column."""
    _validate_table_name(table_name)
    result = await session.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='data' AND table_name=:table_name "
            "AND column_name='geom')"
        ).bindparams(table_name=table_name)
    )
    return result.scalar_one()


async def extract_metadata(session: AsyncSession, table_name: str) -> dict:
    """Extract all metadata from a PostGIS table.

    Returns dict with keys: srid, geometry_type, feature_count, extent_wkt,
    column_info. For non-spatial tables, spatial fields are None.
    """
    _validate_table_name(table_name)
    column_info = await get_column_info(session, table_name)
    feature_count = await get_feature_count(session, table_name)

    has_geometry = await _table_has_geometry(session, table_name)

    if has_geometry:
        srid = await get_table_srid(session, table_name)
        geometry_type = await get_geometry_type(session, table_name)
        extent_wkt = await get_extent(session, table_name)
    else:
        srid = None
        geometry_type = None
        extent_wkt = None

    return {
        "srid": srid,
        "geometry_type": geometry_type,
        "feature_count": feature_count,
        "extent_wkt": extent_wkt,
        "column_info": column_info,
    }


async def ensure_geom_column(session: AsyncSession, table_name: str) -> bool:
    """Rename the geometry column to 'geom' if ogr2ogr used a different name.

    This handles edge cases where ogr2ogr creates 'wkb_geometry' instead of
    'geom' (e.g. when appending to a pre-existing table from a failed ingest,
    or when the GDAL driver ignores -lco GEOMETRY_NAME).

    Returns True if the table has a geometry column, False for non-spatial tables.
    """
    _validate_table_name(table_name)
    result = await session.execute(
        text(
            "SELECT f_geometry_column FROM geometry_columns "
            "WHERE f_table_schema = 'data' AND f_table_name = :table_name"
        ),
        {"table_name": table_name},
    )
    row = result.first()
    if row is None:
        return False  # Non-spatial table

    geom_col = row[0]
    if geom_col == "geom":
        return True  # Already correct

    logger.info(
        "Renaming geometry column",
        table=table_name,
        from_col=geom_col,
        to_col="geom",
    )
    _validate_table_name(geom_col)
    await session.execute(
        text(f"ALTER TABLE data.{table_name} RENAME COLUMN {geom_col} TO geom")
    )
    await session.commit()
    return True


# Web Mercator (EPSG:3857) cannot represent latitudes beyond ±85.06°.
# Geometries extending past this (e.g. Antarctica at -90°) cause
# "transform: tolerance condition error" in ST_Transform.
_MERCATOR_SAFE_ENVELOPE = "ST_MakeEnvelope(-180, -85.06, 180, 85.06, 4326)"


async def clip_to_mercator_bounds(session: AsyncSession, table_name: str) -> None:
    """Clip geometries to the Web Mercator safe envelope (±85.06° lat).

    Only updates rows whose geometry actually extends beyond the bounds,
    so this is a no-op for most datasets.
    """
    _validate_table_name(table_name)
    await session.execute(
        text(
            f"UPDATE data.{table_name} "
            f"SET geom = ST_CollectionExtract("
            f"  ST_Intersection(geom, {_MERCATOR_SAFE_ENVELOPE}),"
            f"  ST_Dimension(geom) + 1"
            f") "
            f"WHERE NOT ST_CoveredBy(geom, {_MERCATOR_SAFE_ENVELOPE})"
        )
    )
    await session.commit()


async def add_4326_column(
    session: AsyncSession, table_name: str, source_srid: int
) -> None:
    """Add a geom_4326 column with WGS84 geometry and spatial index.

    If source_srid is 4326, copies geom directly (ensuring SRID is set).
    Otherwise, reprojects via ST_Transform.
    """
    tref = _qtable(table_name)

    await session.execute(
        text(
            f"ALTER TABLE {tref} "
            f"ADD COLUMN IF NOT EXISTS geom_4326 geometry(Geometry, 4326)"
        )
    )

    if source_srid == 4326:
        await session.execute(
            text(f"UPDATE {tref} SET geom_4326 = ST_SetSRID(geom, 4326)")
        )
    else:
        await session.execute(
            text(f"UPDATE {tref} SET geom_4326 = ST_Transform(geom, 4326)")
        )

    await session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_geom_4326 "
            f"ON {tref} USING GIST (geom_4326)"
        )
    )

    # B-tree index on gid for ORDER BY / keyset pagination (Phase 180 OPT-03)
    await session.execute(
        text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_gid ON {tref} (gid)")
    )

    await session.commit()


async def grant_reader_access(session: AsyncSession, table_name: str) -> None:
    """Grant SELECT on the table to geolens_reader role."""
    await session.execute(
        text(f"GRANT SELECT ON {_qtable(table_name)} TO geolens_reader")
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Attribute metadata helpers
# ---------------------------------------------------------------------------


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


async def generate_attribute_metadata(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    column_info: list[dict],
    *,
    geometry_type: str | None = None,
    sample_values: dict | None = None,
) -> list["AttributeMetadata"]:
    """Auto-populate attribute_metadata rows from column_info.

    Creates one row per column plus a geometry row if geometry_type is provided.
    Uses check-then-insert to be idempotent (skips existing field_names).
    Does NOT query the data table -- sample_values are passed in by the caller.
    """
    from app.datasets.models import AttributeMetadata

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

        data_type = col.get("type", "")
        example_vals = None
        if sample_values and field_name in sample_values:
            example_vals = sample_values[field_name]

        am = AttributeMetadata(
            dataset_id=dataset_id,
            field_name=field_name,
            title=_humanize_column_name(field_name),
            data_type=data_type,
            units=_infer_units(field_name),
            semantic_role=_infer_semantic_role(field_name, data_type),
            domain_type=_infer_domain_type(data_type),
            example_values=example_vals,
            ordinal_position=col.get("ordinal_position"),
            is_nullable=col.get("is_nullable"),
            is_current=True,
        )
        session.add(am)
        created.append(am)
        existing_fields.add(field_name)

    # Geometry row
    if geometry_type is not None and "geom" not in existing_fields:
        am = AttributeMetadata(
            dataset_id=dataset_id,
            field_name="geom",
            title="Geometry",
            data_type=geometry_type or "geometry",
            semantic_role="geometry",
            domain_type="geometry",
            example_values=None,
            is_current=True,
        )
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
    from app.datasets.models import AttributeMetadata

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
            # New column -- create fresh row
            am = AttributeMetadata(
                dataset_id=dataset_id,
                field_name=field_name,
                title=_humanize_column_name(field_name),
                data_type=data_type,
                units=_infer_units(field_name),
                semantic_role=_infer_semantic_role(field_name, data_type),
                domain_type=_infer_domain_type(data_type),
                example_values=example_vals,
                ordinal_position=col.get("ordinal_position"),
                is_nullable=col.get("is_nullable"),
                is_current=True,
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
            am = AttributeMetadata(
                dataset_id=dataset_id,
                field_name="geom",
                title="Geometry",
                data_type=geometry_type or "geometry",
                semantic_role="geometry",
                domain_type="geometry",
                example_values=None,
                is_current=True,
            )
            session.add(am)

    # Mark removed columns as is_current=False
    for field_name, am in existing.items():
        if field_name not in current_field_names and field_name != "geom":
            am.is_current = False

    await session.flush()
