"""Add GIN index on simple-regconfig tsvector for non-English search (SEC-S12).

The English FTS path is served by ``idx_records_search_vector`` (migration 0010),
which indexes ``to_tsvector('english', ...)`` stored as a generated column.  The
simple-regconfig path — used by ``_build_text_filter`` for CJK, accented Latin,
and other scripts that the English stemmer cannot tokenize — has no corresponding
index, causing every non-English query to trigger a sequential scan on
``catalog.records``.

This migration adds ``ix_records_simple_search_vector``, a functional GIN index
on a ``to_tsvector('simple', ...)`` expression covering title, summary,
lineage_summary, and theme_category (the same columns as the runtime expression
in ``service_filters.py:78-87``).

**Expression design note:**

Postgres functional indexes only accept IMMUTABLE expressions.  Both
``concat_ws`` and ``array_to_string`` are STABLE, not IMMUTABLE, so the original
``concat_ws('simple', ..., array_to_string(theme_category, ' '), ...)`` form used
by the SQLAlchemy runtime cannot be used directly in a functional index.

Two-part fix:

1. This migration defines a helper ``catalog.immutable_text_array_join(text[],
   text)`` — an IMMUTABLE SQL wrapper around ``array_to_string`` — and uses
   ``||`` string concatenation (IMMUTABLE) instead of ``concat_ws`` (STABLE).

2. The runtime expression in ``service_filters.py:78-87`` is updated to match
   this ``||``-based form (with ``immutable_text_array_join`` for theme_category)
   so the expression trees are identical and the planner can use the index.

Index expression (must match the runtime exactly):
    to_tsvector('simple',
        coalesce(title, '') || ' ' ||
        coalesce(summary, '') || ' ' ||
        coalesce(lineage_summary, '') || ' ' ||
        coalesce(catalog.immutable_text_array_join(theme_category, ' '), '')
    )

Phase 1062-03 / SEC-S12 (CVSS 5.0).

``CREATE INDEX CONCURRENTLY`` is intentionally omitted — the records table is
small in all current deployments and the maintenance-window block is acceptable.
For deployments approaching 1M+ rows, replace with CONCURRENTLY + a subsequent
``ANALYZE catalog.records``.
"""

from typing import Union

from alembic import op

revision: str = "0020_records_simple_search_vector_idx"
down_revision: Union[str, None] = "0019_users_token_version"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # IMMUTABLE wrapper around STABLE array_to_string() so PG accepts it in
    # functional indexes. The text[] -> text join behaviour is deterministic
    # for a fixed array and separator, which is all we need here.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION catalog.immutable_text_array_join(arr text[], sep text)
            RETURNS text
            LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
            AS $$ SELECT array_to_string(arr, sep) $$
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_records_simple_search_vector
        ON catalog.records
        USING gin (
            to_tsvector(
                'simple',
                coalesce(title, '') || ' ' ||
                coalesce(summary, '') || ' ' ||
                coalesce(lineage_summary, '') || ' ' ||
                coalesce(catalog.immutable_text_array_join(theme_category, ' '), '')
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS catalog.ix_records_simple_search_vector"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS catalog.immutable_text_array_join(text[], text)"
    )
