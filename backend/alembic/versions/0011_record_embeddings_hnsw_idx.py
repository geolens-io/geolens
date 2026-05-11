"""Create HNSW vector index on record_embeddings.embedding (when dimensioned).

Pre-fix the HNSW index was created lazily in application code (in
``backend/app/processing/embeddings/backfill._rebuild_hnsw_index`` and
``service.rebuild_embedding_column``) only after the first backfill or
column resize. Fresh installs / test DBs shipped with no vector index,
so semantic search via the ``<=>`` cosine operator silently fell back
to a brute-force seq scan, and ``alembic upgrade head`` did not produce
a complete schema.

This migration moves the create-on-empty-table path into Alembic. It is
guarded because pgvector's HNSW requires the column to have a known
dimension (typmod). The column starts as ``Vector()`` (typmod=-1) until
the first ``rebuild_embedding_column`` call sets the dimension, so:

* When run after the dimension is set → creates the index.
* When run on a virgin column (typmod=-1) → no-op (logs a notice). The
  index is then created exactly once by ``rebuild_embedding_column`` the
  first time AI embeddings are configured. From that point forward, the
  index lives in the schema and any future Alembic re-run is a no-op via
  ``CREATE INDEX IF NOT EXISTS``.

The runtime ``rebuild_embedding_column`` path keeps the DROP + recreate
because dimension change requires a fresh index — that's a config-time
event the migration cannot reproduce.

Closes v13.12 finding H-08 (db-audit HIGH-03) and migration-audit M-02.
"""

from typing import Union

from alembic import op


revision: str = "0011_record_embeddings_hnsw_idx"
down_revision: Union[str, None] = "0010_trgm_search_indexes"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # Only build the HNSW index if the column has been dimensioned.
    # pgvector raises "column does not have dimensions" if typmod is -1.
    # Skipping in the virgin case is safe: rebuild_embedding_column will
    # create the index on the first AI-provider configuration.
    op.execute(
        """
        DO $$
        DECLARE
            tm integer;
        BEGIN
            SELECT atttypmod INTO tm
            FROM pg_attribute
            WHERE attrelid = 'catalog.record_embeddings'::regclass
              AND attname = 'embedding';

            IF tm IS NOT NULL AND tm <> -1 THEN
                CREATE INDEX IF NOT EXISTS ix_record_embeddings_hnsw
                  ON catalog.record_embeddings USING hnsw
                  (embedding vector_cosine_ops)
                  WITH (m = 16, ef_construction = 64);
            ELSE
                RAISE NOTICE 'Skipping ix_record_embeddings_hnsw: vector column has no dimension yet (will be created by rebuild_embedding_column on first AI-provider config).';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_record_embeddings_hnsw")
