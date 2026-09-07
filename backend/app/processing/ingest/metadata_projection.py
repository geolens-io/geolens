"""The 4326 render column and the reader grant.

What ``_finalize_ingest`` does last, to make a landed table readable by the
tile, feature and analysis surfaces. ``add_4326_column`` writes the render
column (2D, linear, with its GIST index); ``linearize_existing_4326``
enforces that same invariant on a BYO column the pipeline never wrote;
``rederive_geom_4326`` (fix(#1738)) re-applies the whole invariant to a
registered table its owner has written to since, over the state
``probe_geom_4326`` reads; ``grant_reader_access`` hands the finished table
to the reader role.
"""

from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ingest.metadata_sql import _qtable


def _geom_4326_expr(source_srid: int) -> str:
    """The expression that derives ``geom_4326`` from ``geom``.

    One definition: :func:`add_4326_column` and the out-of-band repair
    :func:`rederive_geom_4326` both write this column, and a drift between
    them would make a refresh rewrite every row of every table forever
    while "fixing" nothing.

    fix(#1113): linearize IN THE SOURCE CRS, then reproject. An arc is
    defined by its control points, and CRS transforms are nonlinear:
    transforming the points first and densifying after traces the arc in
    the wrong space, so ``ST_CurveToLine(ST_Transform(...))`` yields a
    materially different shape from the correct
    ``ST_Transform(ST_CurveToLine(...))``.
    """
    if source_srid == 4326:
        return "ST_Force2D(ST_CurveToLine(ST_SetSRID(geom, 4326)))"
    return "ST_Force2D(ST_Transform(ST_CurveToLine(geom), 4326))"


async def add_4326_column(
    session: AsyncSession,
    table_name: str,
    source_srid: int,
    *,
    schema: str = "data",
) -> None:
    """Add a geom_4326 column with WGS84 geometry and spatial index.

    Copies geom directly if source_srid is 4326; otherwise reprojects via
    ST_Transform.

    Declared 2D (`geometry(Geometry, 4326)`) since it backs tile/map
    rendering. `ST_Force2D` strips any source Z (e.g. SRID 4979) so the
    UPDATE doesn't fail with "Geometry has Z dimension but column does
    not"; Z stays in the original `geom` column.

    fix(#1104): also always LINEAR. WFS ingest admits curved geometries
    (MultiSurface/CompoundCurve), and every reader of geom_4326 raises on
    them (ST_AsMVTGeom, ST_AsGeoJSON, ``::geography``, ST_MakeValid).
    `ST_CurveToLine` densifies arcs here, at the one boundary they all
    read from — a no-op on already-linear input, with the curved source
    staying in `geom`, same as Z.
    """
    tref = _qtable(table_name, schema=schema)

    await session.execute(
        text(
            # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
            f"ALTER TABLE {tref} "
            f"ADD COLUMN IF NOT EXISTS geom_4326 geometry(Geometry, 4326)"
        )
    )

    # The expression itself, and the reason it linearizes before it
    # reprojects, live on _geom_4326_expr — the repair path writes the same
    # column and must write it the same way.
    rewrite_expr = _geom_4326_expr(source_srid)
    # codeql[py/sql-injection] fix(#1615): table via _qtable (metadata_sql.py); rewrite_expr is one of _geom_4326_expr's two literals
    await session.execute(text(f"UPDATE {tref} SET geom_4326 = {rewrite_expr}"))

    await ensure_geom_4326_gist_index(session, table_name, schema=schema)

    # No internal commit: the caller (_finalize_ingest at
    # tasks_common.py:821) owns the phase-2 commit boundary so a downstream
    # failure rolls back the ALTER + UPDATE + CREATE INDEX above atomically.


REPAIR_APPLIED = "applied"
REPAIR_NO_GEOMETRY = "no_geometry"
REPAIR_GENERATED = "generated"


class Geom4326State(NamedTuple):
    """What the two geometry columns look like right now.

    Split out so the caller can decide what to do BEFORE resolving the
    source SRID. fix(#1738): ``get_table_srid`` wraps PostGIS
    ``Find_SRID``, which RAISES for a table with no registered geometry
    column rather than returning NULL — a registered non-spatial table
    (#1359 admits them) used to reach the repair as an exception and skip
    the reader grant that follows it.
    """

    source_is_geometry: bool
    has_render: bool
    render_generated: bool

    @property
    def rederivable(self) -> bool:
        """Whether re-deriving the render column is possible at all."""
        return self.source_is_geometry and not self.render_generated


