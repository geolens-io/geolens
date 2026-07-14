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
from sqlalchemy.dialects import postgresql

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


def upgrade() -> None:
    op.drop_constraint(
        "collections_name_key",
        "collections",
        schema="catalog",
        type_="unique",
    )
    op.create_index(
        "uq_collections_name_global",
        "collections",
        ["name"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        "uq_collections_name_tenant",
        "collections",
        ["tenant_id", "name"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )

    op.add_column(
        _TABLE,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="catalog",
    )
    op.execute(
        """
        UPDATE catalog.oauth_accounts AS account
        SET tenant_id = linked_user.tenant_id
        FROM catalog.users AS linked_user
        WHERE linked_user.id = account.user_id
          AND account.tenant_id IS DISTINCT FROM linked_user.tenant_id
        """
    )

    op.drop_constraint(
        "uq_oauth_account_provider_subject",
        _TABLE,
        schema="catalog",
        type_="unique",
    )
    op.create_index(
        "uq_oauth_accounts_provider_subject_global",
        _TABLE,
        ["provider_id", "subject"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        "uq_oauth_accounts_provider_subject_tenant",
        _TABLE,
        ["tenant_id", "provider_id", "subject"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )

    op.execute(
        f"CREATE POLICY {_POLICY} ON catalog.{_TABLE} "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
    )
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
        CREATE FUNCTION {_PARENT_FUNCTION}()
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
    op.execute(
        f"CREATE TRIGGER {_PARENT_TRIGGER} "
        f"BEFORE INSERT OR UPDATE OF user_id, tenant_id ON catalog.{_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {_PARENT_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_PARENT_TRIGGER} ON catalog.{_TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {_PARENT_FUNCTION}()")
    op.execute(f"DROP TRIGGER IF EXISTS {_STAMP_TRIGGER} ON catalog.{_TABLE}")
    op.execute(f"ALTER TABLE catalog.{_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catalog.{_TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON catalog.{_TABLE}")

    op.drop_index(
        "uq_oauth_accounts_provider_subject_tenant",
        table_name=_TABLE,
        schema="catalog",
    )
    op.drop_index(
        "uq_oauth_accounts_provider_subject_global",
        table_name=_TABLE,
        schema="catalog",
    )
    # This intentionally fails if two tenants reused the same external subject:
    # the older global-only schema cannot represent that state safely.
    op.create_unique_constraint(
        "uq_oauth_account_provider_subject",
        _TABLE,
        ["provider_id", "subject"],
        schema="catalog",
    )
    op.drop_column(_TABLE, "tenant_id", schema="catalog")

    op.drop_index(
        "uq_collections_name_tenant",
        table_name="collections",
        schema="catalog",
    )
    op.drop_index(
        "uq_collections_name_global",
        table_name="collections",
        schema="catalog",
    )
    # This intentionally fails if separate tenants reused a collection name:
    # the older global-only schema cannot represent that state safely.
    op.create_unique_constraint(
        "collections_name_key",
        "collections",
        ["name"],
        schema="catalog",
    )
