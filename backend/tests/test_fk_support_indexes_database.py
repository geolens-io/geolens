"""Live-schema invariants for leading foreign-key indexes at Alembic head."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


EXPECTED_PARTIAL_INDEXES = {
    "ix_collection_datasets_added_by": "added_by",
    "ix_collections_created_by": "created_by",
    "ix_dataset_versions_uploaded_by": "uploaded_by",
    "ix_embed_tokens_created_by": "created_by",
    "ix_map_share_tokens_created_by": "created_by",
    "ix_maps_forked_from": "forked_from",
    "ix_records_created_by": "created_by",
    "ix_records_updated_by": "updated_by",
}


async def test_every_catalog_fk_has_a_valid_leading_index(
    test_db_session: AsyncSession,
) -> None:
    """Parent deletes must never need a full child-table FK scan."""
    result = await test_db_session.execute(
        text(
            """
            SELECT constraint_row.conname,
                   constraint_row.conrelid::regclass::text AS table_name
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = constraint_row.connamespace
            WHERE constraint_row.contype = 'f'
              AND namespace.nspname = 'catalog'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_index AS index_row
                  WHERE index_row.indrelid = constraint_row.conrelid
                    AND index_row.indisvalid
                    AND index_row.indisready
                    AND index_row.indnkeyatts >= cardinality(constraint_row.conkey)
                    AND NOT EXISTS (
                        SELECT 1
                        FROM generate_subscripts(constraint_row.conkey, 1)
                             AS key_position(position)
                        WHERE constraint_row.conkey[key_position.position]
                              <> index_row.indkey[key_position.position - 1]
                    )
              )
            ORDER BY table_name, constraint_row.conname
            """
        )
    )
    uncovered = [(row.conname, row.table_name) for row in result]
    assert uncovered == [], f"foreign keys without a valid leading index: {uncovered}"


async def test_audit_fk_indexes_are_partial_non_null_indexes(
    test_db_session: AsyncSession,
) -> None:
    result = await test_db_session.execute(
        text(
            """
            SELECT index_class.relname AS index_name,
                   pg_get_expr(index_row.indpred, index_row.indrelid) AS predicate
            FROM pg_catalog.pg_index AS index_row
            JOIN pg_catalog.pg_class AS index_class
              ON index_class.oid = index_row.indexrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = index_class.relnamespace
            WHERE namespace.nspname = 'catalog'
              AND index_class.relname::text =
                  ANY(CAST(:index_names AS text[]))
              AND index_row.indisvalid
              AND index_row.indisready
            ORDER BY index_class.relname
            """
        ),
        {"index_names": list(EXPECTED_PARTIAL_INDEXES)},
    )
    predicates = {row.index_name: row.predicate for row in result}
    assert predicates.keys() == EXPECTED_PARTIAL_INDEXES.keys()

    for index_name, column_name in EXPECTED_PARTIAL_INDEXES.items():
        predicate = predicates[index_name]
        assert predicate is not None, f"{index_name} is not partial"
        normalized = predicate.replace('"', "").strip().strip("()").strip()
        assert normalized == f"{column_name} IS NOT NULL"
