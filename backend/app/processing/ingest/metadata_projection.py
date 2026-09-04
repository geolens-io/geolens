"""The 4326 render column and the reader grant.

Split out of ``metadata.py`` (#1042): what ``_finalize_ingest`` does last, to
make a landed table readable by the tile, feature and analysis surfaces.
``add_4326_column`` writes the render column (2D and linear, with its GIST
index); ``linearize_existing_4326`` enforces that same invariant on a column
the pipeline never wrote, since registration skips ``add_4326_column`` when a
BYO table already carries one; ``rederive_geom_4326`` re-applies the whole
invariant to a registered table its owner has written to since (#1738);
``grant_reader_access`` hands the finished table to the reader role.
"""

from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ingest.metadata_sql import _qtable


def _geom_4326_expr(source_srid: int) -> str:
    """The expression that derives ``geom_4326`` from ``geom``.

    One definition, because two paths write the column from the source
    geometry — the registration/ingest write (:func:`add_4326_column`) and the
    out-of-band repair (:func:`rederive_geom_4326`) — and a drift between them
    would make a refresh rewrite every row of every table forever while
    "fixing" nothing.

    fix(#1113 review r16): linearize IN THE SOURCE CRS, then reproject. An
    arc is defined by its control points, and CRS transforms are nonlinear:
    transforming the control points first and densifying after traces the
    arc in the wrong space, so ST_CurveToLine(ST_Transform(...)) yields a
    materially different shape from the correct
    ST_Transform(ST_CurveToLine(...)).
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

    If source_srid is 4326, copies geom directly (ensuring SRID is set).
    Otherwise, reprojects via ST_Transform.

    The 4326 column is declared 2D (`geometry(Geometry, 4326)`) — it backs
    tile/map rendering, which is inherently 2D. If the source `geom` is 3D
    (e.g. SRID 4979 with elevation), `ST_Force2D` strips Z so the UPDATE
    doesn't fail with `Geometry has Z dimension but column does not`. Z is
    still preserved in the original `geom` column.

    fix(#1104): the column is also always LINEAR. WFS ingest admits curved
    geometries (MultiSurface/CompoundCurve), and every surface that reads
    geom_4326 raises on them: ST_AsMVTGeom (vector tiles), ST_AsGeoJSON
    (feature reads), ``::geography`` and ST_MakeValid (analysis).
    `ST_CurveToLine` densifies arcs here, at the one boundary they all read
    from; it is an exact no-op on already-linear input, and the curved
    source stays in the original `geom` column, same as Z does.
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

    # DBM-05 (Phase 271): the previously-created `idx_<table>_gid` btree
    # was redundant with the PK btree on `gid SERIAL PRIMARY KEY`. Removed
    # so new ingests no longer ship the duplicate. Migration 0001_baseline drops
    # the leftovers from existing tables.

    # ING-02 / P2-02 (Phase 1076): no internal commit. The caller
    # (_finalize_ingest at tasks_common.py:821) owns the phase-2 commit
    # boundary so a downstream failure rolls back the ALTER + UPDATE +
    # CREATE INDEX above atomically.


REPAIR_APPLIED = "applied"
REPAIR_NO_GEOMETRY = "no_geometry"
REPAIR_GENERATED = "generated"


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
) -> Geom4326Repair:
    """Re-apply the geom_4326 invariant to a table written to outside GeoLens.

    fix(#1738): ``geom_4326`` is a plain column, populated once — by
    :func:`add_4326_column` at registration, and afterwards only by GeoLens's
    own feature-edit writes. A registered table's owner keeps writing to it
    directly (registration copies no data and serves from the live relation),
    and nothing re-derives the column for those writes. An ``UPDATE geom``, a
    ``DELETE`` plus re-``INSERT``, and ``ogr2ogr -overwrite`` (which drops the
    table and recreates it without the column, its index, or the reader grant)
    all leave rows whose render geometry is stale or NULL. Every reader
    filters on ``geom_4326 && <envelope>`` and ``NULL && anything`` is NULL,
    so those rows are silently invisible rather than visibly wrong.

    This is that invariant re-applied from OUTSIDE the table, which is what
    makes it survive ``-overwrite``: the same ADD COLUMN, the same expression
    and the same index-if-absent registration uses, each idempotent, so a
    recreated table gets its column and index back rather than needing the
    dataset deleted and registered again.

    **The UPDATE is scoped to rows whose stored value would actually change**,
    compared through ``ST_AsBinary`` — that is what keeps a refresh of an
    untouched table to one sequential scan with no writes and no bloat, which
    in turn is what makes this safe to run on every refresh rather than behind
    a separate button. The scope is deliberately NOT ``geom_4326 IS NULL OR
    ...``: a row whose ``geom`` is NULL has a NULL render geometry that is
    already correct, and the IS NULL disjunct would rewrite every such row
    NULL-to-NULL on every pass — a write that changes nothing, and a drift
    count that lies.

    A STORED GENERATED ``geom_4326`` is skipped for the reason
    :func:`linearize_existing_4326` skips it: PostgreSQL rejects any
    non-DEFAULT write to a generated column at parse time, and such a column
    re-derives itself on every write anyway, so there is nothing to repair.

    A table with no ``geom`` column is skipped too — registration admits
    non-spatial tables (#1359), and #1737 refuses a spatial table whose
    geometry lives under another name, so "no geom" here means an attribute
    table rather than a broken one.

    One benign interaction, recorded because it looks like drift and is not:
    GeoLens's own feature edits write ``geom_4326`` from the request's GeoJSON
    and ``geom`` by transforming that into the dataset's SRID
    (``features/service.py``), so on a projected dataset the stored render
    value is the original rather than a round trip. The first pass after such
    an edit normalizes it to ``ST_Transform(geom, 4326)`` — a sub-millimetre
    change, counted as one drifted row — and then converges, because the next
    pass compares that expression against itself.

    The caller owns the transaction, the statement deadline and the reader
    GRANT; this function only touches the column and its index.
    """
    tref = _qtable(table_name, schema=schema)

    # One probe for all three questions, and the same pair of column names
    # registration looks for. ``udt_name`` is checked because a plain column
    # that happens to be called ``geom`` is not a geometry: Find_SRID would
    # raise on it, and the UPDATE below would too.
    probe = (
        await session.execute(
            text(
                "SELECT column_name, udt_name, is_generated "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "  AND column_name IN ('geom', 'geom_4326')"
            ).bindparams(schema=schema, table=table_name)
        )
    ).all()
    columns = {row.column_name: row for row in probe}

    source = columns.get("geom")
    if source is None or source.udt_name != "geometry":
        return Geom4326Repair(REPAIR_NO_GEOMETRY, False, False, 0)

    render = columns.get("geom_4326")
    if render is not None and render.is_generated == "ALWAYS":
        return Geom4326Repair(REPAIR_GENERATED, False, False, 0)

    if render is None:
        # Gated on the probe, NOT left to ``IF NOT EXISTS``: ALTER TABLE takes
        # ACCESS EXCLUSIVE whether or not it changes anything, and a lock
        # request that is merely QUEUED already blocks every reader arriving
        # behind it. Issuing it on the ordinary path — a registered table that
        # still has its column — would put a brief stop-the-world on somebody
        # else's table on every refresh. ``IF NOT EXISTS`` stays as the race
        # guard for a column added between the probe and here.
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
        render is None,
        index_added,
        result.rowcount if result.rowcount and result.rowcount > 0 else 0,
    )


async def linearize_existing_4326(
    session: AsyncSession, table_name: str, *, schema: str = "data"
) -> None:
    """Enforce the geom_4326-is-always-linear invariant on a column we did not write.

    fix(#1113 review): ``register_existing_table`` skips :func:`add_4326_column`
    when the table already carries geom_4326, so a table created or copied into
    the data schema AFTER migration 0034 ran could re-introduce curved values
    the backfill can no longer see — and the per-read ST_CurveToLine wraps that
    used to absorb them are gone. Registration is the app's write boundary for
    such tables, so the invariant is enforced here, with the same predicate as
    the migration: any arc, any top-level curve type, or any
    GEOMETRYCOLLECTION (curve members cannot hide anywhere else — linear multi
    types cannot contain them). Exact no-op on already-linear rows.

    A BYO column may also DECLARE a curved typmod — geometry(CurvePolygon,
    4326) — which would reject the linear UPDATE result outright; such a
    column is loosened to a generic typmod first, PRESERVING its Z/M flags
    (geometry_columns reports M as a type suffix and Z only via
    coord_dimension, and a plain Geometry typmod rejects Z values). Only the
    concrete curve typmods need it (abstract CURVE/SURFACE accept their
    linear subtypes); rtrim(type,'M') matches the M-suffixed variants — no
    base curve name ends in M.
    """
    tref = _qtable(table_name, schema=schema)
    # fix(#1113 review r7): a STORED GENERATED geom_4326 rejects any UPDATE at
    # parse time (even one whose WHERE matches nothing), and its values are
    # decided by its generation expression, so it can be neither repaired nor
    # safely retyped here — skip it (#1114 tracks expressions that yield
    # curves).
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
        # fix(#1113 review r8): a generated column whose CURRENT rows are
        # curved would register a dataset broken on every surface, and no
        # later write of ours can fix it — refuse with the actionable cause
        # instead. An empty or linear generated column registers fine; an
        # expression that only yields curves for FUTURE rows is #1114's
        # residue, same as any post-registration external write.
        # fix(#1113 review r9): the test is "would linearization change the
        # value", byte-for-byte — it catches arcs, top-level curve types, AND
        # curve containers nested inside a GEOMETRYCOLLECTION with one
        # comparison, while an all-linear collection (which ST_CurveToLine
        # returns unchanged) stays registrable. A type list here would either
        # miss the nested case or over-reject linear collections.
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

    Returns whether an index was created. fix(#1738): the repair path reports
    what it restored on a table recreated behind GeoLens's back, and "the
    spatial index was missing" is the part of that report an operator can act
    on. Every other caller ignores the value.

    fix(#448): the previous ``CREATE INDEX IF NOT EXISTS idx_<table>_geom_4326``
    matched by NAME schema-wide, not per-table. On a second re-ingest the
    previous swap's index (created against ``<table>_staging`` and carried
    along by the RENAME) still held that name, so the new staging table
    silently got NO spatial index — and the swap then dropped the only
    indexed copy of the data. Check ``pg_indexes`` for a gist index on THIS
    table instead, and let PostgreSQL pick a collision-free index name.
    Called from both add_4326_column (staging load) and _apply_reupload_swap
    (post-swap belt-and-braces), so any re-ingest self-heals a missing index.

    The no-geom_4326 early return is defensive, not a reachable state (#1020):
    add_4326_column has just added the column, and the swap call is gated on a
    geometry_type that extract_metadata cannot report without reading geom_4326.
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

    DBM-12 (Phase 271): Kept as a defense-in-depth measure alongside
    ``ALTER DEFAULT PRIVILEGES`` in ``scripts/init-db.sh``. If the runtime
    ingest role matches the init-db role, this call is redundant; if they
    differ (some custom deployment topologies), this is the only path that
    grants SELECT on freshly-created tables.

    In single_tenant: schema='data', role='geolens_reader' (unchanged behavior).
    In multi_tenant: callers pass schema=tenant_data_schema(tid),
                     role=tenant_reader_role(tid).

    Parameters
    ----------
    session:
        Active async SQLAlchemy session (caller controls the transaction).
    table_name:
        The table to GRANT SELECT on. Validated by _qtable.
    schema:
        Schema containing the table. Defaults to 'data' (single_tenant).
    role:
        Reader role to grant to. Defaults to 'geolens_reader' (single_tenant).
    """
    await session.execute(
        # codeql[py/sql-injection] fix(#1615): table via _qtable (metadata_sql.py); role is server-derived (tenant_reader_role)
        text(f"GRANT SELECT ON {_qtable(table_name, schema)} TO {role}")
    )
    # ING-02 / P2-02 (Phase 1076): no internal commit. The caller
    # (_finalize_ingest at tasks_common.py:821) owns the phase-2 commit
    # boundary so a downstream failure rolls back this GRANT atomically.
