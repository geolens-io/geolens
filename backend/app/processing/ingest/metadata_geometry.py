"""Constructing a table's ``geom`` column, and laundering the names around it.

Split out of ``metadata.py`` (#1042). Three steps of one job, which is why they
travel together: ``rename_reserved_columns`` moves any source attribute out of
the internal names (``geom``, ``geom_4326``, ``gid``, ``fid``, ...), which is
what leaves ``geom`` free for ``ensure_geom_column`` to rename ogr2ogr's
placeholder into; the ``construct_*`` pair builds ``geom`` from x/y or WKT
columns when the source carried no geometry at all.

``detect_dbf_truncation_collisions`` is the other way source column names go
wrong — shapefile DBF truncates them to 10 characters — and is reported to the
user rather than repaired.
"""

import re

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ingest.metadata_sql import (
    _TABLE_NAME_RE,
    _qtable,
    _sql_quote_ident,
    _validate_table_name,
)

logger = structlog.stdlib.get_logger(__name__)


async def construct_point_geometry(
    session: AsyncSession,
    table_name: str,
    x_column: str,
    y_column: str,
    srid: int = 4326,
    *,
    schema: str = "data",
) -> int:
    """Add geometry column from x/y coordinate columns.

    Returns count of rows with valid geometry.
    """
    _validate_table_name(table_name)
    if not _TABLE_NAME_RE.match(x_column) or not _TABLE_NAME_RE.match(y_column):
        raise ValueError("Invalid column name")

    tref = _qtable(table_name, schema=schema)
    x_col = _sql_quote_ident(x_column)
    y_col = _sql_quote_ident(y_column)
    finite_floor = "-1.7976931348623157e308"
    finite_ceiling = "1.7976931348623157e308"
    unparseable = await session.execute(
        text(
            f"SELECT COUNT(*) FROM {tref} "
            f"WHERE {x_col} IS NOT NULL AND {y_col} IS NOT NULL "
            f"AND (NOT pg_input_is_valid({x_col}::text, 'double precision') "
            f"OR NOT pg_input_is_valid({y_col}::text, 'double precision'))"
        )
    )
    unparseable_count = int(unparseable.scalar_one())
    if unparseable_count:
        raise ValueError(
            f"{unparseable_count} row(s) contain X/Y values that are not numbers"
        )
    if srid == 4326:
        valid_coordinates = (
            f"{x_col}::double precision BETWEEN -180 AND 180 AND "
            f"{y_col}::double precision BETWEEN -90 AND 90"
        )
    else:
        valid_coordinates = (
            f"{x_col}::double precision BETWEEN {finite_floor} AND {finite_ceiling} "
            f"AND {y_col}::double precision BETWEEN {finite_floor} AND {finite_ceiling}"
        )
    invalid = await session.execute(
        text(
            f"SELECT COUNT(*) FROM {tref} "
            f"WHERE {x_col} IS NOT NULL AND {y_col} IS NOT NULL "
            f"AND NOT ({valid_coordinates})"
        )
    )
    invalid_count = int(invalid.scalar_one())
    if invalid_count:
        coordinate_system = "EPSG:4326 ranges" if srid == 4326 else "finite values"
        raise ValueError(
            f"{invalid_count} row(s) contain X/Y coordinates outside {coordinate_system}"
        )
    await session.execute(
        text(f"ALTER TABLE {tref} ADD COLUMN geom geometry(Point, {srid})")
    )
    result = await session.execute(
        text(
            f"UPDATE {tref} SET geom = ST_SetSRID("
            f"  ST_MakePoint({x_col}::double precision, {y_col}::double precision), "
            f"  {srid}) "
            f"WHERE {x_col} IS NOT NULL AND {y_col} IS NOT NULL "
            f"AND {valid_coordinates}"
        )
    )
    await session.execute(
        text(f"CREATE INDEX idx_{table_name}_geom ON {tref} USING GIST (geom)")
    )
    # SQLAlchemy CursorResult exposes rowcount for DML; the async Result
    # type stub is less specific so mypy can't narrow it here.
    return result.rowcount  # type: ignore[attr-defined]


