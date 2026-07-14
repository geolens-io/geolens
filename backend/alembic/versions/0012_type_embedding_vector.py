"""Give record_embeddings.embedding a fixed dimension so HNSW can exist.

fix(#448 perf-audit): the baseline creates ``embedding`` as unbounded
``vector`` (atttypmod=-1) and skips the HNSW index with a NOTICE, expecting
``rebuild_embedding_column`` to type the column "on first AI-provider
config". That hook only fires when the dimension CHANGES via the settings
UI, so a deployment running on defaults never gets a typed column — and an
HNSW/ivfflat index can never be built (pgvector requires a typed column).
Semantic search then does an O(N) x dims cosine scan per query, twice.

This migration types the column in place, preferring (in order):

1. An explicitly configured dimension: the ``embedding_dims``
   persistent-config override (skipped when ``ENV_ONLY_CONFIG`` is set,
   mirroring runtime resolution in persistent_config.py), then an
   explicitly-set ``EMBEDDING_DIMS`` env value (detected via pydantic's
   ``model_fields_set``, so a deliberate ``EMBEDDING_DIMS=1536`` counts
   even though it equals the default). Explicit config beats stored
   rows — stale cache rows from a superseded model must not pin the
   column to the old dimension (the current model's inserts would fail
   until a manual rebuild).
2. The dimension of vectors already stored, when they all agree. Stored
   rows beat only the BUILT-IN default: a local model emitting 768-dim
   vectors with nothing configured anywhere must keep its rows.
3. The Settings default (1536, text-embedding-3-small).

Rows whose dimension disagrees with the chosen value are deleted —
embeddings are a regenerable cache (content-hash backfill restores them).
Deployments whose column is already typed (the settings-UI path ran) are
left untouched except for ensuring the index.

Revision ID: 0012_type_embedding_vector
Revises: 0011_allow_generic_geometry_type
Create Date: 2026-07-10
"""

import os
from typing import Sequence, Union

from alembic import op

revision: str = "0012_type_embedding_vector"
down_revision: Union[str, None] = "0011_allow_generic_geometry_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_ENV_VALUES = frozenset({"0", "false", "no", "off"})


def _explicit_embedding_dims() -> int | None:
    """Return an explicitly exported embedding dimension, if one exists.

    Keep this parser migration-local: topology-only Alembic commands import every
    revision module and must not need the mutable application Settings object.
    """
    raw = os.environ.get("EMBEDDING_DIMS")
    if raw is None or not raw.strip():
        return None
    try:
        dims = int(raw)
    except ValueError as exc:
        raise RuntimeError("EMBEDDING_DIMS must be an integer from 1 to 4096") from exc
    if not 1 <= dims <= 4096:
        raise RuntimeError("EMBEDDING_DIMS must be an integer from 1 to 4096")
    return dims


def _env_only_config_enabled() -> bool:
    """Parse ENV_ONLY_CONFIG without importing application configuration."""
    raw = os.environ.get("ENV_ONLY_CONFIG")
    if raw is None or not raw.strip():
        return False
    normalized = raw.strip().lower()
    if normalized in _TRUE_ENV_VALUES:
        return True
    if normalized in _FALSE_ENV_VALUES:
        return False
    raise RuntimeError(
        "ENV_ONLY_CONFIG must be one of true/false, 1/0, yes/no, or on/off"
    )


def upgrade() -> None:
    # fix(#449, codex P2): honor the deployment's configured dimension, not a
    # hardcoded 1536, and let explicit config beat stale stored rows. Mirror
    # runtime resolution (persistent_config.py): ENV_ONLY_CONFIG ignores DB
    # overrides. Compose passes EMBEDDING_DIMS through only when the operator
    # set it, so a deliberate EMBEDDING_DIMS=1536 remains distinguishable from
    # the frozen fallback below.
    explicit = _explicit_embedding_dims()
    explicit_env_dims = str(explicit) if explicit is not None else "NULL"
    consult_db = "false" if _env_only_config_enabled() else "true"
    op.execute(
        f"""
        DO $$
        DECLARE
          cur_typmod int;
          dims int;
          stored_dims int;
          distinct_dims int;
          config_dims int;
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

            SELECT count(DISTINCT vector_dims(embedding)),
                   max(vector_dims(embedding))
              INTO distinct_dims, stored_dims
            FROM catalog.record_embeddings;

            -- fix(#449, codex P2): explicit config (app_settings override
            -- unless env-only, then an explicitly-set EMBEDDING_DIMS) beats
            -- stored rows — stale cache rows from a superseded model must
            -- not pin the column to the old dimension.
            IF {consult_db} THEN
              -- PersistentConfig wraps scalars as {{"v": <value>}} (see
              -- persistent_config.py set()); older/manual rows may hold a
              -- bare number. Handle both shapes.
              SELECT CASE jsonb_typeof(value)
                       WHEN 'object' THEN (value #>> '{{v}}')::int
                       WHEN 'number' THEN (value #>> '{{}}')::int
                       ELSE NULL
                     END
              INTO config_dims
              FROM catalog.app_settings WHERE key = 'embedding_dims';
            END IF;
            IF config_dims IS NULL THEN
              config_dims := {explicit_env_dims};
            END IF;

            -- Stored rows (when they all agree) beat only the built-in
            -- default; mixed dimensions mean a model switch, so they never
            -- pick the dimension themselves.
            dims := COALESCE(
              config_dims,
              CASE WHEN distinct_dims = 1 THEN stored_dims END,
              1536
            );
            IF dims < 1 THEN
              dims := 1536;
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
          -- fix(#449, codex P1): pgvector rejects HNSW on vector columns over
          -- 2000 dims (3072-dim models are legal config, cap is 4096) — skip
          -- the index rather than fail the upgrade; semantic search falls
          -- back to exact scans. Re-probe: the ALTER above may have typed it.
          SELECT atttypmod INTO cur_typmod
          FROM pg_attribute
          WHERE attrelid = 'catalog.record_embeddings'::regclass
            AND attname = 'embedding';

          IF cur_typmod BETWEEN 1 AND 2000 THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS ix_record_embeddings_hnsw '
                    'ON catalog.record_embeddings USING hnsw '
                    '(embedding vector_cosine_ops) '
                    'WITH (m = 16, ef_construction = 64)';
          ELSE
            RAISE NOTICE 'Skipping ix_record_embeddings_hnsw: % dims exceeds pgvector''s 2000-dim HNSW limit; semantic search stays on exact scans.', cur_typmod;
          END IF;
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
