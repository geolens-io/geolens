"""Index the newest-first orderings of the job list and the dataset feeds.

The admin job list pages ``catalog.ingest_jobs`` by ``created_at DESC, id``
and had no index on either column, so every page sorted the whole table.
``idx_records_created_at_desc`` covered only ``created_at``, so the dataset
list and DCAT feed, which order by ``created_at DESC, id DESC``, still sorted
every row sharing the boundary timestamp; a batch import gives many rows one
timestamp. The records index keeps its name and gains ``id``.

Both tables can be large on a live instance, so the upgrade builds and drops
concurrently. The records index is built under a temporary name and swapped
in, so the dataset list never runs without one. Each step checks what an
interrupted run left behind: a concurrent build that fails leaves an invalid
index that ``IF NOT EXISTS`` alone would skip forever.

The downgrade is one plain transaction instead, and holds a write lock on
``catalog.records`` while it rebuilds the single-column index.

Revision ID: 0083_list_order_indexes
Revises: 0082_login_throttle
Create Date: 2026-10-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0083_list_order_indexes"
down_revision: Union[str, None] = "0082_login_throttle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOBS_INDEX = "ix_ingest_jobs_created_at_id"
JOBS_COLUMNS = "created_at DESC, id"
RECORDS_INDEX = "idx_records_created_at_desc"
RECORDS_COLUMNS = "created_at DESC, id DESC"
RECORDS_PREVIOUS_COLUMNS = "created_at"
_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
_SWAP_INDEX = "idx_records_created_at_desc_swap"


def _index(index_name: str) -> tuple[str, bool] | None:
    """Return ``(definition, usable)`` for a catalog index, if present."""
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT pg_catalog.pg_get_indexdef(index_row.indexrelid) AS definition,
                   index_row.indisvalid AND index_row.indisready AS usable
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
    return row.definition, bool(row.usable)


def _definition(index_name: str, table: str, columns: str) -> str:
    return f"CREATE INDEX {index_name} ON catalog.{table} USING btree ({columns})"


def _build(index_name: str, table: str, columns: str) -> None:
    """Build an index online unless a usable one with this definition exists."""
    state = _index(index_name)
    if state == (_definition(index_name, table, columns), True):
        return
    with op.get_context().autocommit_block():
        if state is not None:
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{index_name}"')
        op.execute(
            f'CREATE INDEX CONCURRENTLY "{index_name}" ON catalog."{table}" ({columns})'
        )


def _replace_records_index() -> None:
    """Give ``RECORDS_INDEX`` its new columns without a moment with no index."""
    target = _definition(RECORDS_INDEX, "records", RECORDS_COLUMNS)
    if _index(RECORDS_INDEX) == (target, True):
        if _index(_SWAP_INDEX) is not None:
            with op.get_context().autocommit_block():
                op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{_SWAP_INDEX}"')
        return
    _build(_SWAP_INDEX, "records", RECORDS_COLUMNS)
    with op.get_context().autocommit_block():
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{RECORDS_INDEX}"')
        op.execute(f'ALTER INDEX catalog."{_SWAP_INDEX}" RENAME TO "{RECORDS_INDEX}"')


def upgrade() -> None:
    _build(JOBS_INDEX, "ingest_jobs", JOBS_COLUMNS)
    _replace_records_index()


def downgrade() -> None:
    # One transaction: an older revision in the same downgrade can refuse, and
    # committed DDL would outlive the rollback of 0083's version stamp, leaving
    # `upgrade head` with nothing to rebuild.
    op.execute(_LOCK_TIMEOUT)
    for index_name in (JOBS_INDEX, _SWAP_INDEX, RECORDS_INDEX):
        op.execute(f'DROP INDEX IF EXISTS catalog."{index_name}"')
    op.execute(
        f'CREATE INDEX "{RECORDS_INDEX}" '
        f'ON catalog."records" ({RECORDS_PREVIOUS_COLUMNS})'
    )