async def construct_wkt_geometry(
    session: AsyncSession,
    table_name: str,
    wkt_column: str,
    srid: int = 4326,
    *,
    schema: str = "data",
) -> int:
    """Add geometry column from a WKT text column.

    Returns count of rows with valid geometry.
    """
    _validate_table_name(table_name)
    if not _TABLE_NAME_RE.match(wkt_column):
        raise ValueError("Invalid column name")

    tref = _qtable(table_name, schema=schema)
    wkt_col = _sql_quote_ident(wkt_column)
    parsed_geom = f"ST_GeomFromText({wkt_col}, {srid})"
    invalid_conditions = [
        f"lower({wkt_col}) ~ '(nan|inf)'",
        f"NOT ST_IsValid({parsed_geom})",
    ]
    if srid == 4326:
        invalid_conditions.extend(
            [
                f"ST_XMin(Box3D({parsed_geom})) < -180",
                f"ST_XMax(Box3D({parsed_geom})) > 180",
                f"ST_YMin(Box3D({parsed_geom})) < -90",
                f"ST_YMax(Box3D({parsed_geom})) > 90",
            ]
        )
    try:
        # PostGIS raises on syntactically malformed WKT. A SAVEPOINT keeps that
        # expected validation failure from aborting the caller's ingest
        # transaction, allowing it to report a stable ValueError and clean up.
        async with session.begin_nested():
            invalid = await session.execute(
                text(
                    f"SELECT COUNT(*) FROM {tref} WHERE {wkt_col} IS NOT NULL "
                    f"AND ({' OR '.join(invalid_conditions)})"
                )
            )
            invalid_count = int(invalid.scalar_one())
            if invalid_count:
                coordinate_system = (
                    "EPSG:4326 ranges" if srid == 4326 else "finite values"
                )
                raise ValueError(
                    f"{invalid_count} row(s) contain invalid WKT geometry or "
                    f"coordinates outside {coordinate_system}"
                )

            # Detect geometry type from sample row while malformed input is
            # still isolated by the validation savepoint.
            sample = await session.execute(
                text(
                    f"SELECT GeometryType({parsed_geom}) "
                    f"FROM {tref} WHERE {wkt_col} IS NOT NULL LIMIT 1"
                )
            )
            geom_type = sample.scalar_one_or_none() or "GEOMETRY"
    except DBAPIError as exc:
        raise ValueError("WKT column contains malformed geometry text") from exc

    await session.execute(
        text(f"ALTER TABLE {tref} ADD COLUMN geom geometry({geom_type}, {srid})")
    )
    result = await session.execute(
        text(f"UPDATE {tref} SET geom = {parsed_geom} WHERE {wkt_col} IS NOT NULL")
    )
    await session.execute(
        text(f"CREATE INDEX idx_{table_name}_geom ON {tref} USING GIST (geom)")
    )
    # SQLAlchemy CursorResult exposes rowcount for DML; the async Result
    # type stub is less specific so mypy can't narrow it here.
    return result.rowcount  # type: ignore[attr-defined]


