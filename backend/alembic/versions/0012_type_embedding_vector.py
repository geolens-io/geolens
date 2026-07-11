"""Give record_embeddings.embedding a fixed dimension so HNSW can exist.

fix(#448 perf-audit): the baseline creates ``embedding`` as unbounded
``vector`` (atttypmod=-1) and skips the HNSW index with a NOTICE, expecting
``rebuild_embedding_column`` to type the column "on first AI-provider
config". That hook only fires when the dimension CHANGES via the settings
UI, so a deployment running on defaults never gets a typed column — and an
HNSW/ivfflat index can never be built (pgvector requires a typed column).
Semantic search then does an O(N) x dims cosine scan per query, twice.

This migration types the column in place, preferring (in order) the
dimension of vectors already stored, the ``embedding_dims`` persistent
config override (skipped when ``ENV_ONLY_CONFIG`` is set, mirroring
runtime resolution in persistent_config.py), and finally the configured
``EMBEDDING_DIMS`` env value / Settings default (1536,
text-embedding-3-small). Rows whose dimension disagrees with the chosen
value are deleted — embeddings are a regenerable cache (content-hash
backfill restores them). Deployments whose column is already typed (the
settings-UI path ran) are left untouched except for ensuring the index.

Revision ID: 0012_type_embedding_vector
Revises: 0011_allow_generic_geometry_type
Create Date: 2026-07-10
"""

from typing import Sequence, Union

from alembic import op

from app.core.config import settings

revision: str = "0012_type_embedding_vector"
down_revision: Union[str, None] = "0011_allow_generic_geometry_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # fix(#449, codex P2): the empty-table fallback must honor the deployment's
    # configured dimension, not a hardcoded 1536 — a fresh install running a
    # 384/768-dim model via EMBEDDING_DIMS would otherwise get the column
    # permanently mistyped before any data exists. Mirror runtime resolution
    # (persistent_config.py): ENV_ONLY_CONFIG ignores DB overrides.
    fallback_dims = settings.embedding_dims if settings.embedding_dims >= 1 else 1536
    consult_db = "false" if settings.env_only_config else "true"
    op.execute(
        f"""
        DO $$
        DECLARE
          cur_typmod int;
          dims int;
        BEGIN
          SELECT atttypmod INTO cur_typmod
          FROM pg_attribute
          WHERE attrelid = 'catalog.record_embeddings'::regclass
            AND attname = 'embedding';

          IF cur_typmod = -1 THEN
            -- Acquire the strongest lock up front: DELETE-then-ALTER would
            -- otherwise escalate ROW EXCLUSIVE -> ACCESS EXCLUSIVE mid-flight,
            -- a deadlock-prone pattern if anything is reading the table.
            LOCK TABLE catalog.record_embeddings IN ACCESS EXCLUSIVE MODE;

            -- Prefer the dimension of data already stored; fall back to the
            -- embedding_dims persistent-config override (unless env-only),
            -- then the configured EMBEDDING_DIMS / app default.
            SELECT max(vector_dims(embedding)) INTO dims
            FROM catalog.record_embeddings;
            IF dims IS NULL AND {consult_db} THEN
              -- PersistentConfig wraps scalars as {{"v": <value>}} (see
              -- persistent_config.py set()); older/manual rows may hold a
              -- bare number. Handle both shapes.
              SELECT CASE jsonb_typeof(value)
                       WHEN 'object' THEN (value #>> '{{v}}')::int
                       WHEN 'number' THEN (value #>> '{{}}')::int
                       ELSE NULL
                     END
              INTO dims
              FROM catalog.app_settings WHERE key = 'embedding_dims';
            END IF;
            IF dims IS NULL OR dims < 1 THEN
              dims := {fallback_dims};
            END IF;

            DELETE FROM catalog.record_embeddings
            WHERE vector_dims(embedding) <> dims;

            EXECUTE format(
              'ALTER TABLE catalog.record_embeddings '
              'ALTER COLUMN embedding TYPE vector(%s) USING embedding::vector(%s)',
              dims, dims
            );
          END IF;

          -- Same DDL the baseline and rebuild_embedding_column intend.
          EXECUTE 'CREATE INDEX IF NOT EXISTS ix_record_embeddings_hnsw '
                  'ON catalog.record_embeddings USING hnsw '
                  '(embedding vector_cosine_ops) '
                  'WITH (m = 16, ef_construction = 64)';
        END $$;
        """
    )


def downgrade() -> None:
    # Back to the baseline shape: untyped column, no ANN index. Stored
    # vectors survive the widening cast unchanged.
    op.execute("DROP INDEX IF EXISTS catalog.ix_record_embeddings_hnsw")
    op.execute(
        "ALTER TABLE catalog.record_embeddings "
        "ALTER COLUMN embedding TYPE vector USING embedding::vector"
    )
