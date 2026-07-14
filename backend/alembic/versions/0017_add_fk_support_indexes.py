"""Add leading indexes for nullable attribution and lineage foreign keys.

PostgreSQL does not create indexes on the referencing side of a foreign key.
These columns all use ``ON DELETE SET NULL`` and are exercised by supported
hard-delete paths for users and maps. Without a leading index, deleting a
parent row scans the complete child table while enforcing the constraint.

Every indexed column is nullable, so the indexes exclude null values. The
tables can be large in production; concurrent, resumable DDL avoids blocking
normal reads and writes while each index is built.

Revision ID: 0017_add_fk_support_indexes
Revises: 0016_admin_identity_hardening
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_add_fk_support_indexes"
down_revision: Union[str, None] = "0016_admin_identity_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Fixed identifiers only; keeping the inventory in one tuple makes upgrade and
# downgrade exact inverses and gives the focused invariant test one source of
# truth to inspect.
FK_SUPPORT_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_collection_datasets_added_by", "collection_datasets", "added_by"),
    ("ix_collections_created_by", "collections", "created_by"),
    ("ix_dataset_versions_uploaded_by", "dataset_versions", "uploaded_by"),
    ("ix_embed_tokens_created_by", "embed_tokens", "created_by"),
    ("ix_map_share_tokens_created_by", "map_share_tokens", "created_by"),
    ("ix_maps_forked_from", "maps", "forked_from"),
    ("ix_records_created_by", "records", "created_by"),
    ("ix_records_updated_by", "records", "updated_by"),
)


def _index_state(index_name: str) -> tuple[bool, bool] | None:
    """Return ``(indisvalid, indisready)`` for a catalog index, if present."""
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT index_row.indisvalid, index_row.indisready
            FROM pg_catalog.pg_index AS index_row
            JOIN pg_catalog.pg_class AS index_class
              ON index_class.oid = index_row.indexrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = index_class.relnamespace
            WHERE namespace.nspname = 'catalog'
              AND index_class.relname = :index_name
            """
            ),
            {"index_name": index_name},
        )
        .one_or_none()
    )
    if row is None:
        return None
    return bool(row.indisvalid), bool(row.indisready)


def upgrade() -> None:
    """Create partial FK-support indexes without blocking table writes."""
    # CREATE INDEX CONCURRENTLY is forbidden inside a transaction. Alembic's
    # autocommit block commits the surrounding migration transaction, executes
    # each statement in autocommit mode, then starts a new transaction for the
    # version-table update. A failed concurrent build can leave an invalid,
    # same-name index behind; IF NOT EXISTS alone would then skip it forever.
    # Drop invalid/not-ready remnants before recreating, while preserving an
    # already-valid index when a retry follows a later migration failure.
    for index_name, table_name, column_name in FK_SUPPORT_INDEXES:
        state = _index_state(index_name)
        if state == (True, True):
            continue

        with op.get_context().autocommit_block():
            if state is not None:
                op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{index_name}"')
            op.execute(
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
                f'ON catalog."{table_name}" ("{column_name}") '
                f'WHERE "{column_name}" IS NOT NULL'
            )


def downgrade() -> None:
    """Drop the FK-support indexes without blocking table writes."""
    with op.get_context().autocommit_block():
        for index_name, _table_name, _column_name in reversed(FK_SUPPORT_INDEXES):
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{index_name}"')