async def probe_geom_4326(
    session: AsyncSession, table_name: str, *, schema: str = "data"
) -> Geom4326State:
    """Read the state of ``geom`` and ``geom_4326`` in one query.

    The same pair of column names registration looks for. ``udt_name`` is
    checked because a plain column that happens to be called ``geom`` is not a
    geometry: ``Find_SRID`` would raise on it, and the UPDATE would too.
    """
    rows = (
        await session.execute(
            text(
                "SELECT column_name, udt_name, is_generated "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "  AND column_name IN ('geom', 'geom_4326')"
            ).bindparams(schema=schema, table=table_name)
        )
    ).all()
    columns = {row.column_name: row for row in rows}
    source = columns.get("geom")
    render = columns.get("geom_4326")
    return Geom4326State(
        source_is_geometry=source is not None and source.udt_name == "geometry",
        has_render=render is not None,
        render_generated=render is not None and render.is_generated == "ALWAYS",
    )


class Geom4326Repair(NamedTuple):
    """What one re-derive pass did to a table, for the run to report.

    ``rows_rewritten`` is the drift signal: a table nobody wrote to since the
    last pass reports 0, and a repeated non-zero count means the owner's
    writes keep arriving between refreshes.
    """

    outcome: str
    column_added: bool
    index_added: bool
    rows_rewritten: int


async def rederive_geom_4326(
    session: AsyncSession,
    table_name: str,
    source_srid: int,
    *,
    schema: str = "data",
    state: Geom4326State | None = None,
) -> Geom4326Repair:
    """Re-apply the geom_4326 invariant to a table written to outside GeoLens.

    fix(#1738): ``geom_4326`` is a plain column, populated once at
    registration and afterwards only by GeoLens's own feature-edit writes.
    A registered table's owner keeps writing to it directly, and nothing
    re-derives the column for those writes — an ``UPDATE geom``, a
    ``DELETE``+re-``INSERT``, or ``ogr2ogr -overwrite`` (which drops and
    recreates the table without the column, index, or reader grant) leaves
    rows whose render geometry is stale or NULL. Every reader filters on
    ``geom_4326 && <envelope>``, and ``NULL && anything`` is NULL — so
    those rows go silently invisible rather than visibly wrong.

    Re-applied from OUTSIDE the table (same idempotent ADD COLUMN,
    expression, and index-if-absent registration uses), which is what lets
    it survive ``-overwrite`` without deleting and re-registering the
    dataset.

    **The UPDATE is scoped to rows whose stored value would actually
    change**, compared via ``ST_AsBinary`` — this keeps a refresh of an
    untouched table to one sequential scan with no writes, which is what
    makes it safe to run on every refresh. Deliberately NOT
    ``geom_4326 IS NULL OR ...``: a row with NULL ``geom`` already has a
    correct NULL render, and that disjunct would rewrite it NULL-to-NULL
    every pass — a write that changes nothing and a drift count that lies.

    Skips a STORED GENERATED ``geom_4326`` (same reason as
    :func:`linearize_existing_4326`: PostgreSQL rejects non-DEFAULT writes
    to it at parse time, and it re-derives itself on every write anyway).
    Skips a table with no ``geom`` column too — registration admits
    non-spatial tables (#1359), and #1737 refuses geometry under another
    name, so "no geom" here means an attribute table, not a broken one.

    Benign interaction, not drift: feature edits write ``geom_4326``
    straight from the request GeoJSON and ``geom`` by transforming that
    into the dataset SRID (``features/service.py``), so on a projected
    dataset the stored render value isn't a round trip. The first pass
    after such an edit normalizes it to ``ST_Transform(geom, 4326)`` — a
    sub-millimetre change counted as one drifted row — then converges.

    The caller owns the transaction, statement deadline, and reader GRANT;
    this function only touches the column and its index.
    """
    tref = _qtable(table_name, schema=schema)

    # ``state`` is accepted rather than always probed: the caller needs these
    # answers first anyway to decide whether to resolve the source SRID at
    # all. Probed here when absent so the function still stands on its own.
    if state is None:
        state = await probe_geom_4326(session, table_name, schema=schema)

    if not state.source_is_geometry:
        return Geom4326Repair(REPAIR_NO_GEOMETRY, False, False, 0)
    if state.render_generated:
        return Geom4326Repair(REPAIR_GENERATED, False, False, 0)

    if not state.has_render:
        # Gated on the probe, NOT left to ``IF NOT EXISTS``: ALTER TABLE takes
        # ACCESS EXCLUSIVE regardless, and a merely QUEUED lock request
        # already blocks every reader behind it — issuing it on the ordinary
        # path (a table that still has its column) would stop-the-world on
        # every refresh. ``IF NOT EXISTS`` stays as the race guard for a
        # column added between the probe and here.
        await session.execute(
            text(
                # codeql[py/sql-injection] fix(#1738): identifiers validated by _qtable (metadata_sql.py)
                f"ALTER TABLE {tref} "
                f"ADD COLUMN IF NOT EXISTS geom_4326 geometry(Geometry, 4326)"
            )
        )

    rewrite_expr = _geom_4326_expr(source_srid)
    result = await session.execute(
        text(
            # codeql[py/sql-injection] fix(#1738): table via _qtable (metadata_sql.py); rewrite_expr is one of _geom_4326_expr's two literals
            f"UPDATE {tref} SET geom_4326 = {rewrite_expr} "
            f"WHERE ST_AsBinary(geom_4326) IS DISTINCT FROM "
            f"      ST_AsBinary({rewrite_expr})"
        )
    )
    index_added = await ensure_geom_4326_gist_index(session, table_name, schema=schema)
    return Geom4326Repair(
        REPAIR_APPLIED,
        not state.has_render,
        index_added,
        result.rowcount if result.rowcount and result.rowcount > 0 else 0,
    )


