"""GIN trigram indexes for accent-insensitive ILIKE search paths.

The catalog search filter (``backend/app/modules/catalog/search/service_filters.py``)
runs ``lower(unaccent(...)) LIKE '%term%'`` against ``Record.title``,
``Record.summary``, ``RecordKeyword.keyword``, and the contact name+org
concat. Maps list/search ILIKE-s ``Map.name`` and ``Map.description``.
``pg_trgm`` is installed but no GIN trigram indexes exist, so every search
query falls back to a sequential scan that scales with row count.

Adds:

* ``catalog.immutable_unaccent(text)`` — IMMUTABLE wrapper around the
  STABLE built-in ``unaccent()`` so functional indexes can reference it.
  Required because PostgreSQL functional indexes only accept IMMUTABLE
  expressions and the project already uses the same pattern for
  ``catalog.immutable_camel_to_spaced`` (see 0001_baseline.py).
* GIN trigram functional indexes on:
  * ``records.title`` (lower + unaccent)
  * ``records.summary`` (lower + unaccent + coalesce)
  * ``record_keywords.keyword`` (lower + unaccent)
  * ``maps.name`` (lower)
  * ``maps.description`` (lower + coalesce)

Closes v13.12 finding H-07 (db-audit HIGH-02).
"""

from typing import Union

from alembic import op


revision: str = "0010_trgm_search_indexes"
down_revision: Union[str, None] = "0009_audit_logs_indexes"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # IMMUTABLE wrapper around STABLE unaccent() so PG accepts it in
    # functional indexes. (PG's built-in unaccent is STABLE because it
    # reads dictionary configuration; we promise we'll never change the
    # dict so it's effectively immutable for our purposes.)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION catalog.immutable_unaccent(input text)
            RETURNS text
            LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
            AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, input); $$
        """
    )

    # records.title — every catalog search ILIKE-s this column.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_records_title_trgm "
        "ON catalog.records USING gin "
        "(lower(catalog.immutable_unaccent(title)) gin_trgm_ops)"
    )
    # records.summary — coalesce so NULL summaries don't break the index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_records_summary_trgm "
        "ON catalog.records USING gin "
        "(lower(catalog.immutable_unaccent(coalesce(summary, ''))) gin_trgm_ops)"
    )
    # record_keywords.keyword — same ILIKE pattern in service_filters.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_record_keywords_keyword_trgm "
        "ON catalog.record_keywords USING gin "
        "(lower(catalog.immutable_unaccent(keyword)) gin_trgm_ops)"
    )
    # maps.name and maps.description — service_crud.py + service_public.py
    # ILIKE these on every list query (no unaccent there, only lower).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_maps_name_trgm "
        "ON catalog.maps USING gin (lower(name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_maps_description_trgm "
        "ON catalog.maps USING gin "
        "(lower(coalesce(description, '')) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_maps_description_trgm")
    op.execute("DROP INDEX IF EXISTS catalog.ix_maps_name_trgm")
    op.execute("DROP INDEX IF EXISTS catalog.ix_record_keywords_keyword_trgm")
    op.execute("DROP INDEX IF EXISTS catalog.ix_records_summary_trgm")
    op.execute("DROP INDEX IF EXISTS catalog.ix_records_title_trgm")
    op.execute("DROP FUNCTION IF EXISTS catalog.immutable_unaccent(text)")
