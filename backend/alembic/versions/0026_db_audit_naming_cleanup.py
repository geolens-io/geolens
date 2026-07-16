"""db-audit-20260716 naming cleanup: duplicate slug index + staging pkey names.

Two findings from the 2026-07-16 DB audit:

BLOAT-1 — `ix_catalog_map_icon_assets_slug` fully duplicated the backing index
of `uq_map_icon_assets_slug` on the same column; every write maintained both.

BLOAT-3 — `ALTER TABLE ... RENAME TO` at ingest publish kept each table's PK
constraint (and backing index) named after its attempt-scoped staging table
(`*_staging_<uuid>_pkey`). Those names are user-visible to anyone connecting
directly with QGIS/pgAdmin/DBeaver. Ingest now renames the constraint at
publish (`rename_pkey_to_match_table` in tasks_common.py); this migration
fixes the tables published before that change, across all tenant schemas.

Downgrade drops back to the pre-audit index but does NOT restore the staging
pkey names — the attempt UUIDs are gone and the names are cosmetic.

Revision ID: 0026_db_audit_naming_cleanup
Revises: 0025_dataset_tile_cache_version
Create Date: 2026-07-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_db_audit_naming_cleanup"
down_revision: Union[str, None] = "0025_dataset_tile_cache_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        "ix_catalog_map_icon_assets_slug",
        table_name="map_icon_assets",
        schema="catalog",
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            r"""
            SELECT n.nspname, c.relname, con.conname
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE con.contype = 'p'
              AND con.conname LIKE '%\_staging\_%' ESCAPE '\'
              AND c.relname NOT LIKE '%\_staging\_%' ESCAPE '\'
              -- Only GeoLens-owned data schemas ('data', or 'data_t_<tenant>'
              -- per tenant_data_schema); a co-hosted non-GeoLens schema could
              -- legitimately contain '_staging_' pkey names we must not touch.
              AND (n.nspname = 'data' OR n.nspname LIKE 'data\_t\_%' ESCAPE '\')
            """
        )
    ).fetchall()
    for schema, table, conname in rows:
        desired = f"{table[:58]}_pkey"
        if conname == desired:
            continue
        # Skip if the target index name is already taken in this schema
        # (e.g. an orphaned *_old table) rather than fail the migration.
        taken = conn.execute(
            sa.text(
                "SELECT 1 FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :name"
            ),
            {"schema": schema, "name": desired},
        ).scalar()
        if taken:
            continue
        conn.execute(
            sa.text(
                f'ALTER TABLE "{schema}"."{table}" '
                f'RENAME CONSTRAINT "{conname}" TO "{desired}"'
            )
        )


def downgrade() -> None:
    op.create_index(
        "ix_catalog_map_icon_assets_slug",
        "map_icon_assets",
        ["slug"],
        schema="catalog",
    )