async def linearize_existing_4326(
    session: AsyncSession, table_name: str, *, schema: str = "data"
) -> None:
    """Enforce the geom_4326-is-always-linear invariant on a column we did not write.

    fix(#1113): ``register_existing_table`` skips :func:`add_4326_column`
    when the table already carries geom_4326, so a table created or copied
    into the data schema after migration 0034 could re-introduce curved
    values the backfill can no longer see, with the per-read ST_CurveToLine
    wraps that used to absorb them gone. Enforced here at registration with
    the same predicate as the migration: any arc, top-level curve type, or
    GEOMETRYCOLLECTION (curve members can't hide anywhere else — linear
    multi types can't contain them). Exact no-op on already-linear rows.

    A BYO column may also DECLARE a curved typmod (e.g.
    geometry(CurvePolygon, 4326)), which would reject the linear UPDATE
    result outright; such a column is loosened to a generic typmod first,
    PRESERVING its Z/M flags (geometry_columns reports M as a type suffix
    and Z only via coord_dimension; a plain Geometry typmod rejects Z).
    Only the concrete curve typmods need it — abstract CURVE/SURFACE accept
    their linear subtypes; rtrim(type,'M') matches M-suffixed variants, since
    no base curve name ends in M.
    """
    tref = _qtable(table_name, schema=schema)
    # fix(#1113): a STORED GENERATED geom_4326 rejects any UPDATE at parse
    # time, decided instead by its generation expression, so it can be
    # neither repaired nor retyped here — skip it (#1114 tracks
    # expressions that yield curves).
    generated = (
        await session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "  AND column_name = 'geom_4326' AND is_generated = 'ALWAYS'"
            ).bindparams(schema=schema, table=table_name)
        )
    ).first()
    if generated is not None:
        # fix(#1113): a generated column with CURRENTLY-curved rows would
        # register a dataset broken on every surface with no later fix
        # possible — refuse with the actionable cause. An empty or linear
        # generated column registers fine; curves only for FUTURE rows is
        # #1114's residue, same as any external write. The test — "would
        # linearization change the value", byte-for-byte — catches arcs,
        # top-level curve types, AND curve containers nested in a
        # GEOMETRYCOLLECTION in one comparison; a type list would miss the
        # nested case or over-reject linear collections.
        curved = (
            await session.execute(
                text(
                    # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
                    f"SELECT 1 FROM {tref} "  # noqa: S608
                    f"WHERE ST_AsBinary(ST_CurveToLine(geom_4326)) "
                    f"      <> ST_AsBinary(geom_4326) "
                    f"LIMIT 1"
                )
            )
        ).first()
        if curved is not None:
            raise ValueError(
                "geom_4326 is a generated column whose expression yields "
                "curved geometries; adjust it to apply ST_CurveToLine "
                "(curved types break tiles, feature reads, and analysis)"
            )
        return
    typmod = (
        await session.execute(
            text(
                "SELECT type, srid, coord_dimension "
                "FROM public.geometry_columns "
                "WHERE f_table_schema = :schema "
                "  AND f_table_name = :table "
                "  AND f_geometry_column = 'geom_4326' "
                "  AND rtrim(type, 'M') IN ('CIRCULARSTRING','COMPOUNDCURVE',"
                "               'CURVEPOLYGON','MULTICURVE','MULTISURFACE')"
            ).bindparams(schema=schema, table=table_name)
        )
    ).first()
    if typmod is not None:
        if typmod.coord_dimension == 4:
            generic = "GeometryZM"
        elif typmod.coord_dimension == 3:
            generic = "GeometryM" if typmod.type.endswith("M") else "GeometryZ"
        else:
            generic = "Geometry"
        await session.execute(
            text(
                # codeql[py/sql-injection] fix(#1615): table via _qtable (metadata_sql.py); generic is a fixed literal, srid an int()
                f"ALTER TABLE {tref} ALTER COLUMN geom_4326 "
                f"TYPE geometry({generic}, {int(typmod.srid)})"
            )
        )
    # rtrim on GeometryType too: an M curve reports CURVEPOLYGONM, so the
    # bare list would skip an arc-free M container.
    await session.execute(
        text(
            # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
            f"UPDATE {tref} SET geom_4326 = ST_CurveToLine(geom_4326) "
            f"WHERE ST_HasArc(geom_4326) "
            f"   OR rtrim(GeometryType(geom_4326), 'M') IN "
            f"      ('CIRCULARSTRING','COMPOUNDCURVE','CURVEPOLYGON',"
            f"       'MULTICURVE','MULTISURFACE') "
            f"   OR rtrim(GeometryType(geom_4326), 'M') = 'GEOMETRYCOLLECTION'"
        )
    )


