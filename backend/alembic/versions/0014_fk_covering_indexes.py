"""FK covering btree indexes for high-priority join columns.

PostgreSQL does NOT auto-create btree indexes on foreign-key columns -- only
on primary keys and unique constraints. Without an FK-side index, every
cascade DELETE and every ``WHERE fk_col = ?`` join probe is a sequential
scan over the child table.

Three high-priority gaps from db-audit MED-04 / migration-audit M-04:

* ``vrt_generations.vrt_dataset_id`` -- VRT mosaic generation history,
  joined on every "list generations for this VRT" query and on cascade
  delete of the VRT dataset.
* ``refresh_tokens.user_id`` -- joined on every "this user's active
  refresh tokens" lookup and on cascade delete when a user account is
  removed.
* ``dataset_versions.dataset_id`` -- joined on every dataset detail
  page (version history list) and on cascade delete of the dataset.

These three were called out in the audit as high-cardinality / hot-path.
The remaining 10 unindexed FK columns are deferred (low query frequency
or covered by composite indexes already).

Closes v13.13 DBM-10 (db-audit MED-04, migration-audit M-04).
"""

from typing import Union

from alembic import op


revision: str = "0014_fk_covering_indexes"
down_revision: Union[str, None] = "0013_partial_indexes_embed_tokens_ingest_jobs"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # vrt_generations -> datasets (CASCADE).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vrt_generations_vrt_dataset_id "
        "ON catalog.vrt_generations (vrt_dataset_id)"
    )
    # refresh_tokens -> users (CASCADE).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id "
        "ON catalog.refresh_tokens (user_id)"
    )
    # dataset_versions -> datasets (CASCADE).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dataset_versions_dataset_id "
        "ON catalog.dataset_versions (dataset_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_dataset_versions_dataset_id")
    op.execute("DROP INDEX IF EXISTS catalog.ix_refresh_tokens_user_id")
    op.execute("DROP INDEX IF EXISTS catalog.ix_vrt_generations_vrt_dataset_id")
