"""Partial indexes for hot embed_tokens + ingest_jobs filter paths.

* ``ix_embed_tokens_active_expires`` -- partial btree on ``embed_tokens.expires_at``
  WHERE ``is_active = true``. Backs the per-request filter
  ``WHERE is_active = true AND expires_at > now()`` (token-validation hot path
  in ``backend/app/modules/embed_tokens/service.py``). The existing
  ``uq_embed_tokens_one_active_per_map`` partial UNIQUE indexes on
  ``map_id``, not ``expires_at`` -- this index closes the gap for time-range
  filters on active tokens.
* ``ix_ingest_jobs_status_active`` -- partial btree on ``ingest_jobs.status``
  WHERE ``status IN ('running','pending')``. Backs stale-job recovery scans.
  Most rows are ``complete`` or ``failed`` (ingest history); only the
  small ``running`` / ``pending`` working set needs to be indexed.

Both partials stay tiny on disk because they exclude the dominant
non-matching rows (inactive tokens / completed jobs), so they live in
shared_buffers indefinitely once warm.

Closes v13.13 DBM-02 (db-audit MED-03) and DBM-03 (db-audit MED-04).
"""

from typing import Union

from alembic import op


revision: str = "0013_partial_indexes_embed_tokens_ingest_jobs"
down_revision: Union[str, None] = "0012_dataset_tile_columns"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # DBM-02: embed_tokens active+expires partial index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embed_tokens_active_expires "
        "ON catalog.embed_tokens (expires_at) "
        "WHERE is_active = true"
    )
    # DBM-03: ingest_jobs status partial index for running/pending rows.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ingest_jobs_status_active "
        "ON catalog.ingest_jobs (status) "
        "WHERE status IN ('running', 'pending')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_ingest_jobs_status_active")
    op.execute("DROP INDEX IF EXISTS catalog.ix_embed_tokens_active_expires")
