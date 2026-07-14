"""Tenant-isolate OAuth links and collection-name uniqueness.

OAuth providers are fleet configuration in hosted mode, but the account link
from an external subject to a local user belongs to the active tenant. Backfill
the new tenant key from each linked user, replace global subject uniqueness with
the dormant-global/per-tenant partial-index pattern, and add fail-closed RLS and
server-side tenant stamping.

Collections already carry tenant scope, so their historical global name
constraint is also replaced with dormant-global and per-tenant partial indexes.

Revision ID: 0021_tenant_control_plane_hardening
Revises: 0020_tenant_dataset_table_names
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_tenant_control_plane_hardening"
down_revision: Union[str, None] = "0020_tenant_dataset_table_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oauth_accounts"
_POLICY = "tenant_isolation_oauth_accounts"
_STAMP_TRIGGER = "trg_stamp_current_tenant_on_insert"
# PostgreSQL fires same-event triggers in name order. Keep this validator after
# ``trg_stamp_current_tenant_on_insert`` so a hosted insert cannot first pass
# with NULL tenant_id and then be stamped to disagree with a global parent.
_PARENT_TRIGGER = "trg_validate_oauth_account_user_tenant"
_PARENT_FUNCTION = "catalog.enforce_oauth_account_user_tenant"
_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
_COLLECTION_CONSTRAINT = "collections_name_key"
_OAUTH_CONSTRAINT = "uq_oauth_account_provider_subject"
_PARTIAL_INDEXES = (
    (
        "collections",
        "uq_collections_name_global",
        '"name"',
        "tenant_id IS NULL",
    ),
    (
        "collections",
        "uq_collections_name_tenant",
        '"tenant_id", "name"',
        "tenant_id IS NOT NULL",
    ),
    (
        _TABLE,
        "uq_oauth_accounts_provider_subject_global",
        '"provider_id", "subject"',
        "tenant_id IS NULL",
    ),
    (
        _TABLE,
        "uq_oauth_accounts_provider_subject_tenant",
        '"tenant_id", "provider_id", "subject"',
        "tenant_id IS NOT NULL",
    ),
)


def _index_state(index_name: str) -> tuple[bool, bool] | None:
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
    table: str,
    index_name: str,
    columns: str,
    predicate: str | None = None,
) -> None:
    """Build one unique index online, repairing an interrupted prior build."""
    state = _index_state(index_name)
    if state == (True, True):
        return

    where = f" WHERE {predicate}" if predicate is not None else ""
    with op.get_context().autocommit_block():
        if state is not None:
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{index_name}"')
        op.execute(
            f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
            f'ON catalog."{table}" ({columns}){where}'
        )


def _attach_unique_constraint(table: str, constraint: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE connamespace = 'catalog'::regnamespace
                  AND conrelid = 'catalog.{table}'::regclass
                  AND conname = '{constraint}'
            ) THEN
                ALTER TABLE catalog.{table}
                    ADD CONSTRAINT {constraint}
                    UNIQUE USING INDEX {constraint};
            END IF;
        END
        $$
        """
    )


def _drop_partial_indexes() -> None:
    with op.get_context().autocommit_block():
        for _table, index_name, _columns, _predicate in reversed(_PARTIAL_INDEXES):
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{index_name}"')


def _install_oauth_boundary() -> None:
    """Install write guards before concurrent builds release table locks."""
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON catalog.{_TABLE}")
    op.execute(
        f"CREATE POLICY {_POLICY} ON catalog.{_TABLE} "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_STAMP_TRIGGER} ON catalog.{_TABLE}")
    op.execute(
        f"CREATE TRIGGER {_STAMP_TRIGGER} BEFORE INSERT ON catalog.{_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION "
        "catalog.stamp_current_tenant_on_insert()"
    )

    # The active-tenant trigger above prevents a caller-selected tenant key;
    # this complementary invariant prevents linking that key to another
    # tenant's user, including through privileged maintenance SQL.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_PARENT_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        DECLARE
            linked_user_tenant uuid;
        BEGIN
            SELECT tenant_id INTO linked_user_tenant
            FROM catalog.users
            WHERE id = NEW.user_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'OAuth account user % does not exist', NEW.user_id
                    USING ERRCODE = '23503';
            END IF;

            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := linked_user_tenant;
            ELSIF NEW.tenant_id IS DISTINCT FROM linked_user_tenant THEN
                RAISE EXCEPTION
                    'OAuth account tenant does not match linked user tenant'
                    USING ERRCODE = '42501';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_PARENT_TRIGGER} ON catalog.{_TABLE}")
    op.execute(
        f"CREATE TRIGGER {_PARENT_TRIGGER} "
        f"BEFORE INSERT OR UPDATE OF user_id, tenant_id ON catalog.{_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {_PARENT_FUNCTION}()"
    )


def upgrade() -> None:
    # The old global collection constraint remains active while its partial
    # replacements are built, so concurrent writes cannot slip through a gap.
    for definition in _PARTIAL_INDEXES[:2]:
        _ensure_unique_index(*definition)

    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.collections "
        f"DROP CONSTRAINT IF EXISTS {_COLLECTION_CONSTRAINT}"
    )
    # The next concurrent build commits this prefix. IF NOT EXISTS keeps a
    # lock-timeout or interrupted-index retry safe.
    op.execute(f"ALTER TABLE catalog.{_TABLE} ADD COLUMN IF NOT EXISTS tenant_id UUID")
    op.execute(
        """
        UPDATE catalog.oauth_accounts AS account
        SET tenant_id = linked_user.tenant_id
        FROM catalog.users AS linked_user
        WHERE linked_user.id = account.user_id
          AND account.tenant_id IS DISTINCT FROM linked_user.tenant_id
        """
    )

    # Entering the first index autocommit block commits this boundary. New
    # OAuth links are then stamped and parent-validated throughout both builds.
    _install_oauth_boundary()
    for definition in _PARTIAL_INDEXES[2:]:
        _ensure_unique_index(*definition)

    op.execute(_LOCK_TIMEOUT)
    op.execute(
        f"ALTER TABLE catalog.{_TABLE} DROP CONSTRAINT IF EXISTS {_OAUTH_CONSTRAINT}"
    )


def downgrade() -> None:
    # Prove the old global invariants first. If tenants reused a collection
    # name or external subject, the concurrent build fails before any RLS or
    # tenant-key protection is removed.
    _ensure_unique_index(
        _TABLE,
        _OAUTH_CONSTRAINT,
        '"provider_id", "subject"',
    )
    _ensure_unique_index(
        "collections",
        _COLLECTION_CONSTRAINT,
        '"name"',
    )

    op.execute(_LOCK_TIMEOUT)
    _attach_unique_constraint(_TABLE, _OAUTH_CONSTRAINT)
    _attach_unique_constraint("collections", _COLLECTION_CONSTRAINT)
    op.execute(f"DROP TRIGGER IF EXISTS {_PARENT_TRIGGER} ON catalog.{_TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {_PARENT_FUNCTION}()")
    op.execute(f"DROP TRIGGER IF EXISTS {_STAMP_TRIGGER} ON catalog.{_TABLE}")
    op.execute(f"ALTER TABLE catalog.{_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catalog.{_TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON catalog.{_TABLE}")

    _drop_partial_indexes()

    op.execute(_LOCK_TIMEOUT)
    op.execute(f"ALTER TABLE catalog.{_TABLE} DROP COLUMN IF EXISTS tenant_id")
