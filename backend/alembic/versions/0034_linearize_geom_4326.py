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

Idempotent: the UPDATE touches only rows where ST_HasArc still reports an
arc, so a re-run matches nothing. ST_HasArc rather than a GeometryType IN
(...) list because it also sees curves nested inside a
GEOMETRYCOLLECTION, which GeometryType reports as the collection type.

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
              AND (c.table_schema = 'data'
                   OR c.table_schema LIKE 'data\\_t\\_%')
            ORDER BY c.table_schema, c.table_name
            """
        )
    ).all()
    for schema, table in tables:
        conn.execute(
            sa.text(
                f"UPDATE {_quote_ident(schema)}.{_quote_ident(table)} "
                f"SET geom_4326 = ST_CurveToLine(geom_4326) "
                f"WHERE ST_HasArc(geom_4326)"
            )
        )


def downgrade() -> None:
    # Data-only normalization; nothing to restore (see module docstring).
    pass
