"""Dataset group grants, and sharing groups inside the tenant boundary.

``dataset_group_grants`` lets members of a sharing group read a ``restricted``
dataset, next to the role-keyed ``dataset_grants``.

Group membership now decides who reads data, so ``groups`` and
``group_members`` join the stamped, fail-closed tenant boundary.
``group_members`` gains its own ``tenant_id``, taken from its group, and a
validator refuses a member whose tenant differs from the group's, including
for privileged maintenance SQL. The policies stay dormant until
``apply_tenancy_rls()`` enables them in multi-tenant mode.

Revision ID: 0091_dataset_group_grants
Revises: 0090_attribute_value_labels
Create Date: 2026-10-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0091_dataset_group_grants"
down_revision: Union[str, None] = "0090_attribute_value_labels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("groups", "group_members")
_STAMP_TRIGGER = "trg_stamp_current_tenant_on_insert"
_STAMP_FUNCTION = "catalog.stamp_current_tenant_on_insert"
# PostgreSQL fires same-event triggers in name order, so the validator sees
# the tenant the stamp trigger set.
_MEMBER_TRIGGER = "trg_validate_group_member_tenant"
_MEMBER_FUNCTION = "catalog.enforce_group_member_tenant"
_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.create_table(
        "dataset_group_grants",
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.datasets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "granted_by",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_dataset_group_grants_group_id",
        "dataset_group_grants",
        ["group_id"],
        schema="catalog",
    )
    op.create_index(
        "ix_dataset_group_grants_granted_by",
        "dataset_group_grants",
        ["granted_by"],
        schema="catalog",
        postgresql_where=sa.text("granted_by IS NOT NULL"),
    )

    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.group_members ADD COLUMN IF NOT EXISTS tenant_id UUID"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM catalog.group_members AS member
                JOIN catalog.groups AS grp ON grp.id = member.group_id
                JOIN catalog.users AS account ON account.id = member.user_id
                WHERE account.tenant_id IS DISTINCT FROM grp.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'cannot tenantize group_members with members from another tenant'
                    USING ERRCODE = '42501';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        UPDATE catalog.group_members AS member
        SET tenant_id = grp.tenant_id
        FROM catalog.groups AS grp
        WHERE grp.id = member.group_id
          AND member.tenant_id IS DISTINCT FROM grp.tenant_id
        """
    )

    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON catalog.{table}")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON catalog.{table} "
            "USING (tenant_id = current_setting('app.current_tenant')::uuid) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
        )
        op.execute(f"DROP TRIGGER IF EXISTS {_STAMP_TRIGGER} ON catalog.{table}")
        op.execute(
            f"CREATE TRIGGER {_STAMP_TRIGGER} BEFORE INSERT ON catalog.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_STAMP_FUNCTION}()"
        )

    # SECURITY INVOKER: under hosted RLS another tenant's group or user is
    # invisible here and reads as missing; the explicit comparison covers a
    # role that bypasses RLS.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_MEMBER_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        DECLARE
            group_tenant uuid;
            member_tenant uuid;
        BEGIN
            SELECT tenant_id INTO group_tenant
            FROM catalog.groups
            WHERE id = NEW.group_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Group % does not exist', NEW.group_id
                    USING ERRCODE = '23503';
            END IF;

            SELECT tenant_id INTO member_tenant
            FROM catalog.users
            WHERE id = NEW.user_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Group member % does not exist', NEW.user_id
                    USING ERRCODE = '23503';
            END IF;

            IF member_tenant IS DISTINCT FROM group_tenant THEN
                RAISE EXCEPTION 'Group member tenant does not match group tenant'
                    USING ERRCODE = '42501';
            END IF;

            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := group_tenant;
            ELSIF NEW.tenant_id IS DISTINCT FROM group_tenant THEN
                RAISE EXCEPTION 'Group member tenant does not match group tenant'
                    USING ERRCODE = '42501';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_MEMBER_TRIGGER} ON catalog.group_members")
    op.execute(
        f"CREATE TRIGGER {_MEMBER_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF group_id, user_id, tenant_id "
        "ON catalog.group_members "
        f"FOR EACH ROW EXECUTE FUNCTION {_MEMBER_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(f"DROP TRIGGER IF EXISTS {_MEMBER_TRIGGER} ON catalog.group_members")
    op.execute(f"DROP FUNCTION IF EXISTS {_MEMBER_FUNCTION}()")
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {_STAMP_TRIGGER} ON catalog.{table}")
        op.execute(f"ALTER TABLE catalog.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catalog.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON catalog.{table}")
    op.execute("ALTER TABLE catalog.group_members DROP COLUMN IF EXISTS tenant_id")

    op.drop_index(
        "ix_dataset_group_grants_granted_by",
        table_name="dataset_group_grants",
        schema="catalog",
    )
    op.drop_index(
        "ix_dataset_group_grants_group_id",
        table_name="dataset_group_grants",
        schema="catalog",
    )
    op.drop_table("dataset_group_grants", schema="catalog")
