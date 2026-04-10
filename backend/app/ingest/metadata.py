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

        # SQL-quote the identifier so non-ASCII, mixed-case, and hyphenated
        # column names are handled correctly. The table-name validation above
        # already guards against injection via the table path; quoting the
        # column name is the safe alternative to the old regex filter.
        quoted = '"' + col_name.replace('"', '""') + '"'

        rows = await session.execute(
            text(
                f"SELECT DISTINCT {quoted}::text AS val "
                f"FROM ("
                f"  SELECT {quoted} FROM {_qtable(table_name)} "
                f"  WHERE {quoted} IS NOT NULL LIMIT :sample_size"
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
    # Wrap in a SAVEPOINT (begin_nested) so that a failed query (e.g. missing
    # table in tests, permission denied) does not poison the outer transaction.
    geometry_score: float = 100.0
    if has_geometry:
        try:
            async with session.begin_nested():
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
    # Compute per-column non-null percentage in a SINGLE query instead of N queries.
    # A 50-column dataset previously triggered 50 sequential full-table scans.
    # Column identifiers are SQL-quoted below so non-ASCII / mixed-case / CJK
    # column names are counted correctly (see RESEARCH §2.5 regression fix).
    attribute_score: float = 100.0
    non_geom_cols = [
        c
        for c in column_info
        if "geometry" not in c.get("type", "").lower() and c.get("name")
    ]
    if non_geom_cols:
        col_exprs = ", ".join(
            f'COUNT("{col["name"].replace(chr(34), chr(34) + chr(34))}") '
            f'* 100.0 / NULLIF(COUNT(*), 0) AS "s_{i}"'
            for i, col in enumerate(non_geom_cols)
        )
        try:
            async with session.begin_nested():
                result = await session.execute(
                    text(f"SELECT {col_exprs} FROM data.{table_name}")
                )
                row = result.one_or_none()
                if row is not None:
                    col_scores: list[float] = [float(v) for v in row if v is not None]
                    if col_scores:
                        attribute_score = round(sum(col_scores) / len(col_scores), 1)
        except Exception:
            # On failure, leave attribute_score at its 100.0 default (same as prior behavior)
            pass

    # 5. Composite
    # For table records, geometry_validity and crs_defined are not applicable.
    # Re-normalize weights over the two applicable dimensions:
    #   metadata (30) + attribute (25) = 55 total → metadata (30/55) + attribute (25/55)
    is_table = getattr(record, "record_type", None) == "table"
    if is_table:
        overall = round(metadata_score * (30 / 55) + attribute_score * (25 / 55))
        return {
            "overall": overall,
            "metadata_completeness": metadata_score,
            "attribute_completeness": attribute_score,
            "geometry_validity": None,  # N/A for tables
            "crs_defined": None,  # N/A for tables
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


async def rename_reserved_columns(
    session: AsyncSession,
    table_name: str,
) -> list[dict]:
    """Rename any source column whose name collides with a GeoLens-internal
    PostGIS column (gid, geom, geometry, geom_4326, fid, ogc_fid) to
    ``src_<name>``. Runs BEFORE add_4326_column so that ALTER TABLE ADD COLUMN
    geom_4326 cannot collide with a source attribute.

    Only renames columns that were NOT created by the ingest pipeline itself:
    - ``gid``: pipeline creates it as a serial PRIMARY KEY (column_default is
      non-null). A source-origin ``gid`` has no default and is not an identity.
    - ``geom`` / ``geometry``: pipeline creates a PostGIS geometry column
      (data_type = 'USER-DEFINED', udt_name = 'geometry'). Any other type is
      source-origin.
    - ``geom_4326``: always renamed on entry — this helper runs before
      add_4326_column, so any existing ``geom_4326`` must be source-origin.
    - ``fid``, ``ogc_fid``: always renamed (ogr2ogr with -lco FID=gid does not
      create these; any such column is source-origin).

    Returns a list of rename records ``[{"original": "gid", "renamed": "src_gid"}, ...]``
    which callers can attach to ``job.user_metadata['warnings']``.
    """
    from app.ingest.ogr import RESERVED_COLUMN_NAMES

    _validate_table_name(table_name)

    result = await session.execute(
        text(
            "SELECT column_name, data_type, udt_name, column_default, is_identity "
            "FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :t "
            "ORDER BY ordinal_position"
        ).bindparams(t=table_name)
    )
    rows = result.all()
    all_column_names = {r[0] for r in rows}

    renames: list[dict] = []
    for row in rows:
        col_name, data_type, udt_name, col_default, is_identity = row
        if col_name not in RESERVED_COLUMN_NAMES:
            continue

        # Determine if this column was created by the pipeline or came from the source.
        if col_name == "gid":
            # Pipeline-created gid is a serial/identity with a nextval default.
            # Source-origin gid has no default and is not an identity column.
            is_pipeline_gid = (col_default is not None and "nextval" in str(col_default)) or (
                is_identity == "YES"
            )
            if is_pipeline_gid:
                continue  # This is the pipeline's own gid — leave it alone.

        elif col_name in ("geom", "geometry"):
            # Pipeline-created geometry column has data_type = 'USER-DEFINED'
            # and udt_name = 'geometry'. Source-origin columns have other types.
            if data_type == "USER-DEFINED" and udt_name == "geometry":
                continue  # Pipeline-created spatial column — leave it alone.

        # All remaining reserved-name columns are source-origin. Rename to src_<name>.
        # If src_<name> already exists, append a numeric suffix.
        target = f"src_{col_name}"
        suffix = 2
        while target in all_column_names:
            target = f"src_{col_name}_{suffix}"
            suffix += 1

        # Execute the rename using double-quoted identifiers (not bindable).
        q_orig = '"' + col_name.replace('"', '""') + '"'
        q_target = '"' + target.replace('"', '""') + '"'
        await session.execute(
            text(f'ALTER TABLE "data"."{table_name}" RENAME COLUMN {q_orig} TO {q_target}')
        )

        logger.warning(
            "Renamed reserved source column",
            table=table_name,
            original=col_name,
            renamed=target,
        )
        renames.append({"original": col_name, "renamed": target})
        # Update the in-memory set so subsequent iterations see the new name.
        all_column_names.discard(col_name)
        all_column_names.add(target)

    if renames:
        await session.commit()
    return renames


def detect_dbf_truncation_collisions(
    source_columns: list[dict],
) -> list[dict]:
    """Detect shapefile DBF 10-character field-name truncation collisions.

    Given the source-file column list from run_ogrinfo_preview(), returns a
    list of collision records grouped by the first 10 lowercase characters:
      [{"truncated": "population", "originals": ["population_2020", "population_2021"]}]

    Only returns groups with 2+ original names — a single column is not a
    collision. Empty input returns an empty list.
    """
    truncation_map: dict[str, list[str]] = {}
    for col in source_columns:
        name = col.get("name", "")
        truncated = name[:10].lower()
        truncation_map.setdefault(truncated, []).append(name)

    return [
        {"truncated": truncated, "originals": originals}
        for truncated, originals in truncation_map.items()
        if len(originals) >= 2
    ]


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
