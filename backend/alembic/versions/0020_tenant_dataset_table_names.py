"""Scope physical dataset table-name uniqueness to each tenant.

The catalog originally required ``datasets.table_name`` to be globally unique
because every deployment used one physical ``data`` schema. Multi-tenant mode
uses one ``data_t_<tenant>`` schema per tenant, so two tenants may safely use
the same physical table name. Keeping the global constraint also made
RLS-scoped collision detection race into an unexpected unique violation.

Revision ID: 0020_tenant_dataset_table_names
Revises: 0019_tenant_provisioning_boundary
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_tenant_dataset_table_names"
down_revision: Union[str, None] = "0019_tenant_provisioning_boundary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "datasets"
_CONSTRAINT = "datasets_table_name_key"
_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
_PARTIAL_INDEXES = (
    (
        "uq_datasets_table_name_global",
        '"table_name"',
        "tenant_id IS NULL",
    ),
    (
        "uq_datasets_table_name_tenant",
        '"tenant_id", "table_name"',
        "tenant_id IS NOT NULL",
    ),
)


def _index_state(index_name: str) -> tuple[bool, bool] | None:
    """Return PostgreSQL's validity/readiness flags for one catalog index."""
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


def _ensure_unique_index(
    index_name: str, columns: str, predicate: str | None = None
) -> None:
    """Build a unique index online and repair interrupted build remnants."""
    state = _index_state(index_name)
    if state == (True, True):
        return

    where = f" WHERE {predicate}" if predicate is not None else ""
    with op.get_context().autocommit_block():
        if state is not None:
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{index_name}"')
        op.execute(
            f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
            f'ON catalog."{_TABLE}" ({columns}){where}'
        )


def _drop_partial_indexes() -> None:
    with op.get_context().autocommit_block():
        for index_name, _columns, _predicate in reversed(_PARTIAL_INDEXES):
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{index_name}"')


def upgrade() -> None:
    # Build the replacements while the old, stricter global constraint still
    # prevents duplicates. The brief constraint drop is bounded separately.
    for definition in _PARTIAL_INDEXES:
        _ensure_unique_index(*definition)

    op.execute(_LOCK_TIMEOUT)
    op.execute(f"ALTER TABLE catalog.{_TABLE} DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")


def downgrade() -> None:
    # This intentionally fails loud if separate tenants have since reused a
    # table name: the older global-only schema cannot represent that state.
    _ensure_unique_index(_CONSTRAINT, '"table_name"')
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE connamespace = 'catalog'::regnamespace
                  AND conrelid = 'catalog.{_TABLE}'::regclass
                  AND conname = '{_CONSTRAINT}'
            ) THEN
                ALTER TABLE catalog.{_TABLE}
                    ADD CONSTRAINT {_CONSTRAINT}
                    UNIQUE USING INDEX {_CONSTRAINT};
            END IF;
        END
        $$
        """
    )
    _drop_partial_indexes()
