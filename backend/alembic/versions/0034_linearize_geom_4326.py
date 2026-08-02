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
            ORDER BY c.table_schema, c.table_name
            """
        )
    ).all()
    for schema, table in tables:
        conn.execute(
            sa.text(
                f"UPDATE {_quote_ident(schema)}.{_quote_ident(table)} "
                f"SET geom_4326 = ST_CurveToLine(geom_4326) "
                f"WHERE ST_HasArc(geom_4326) "
                f"   OR GeometryType(geom_4326) IN "
                f"      ('CIRCULARSTRING','COMPOUNDCURVE','CURVEPOLYGON',"
                f"       'MULTICURVE','MULTISURFACE') "
                f"   OR GeometryType(geom_4326) = 'GEOMETRYCOLLECTION'"
            )
        )


def downgrade() -> None:
    # Data-only normalization; nothing to restore (see module docstring).
    pass