async def ensure_geom_4326_gist_index(
    session: AsyncSession, table_name: str, *, schema: str = "data"
) -> bool:
    """Create the GIST index on geom_4326 if this table doesn't have one.

    Returns whether an index was created — fix(#1738): the repair path
    reports "the spatial index was missing" from this value; every other
    caller ignores it.

    fix(#448): the previous ``CREATE INDEX IF NOT EXISTS
    idx_<table>_geom_4326`` matched by NAME schema-wide, not per-table. On a
    second re-ingest the previous swap's index (created against
    ``<table>_staging``, carried along by the RENAME) still held that name,
    so the new staging table silently got NO spatial index and the swap
    then dropped the only indexed copy. Check ``pg_indexes`` for a gist
    index on THIS table instead, and let PostgreSQL pick a collision-free
    name. Called from both add_4326_column and _apply_reupload_swap, so any
    re-ingest self-heals a missing index.

    The no-geom_4326 early return is defensive, not reachable (#1020):
    add_4326_column has just added the column, and the swap call is gated
    on a geometry_type extract_metadata can't report without geom_4326.
    """
    has_col = await session.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :tn "
            "AND column_name = 'geom_4326'"
        ).bindparams(schema=schema, tn=table_name)
    )
    if has_col.first() is None:
        return False

    has_gist = await session.execute(
        text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = :schema AND tablename = :tn "
            "AND indexdef LIKE '%USING gist (geom_4326)%'"
        ).bindparams(schema=schema, tn=table_name)
    )
    if has_gist.first() is None:
        await session.execute(
            text(
                # codeql[py/sql-injection] fix(#1615): identifiers validated by _qtable (metadata_sql.py)
                f"CREATE INDEX ON {_qtable(table_name, schema)} USING GIST (geom_4326)"
            )
        )
        return True
    return False


async def grant_reader_access(
    session: AsyncSession,
    table_name: str,
    *,
    schema: str = "data",
    role: str = "geolens_reader",
) -> None:
    """Grant SELECT on the table to the appropriate reader role.

    DBM-12: defense-in-depth alongside ``ALTER DEFAULT PRIVILEGES`` in
    ``scripts/init-db.sh``, redundant when the runtime ingest role matches
    the init-db role but the only grant path when a deployment's roles
    differ. ``schema``/``role`` default to single_tenant's 'data'/
    'geolens_reader'; multi_tenant callers pass tenant_data_schema(tid)/
    tenant_reader_role(tid).
    """
    await session.execute(
        # codeql[py/sql-injection] fix(#1615): table via _qtable (metadata_sql.py); role is server-derived (tenant_reader_role)
        text(f"GRANT SELECT ON {_qtable(table_name, schema)} TO {role}")
    )
    # No internal commit: the caller (_finalize_ingest at tasks_common.py:821)
    # owns the phase-2 commit boundary so a downstream failure rolls back
    # this GRANT atomically.
