"""Drop redundant idx_<table>_gid btree indexes in the data schema.

Every dynamically-created ``data.<table>`` ingest table has both:

* ``gid SERIAL PRIMARY KEY`` -- auto-creates a btree on ``gid``.
* ``CREATE INDEX idx_<table>_gid ON <table> (gid)`` -- explicit second
  btree on the same column. This was added in Phase 180 OPT-03 with the
  intent of helping ORDER BY / keyset pagination. PostgreSQL uses the
  PK btree for ``ORDER BY gid`` just fine, so the secondary index is pure
  waste: extra disk, extra write maintenance, zero query benefit.

This migration drops every ``idx_*_gid`` index in the ``data`` schema.
The companion change in ``backend/app/processing/ingest/metadata.py``
removes the ``CREATE INDEX`` line so future ingests do not recreate
the redundant index.

Downgrade is intentionally a no-op: enumerating which ``data.*`` tables
existed and recreating the redundant indexes is not a meaningful undo
target. To re-introduce the indexes (not recommended), restore the
``metadata.py`` line and re-ingest.

Closes v13.13 DBM-05 (db-audit MED-05).
"""

from typing import Union

from alembic import op


revision: str = "0016_drop_redundant_data_gid_indexes"
down_revision: Union[str, None] = "0015_audit_username_trgm_indexes"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # Iterate every idx_<table>_gid index in the data schema and drop it.
    # The PK btree on gid SERIAL PRIMARY KEY remains and covers all
    # query paths (equality lookup + ORDER BY) the redundant index served.
    op.execute(
        """
        DO $$
        DECLARE
            idx_record RECORD;
        BEGIN
            FOR idx_record IN
                SELECT schemaname, indexname
                FROM pg_indexes
                WHERE schemaname = 'data'
                  AND indexname LIKE 'idx_%_gid'
            LOOP
                EXECUTE format(
                    'DROP INDEX IF EXISTS %I.%I',
                    idx_record.schemaname, idx_record.indexname
                );
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # No-op: we cannot enumerate which data.* tables existed in the
    # post-upgrade state without losing schema information that is not
    # captured here. To restore the indexes (not recommended), revert
    # the metadata.py change and re-ingest.
    pass
