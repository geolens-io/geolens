"""Linearize curved geom_4326 values in existing per-dataset tables.

fix(#1104): WFS ingest admitted curved geometries (MultiSurface /
CompoundCurve) into ``geom_4326``, and every surface that reads the column
raises on them: ST_AsMVTGeom (vector tiles), ST_AsGeoJSON (feature reads),
``::geography`` and ST_MakeValid (analysis). Ingest now applies
ST_CurveToLine when it builds the column; this backfills rows ingested
before that change so the geom_4326-is-always-linear invariant holds for
existing data too. The curved original stays in each table's ``geom``
column, untouched.

The per-dataset tables are dynamic, so they are discovered from
information_schema: every BASE TABLE with a geometry column named
``geom_4326`` in the ``data`` schema (single-tenant) or a ``data_t_%``
tenant schema (multi-tenant, see tenant_data_schema).

The predicate is the union of three tests, because each alone misses a
stored shape — fix(#1113 review): a curve TYPE with no arc in it
(``MULTISURFACE(((...)))``, a form the curved-sources suite itself uses)
still breaks every curve-intolerant reader, and ST_HasArc alone skips
it; a GeometryType list alone misses an arc nested inside a
GEOMETRYCOLLECTION, which reports the collection type. So: any arc
(ST_HasArc), any top-level curve type (the closed five-member list), or
any GEOMETRYCOLLECTION (linear members pass through ST_CurveToLine
unchanged; curve members cannot hide anywhere else — linear multi types
cannot contain them). Idempotent: converted rows leave the predicate,
and a GEOMETRYCOLLECTION re-converts to an identical value.

Downgrade is a deliberate no-op: densifying arcs is not losslessly
reversible, the curved source survives in ``geom``, and the catalog's
``geometry_type`` already declared the linear type for these datasets.

Revision ID: 0034_linearize_geom_4326
Revises: 0033_records_derived_from
Create Date: 2026-08-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034_linearize_geom_4326"
down_revision: Union[str, None] = "0033_records_derived_from"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def upgrade() -> None:
    import logging

    log = logging.getLogger("alembic.runtime.migration")
    conn = op.get_bind()
    tables = conn.execute(
        sa.text(
            """
            SELECT c.table_schema, c.table_name
            FROM information_schema.columns AS c
            JOIN information_schema.tables AS t
              ON t.table_schema = c.table_schema
             AND t.table_name = c.table_name
            WHERE c.column_name = 'geom_4326'
              AND c.udt_name = 'geometry'
              AND t.table_type = 'BASE TABLE'
              -- fix(#1113 review r7): a STORED GENERATED geom_4326 rejects
              -- any UPDATE at parse time (even WHERE false), which would
              -- abort this whole migration. It also cannot be fixed by
              -- UPDATE — its values are decided by its generation
              -- expression — so it is skipped, not repaired (#1114 tracks
              -- externally-defined columns whose expressions yield curves).
              AND c.is_generated = 'NEVER'
              -- fix(#1113 review): only GeoLens-owned data schemas — 'data'
              -- (single-tenant) or the EXACT per-tenant schemas derived from
              -- catalog.tenants, the same construction as tenant_data_schema()
              -- and migrations 0024/0026. A co-hosted schema that merely
              -- starts with 'data_t_' could hold a geom_4326 column whose
              -- curves this UPDATE would irreversibly densify.
              AND (c.table_schema = 'data'
                   OR c.table_schema IN (
                       SELECT 'data_t_' || pg_catalog.replace(id::text, '-', '_')
                       FROM catalog.tenants
                   ))
              -- fix(#1113 review r11): REGISTERED datasets only. An operator
              -- can copy a table into a data schema before registering it
              -- (discover_unregistered_tables exists for exactly that state);
              -- GeoLens serves nothing from it yet, registration now runs its
              -- own linearization, and densifying it here would be
              -- irreversible harm with no surface fixed. table_name is
              -- globally unique across tenants (registration's duplicate
              -- check), so the name join is the tenant-safe scope.
              AND c.table_name IN (SELECT table_name FROM catalog.datasets)
            ORDER BY c.table_schema, c.table_name
            """
        )
    ).all()
    for schema, table in tables:
        # fix(#1113 review): a BYO table can declare geom_4326 with a curved
        # TYPMOD — geometry(CurvePolygon, 4326) — and the linear UPDATE result
        # then violates the declared column type, aborting the whole
        # migration. Loosen such a column to generic geometry(Geometry, srid)
        # first; the concrete curve typmods are the only ones that reject
        # their linear counterparts (abstract CURVE/SURFACE typmods accept
        # linear subtypes), and loosening is a no-op risk-wise where the
        # UPDATE would have succeeded anyway.
        # fix(#1113 review r5): geometry_columns encodes dimensionality two
        # ways — M as a suffix on ``type`` (CURVEPOLYGONM, coord_dimension 3),
        # Z with NO suffix (coord_dimension 3), ZM with no suffix and
        # coord_dimension 4 — and generic geometry(Geometry, srid) REJECTS Z
        # values, so the loosened typmod must carry the original Z/M flags.
        # rtrim(type,'M') matches both plain and M-suffixed curve typmods; no
        # base curve name ends in M.
        typmod = conn.execute(
            sa.text(
                "SELECT type, srid, coord_dimension "
                "FROM public.geometry_columns "
                "WHERE f_table_schema = :schema "
                "  AND f_table_name = :table "
                "  AND f_geometry_column = 'geom_4326' "
                "  AND rtrim(type, 'M') IN ('CIRCULARSTRING','COMPOUNDCURVE',"
                "               'CURVEPOLYGON','MULTICURVE','MULTISURFACE')"
            ),
            {"schema": schema, "table": table},
        ).first()
        if typmod is not None:
            if typmod.coord_dimension == 4:
                generic = "GeometryZM"
            elif typmod.coord_dimension == 3:
                generic = "GeometryM" if typmod.type.endswith("M") else "GeometryZ"
            else:
                generic = "Geometry"
            conn.execute(
                sa.text(
                    f"ALTER TABLE {_quote_ident(schema)}.{_quote_ident(table)} "
                    f"ALTER COLUMN geom_4326 "
                    f"TYPE geometry({generic}, {int(typmod.srid)})"
                )
            )
        # rtrim on GeometryType for the same reason: an M curve reports
        # CURVEPOLYGONM, so the bare list would skip an arc-free M container.
        conn.execute(
            sa.text(
                f"UPDATE {_quote_ident(schema)}.{_quote_ident(table)} "
                f"SET geom_4326 = ST_CurveToLine(geom_4326) "
                f"WHERE ST_HasArc(geom_4326) "
                f"   OR rtrim(GeometryType(geom_4326), 'M') IN "
                f"      ('CIRCULARSTRING','COMPOUNDCURVE','CURVEPOLYGON',"
                f"       'MULTICURVE','MULTISURFACE') "
                f"   OR rtrim(GeometryType(geom_4326), 'M') = 'GEOMETRYCOLLECTION'"
            )
        )

    # fix(#1113 review r9): the loop above must SKIP stored generated columns
    # (any UPDATE against one aborts at parse time), but an already-registered
    # dataset whose generated expression yields curves stays broken with no
    # signal. Surface those tables to the operator — a SELECT cannot abort the
    # migration — and point at the tracking issue; repairing a column someone
    # else's expression owns is not this migration's call (#1114).
    generated = conn.execute(
        sa.text(
            """
            SELECT c.table_schema, c.table_name
            FROM information_schema.columns AS c
            JOIN information_schema.tables AS t
              ON t.table_schema = c.table_schema
             AND t.table_name = c.table_name
            WHERE c.column_name = 'geom_4326'
              AND c.udt_name = 'geometry'
              AND t.table_type = 'BASE TABLE'
              AND c.is_generated = 'ALWAYS'
              AND (c.table_schema = 'data'
                   OR c.table_schema IN (
                       SELECT 'data_t_' || pg_catalog.replace(id::text, '-', '_')
                       FROM catalog.tenants
                   ))
              -- fix(#1113 review r11): warn only about datasets GeoLens
              -- actually serves; an unregistered table's generated column is
              -- registration's problem when (if) it registers.
              AND c.table_name IN (SELECT table_name FROM catalog.datasets)
            """
        )
    ).all()
    for schema, table in generated:
        curved = conn.execute(
            sa.text(
                f"SELECT 1 FROM {_quote_ident(schema)}.{_quote_ident(table)} "
                f"WHERE ST_AsBinary(ST_CurveToLine(geom_4326)) "
                f"      <> ST_AsBinary(geom_4326) LIMIT 1"
            )
        ).first()
        if curved is not None:
            log.warning(
                "%s.%s: geom_4326 is a GENERATED column whose expression "
                "yields curved geometries; this backfill cannot repair it and "
                "tiles/feature reads/analysis will fail for that dataset. "
                "Adjust the generation expression to apply ST_CurveToLine "
                "(tracked in geolens#1114).",
                schema,
                table,
            )


def downgrade() -> None:
    # Data-only normalization; nothing to restore (see module docstring).
    pass