async def ensure_geom_column(
    session: AsyncSession, table_name: str, schema: str = "data"
) -> bool:
    """Rename the geometry column to 'geom' if ogr2ogr used a different name.

    In the happy path this renames the `_geolens_geom` placeholder that
    `run_ogr2ogr` / `run_ogr2ogr_service` create (see the GEOMETRY_NAME
    override in ogr.py) to `geom`. It also handles legacy edge cases where
    ogr2ogr creates 'wkb_geometry' instead (e.g. when appending to a
    pre-existing table or when a driver ignores -lco GEOMETRY_NAME).

    Must run AFTER `rename_reserved_columns` so that any source attribute
    named `geom`/`geometry` has already been moved to `src_<name>`,
    leaving `geom` free for the rename.

    ``schema`` defaults to ``"data"`` for single_tenant backward compatibility.
    In multi_tenant callers pass ``_current_tenant_schema()`` (CR-03, Phase 1209).

    Returns True if the table has a geometry column, False for non-spatial tables.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)
    result = await session.execute(
        text(
            "SELECT f_geometry_column FROM geometry_columns "
            "WHERE f_table_schema = :schema AND f_table_name = :table_name"
        ),
        {"schema": schema, "table_name": table_name},
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
        text(
            f"ALTER TABLE {_qtable(table_name, schema=schema)} "
            f"RENAME COLUMN {_sql_quote_ident(geom_col)} TO geom"
        )
    )
    # ING-02 / P2-02 (Phase 1076): no internal commit. The caller
    # (_finalize_ingest at tasks_common.py:821) owns the phase-2 commit
    # boundary so a downstream failure rolls back this rename atomically.
    return True


async def rename_reserved_columns(
    session: AsyncSession,
    table_name: str,
    schema: str = "data",
) -> list[dict]:
    """Rename any source column whose name collides with a GeoLens-internal
    PostGIS column (gid, geom, geometry, geom_4326, fid, ogc_fid) to
    ``src_<name>``. Runs BEFORE add_4326_column so that ALTER TABLE ADD COLUMN
    geom_4326 cannot collide with a source attribute.

    fix(#640): also renames columns containing ``:`` (Socrata exports ship
    system columns literally named ``:id``, ``:created_at``, ... which
    survive OGR's laundering). A colon inside a double-quoted identifier is
    parsed as a bind parameter by SQLAlchemy ``text()``, so such names break
    every downstream text()-built query (sampling, column stats, tiles).
    They are laundered to letter-leading safe names (``:id`` -> ``id``).

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
    from app.processing.ingest.ogr import RESERVED_COLUMN_NAMES

    _validate_table_name(table_name)
    _validate_table_name(schema)

    # PERF-4: fast-path — most ingests have zero reserved-name collisions,
    # so check first with a tiny WHERE-filtered query before fetching the
    # full column list. Skips the full-table scan in the common case.
    reserved_check = await session.execute(
        text(
            "SELECT column_name "
            "FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :t "
            "AND (column_name = ANY(:names) OR strpos(column_name, ':') > 0)"
        ).bindparams(schema=schema, t=table_name, names=list(RESERVED_COLUMN_NAMES))
    )
    if not reserved_check.first():
        return []

    # At least one collision candidate exists — now fetch everything we
    # need to decide whether each candidate is source-origin and what
    # rename target is safe.
    result = await session.execute(
        text(
            "SELECT column_name, data_type, udt_name, column_default, is_identity "
            "FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :t "
            "ORDER BY ordinal_position"
        ).bindparams(schema=schema, t=table_name)
    )
    rows = result.all()
    all_column_names = {r[0] for r in rows}

    # Wrap the entire rename loop in a SAVEPOINT so a mid-loop ALTER
    # failure rolls back ALL previously-applied renames atomically (R-4).
    # Without this, an ALTER failing on the Nth rename would commit N-1
    # renames and leave the ingest table in an inconsistent state that
    # the caller cannot recover from.
    renames: list[dict] = []
    try:
        async with session.begin_nested():
            for row in rows:
                col_name, data_type, udt_name, col_default, is_identity = row
                if col_name not in RESERVED_COLUMN_NAMES and ":" not in col_name:
                    continue

                if ":" in col_name:
                    # fix(#640): colon-bearing (Socrata-style) column —
                    # launder to a safe name. Must start with a letter or the
                    # column-stats/distinct-values identifier validator
                    # rejects it (codex P2 on #646): ":id" -> "id", not "_id".
                    base = re.sub(r"[^A-Za-z0-9_]", "_", col_name).strip("_")
                    if not base or not base[0].isalpha():
                        base = f"col_{base}" if base else "col"
                    # A laundered name may hit an internal name (":geom" ->
                    # "geom") — apply the reserved-name rule so the staging
                    # pipeline's own geometry columns stay uncontested
                    # (codex P2 round 2 on #646).
                    if base in RESERVED_COLUMN_NAMES:
                        base = f"src_{base}"
                    base = base[:63]
                else:
                    # Determine if this column was created by the pipeline or came from the source.
                    if col_name == "gid":
                        # Pipeline-created gid is a serial/identity with a nextval default.
                        # Source-origin gid has no default and is not an identity column.
                        is_pipeline_gid = (
                            col_default is not None and "nextval" in str(col_default)
                        ) or (is_identity == "YES")
                        if is_pipeline_gid:
                            continue  # This is the pipeline's own gid — leave it alone.

                    elif col_name in ("geom", "geometry"):
                        # Pipeline-created geometry column has data_type = 'USER-DEFINED'
                        # and udt_name = 'geometry'. Source-origin columns have other types.
                        if data_type == "USER-DEFINED" and udt_name == "geometry":
                            continue  # Pipeline-created spatial column — leave it alone.

                    # All remaining reserved-name columns are source-origin. Rename to src_<name>.
                    base = f"src_{col_name}"

                # If the target already exists, append a numeric suffix.
                target = base
                suffix = 2
                while target in all_column_names:
                    target = f"{base[:60]}_{suffix}"
                    suffix += 1

                # Execute the rename using double-quoted identifiers (not bindable).
                q_orig = _sql_quote_ident(col_name)
                q_target = _sql_quote_ident(target)
                await session.execute(
                    text(
                        f'ALTER TABLE "{schema}"."{table_name}" '
                        f"RENAME COLUMN {q_orig} TO {q_target}"
                    )
                )

                logger.warning(
                    "Renamed reserved or unsafe source column",
                    table=table_name,
                    original=col_name,
                    renamed=target,
                )
                renames.append({"original": col_name, "renamed": target})
                # Update the in-memory set so subsequent iterations see the new name.
                all_column_names.discard(col_name)
                all_column_names.add(target)
    except Exception as exc:  # broad: ALTER TABLE can fail for schema/permission reasons; re-raise to fail the job
        # Savepoint rollback already unwound any partial renames; re-raise so
        # the caller's exception handler marks the ingest job as failed with
        # a clear error message.
        logger.error(
            "Reserved-column rename failed; table left in pre-rename state",
            table=table_name,
            error=str(exc),
            renames_attempted=len(renames),
            exc_info=True,
        )
        raise

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
