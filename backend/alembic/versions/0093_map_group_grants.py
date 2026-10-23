"""Map group grants and the restricted map visibility.

``map_group_grants`` lets members of a sharing group read a ``restricted``
map. A grant takes its ``tenant_id`` from its map and joins the stamped,
fail-closed tenant boundary, and a validator refuses a group from another
tenant, including for privileged maintenance SQL. The policy stays dormant
until ``apply_tenancy_rls()`` enables it in multi-tenant mode.

Revision ID: 0093_map_group_grants
Revises: 0092_dataset_group_grant_tenant
Create Date: 2026-10-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0093_map_group_grants"
down_revision: Union[str, None] = "0092_dataset_group_grant_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "map_group_grants"
_POLICY = f"tenant_isolation_{_TABLE}"
_STAMP_TRIGGER = "trg_stamp_current_tenant_on_insert"
_STAMP_FUNCTION = "catalog.stamp_current_tenant_on_insert"
# PostgreSQL fires same-event triggers in name order, so the validator sees
# the tenant the stamp trigger set.
_GRANT_TRIGGER = "trg_validate_map_group_grant_tenant"
_GRANT_FUNCTION = "catalog.enforce_map_group_grant_tenant"
_CHECK = "chk_maps_visibility"
_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "map_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.maps.id", ondelete="CASCADE"),
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
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_map_group_grants_group_id", _TABLE, ["group_id"], schema="catalog"
    )
    op.create_index(
        "ix_map_group_grants_granted_by",
        _TABLE,
        ["granted_by"],
        schema="catalog",
        postgresql_where=sa.text("granted_by IS NOT NULL"),
    )

    op.execute(_LOCK_TIMEOUT)
    op.execute(f"ALTER TABLE catalog.maps DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute(
        f"ALTER TABLE catalog.maps ADD CONSTRAINT {_CHECK} "
        "CHECK (visibility IN ('private', 'public', 'internal', 'restricted'))"
    )

    op.execute(
        f"CREATE POLICY {_POLICY} ON catalog.{_TABLE} "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
    )
    op.execute(
        f"CREATE TRIGGER {_STAMP_TRIGGER} BEFORE INSERT ON catalog.{_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {_STAMP_FUNCTION}()"
    )

    # SECURITY INVOKER: under hosted RLS another tenant's map or group is
    # invisible here and reads as missing; the explicit comparison covers a
    # role that bypasses RLS.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_GRANT_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        DECLARE
            map_tenant uuid;
            group_tenant uuid;
        BEGIN
            SELECT tenant_id INTO map_tenant
            FROM catalog.maps
            WHERE id = NEW.map_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Map % does not exist', NEW.map_id
                    USING ERRCODE = '23503';
            END IF;

            SELECT tenant_id INTO group_tenant
            FROM catalog.groups
            WHERE id = NEW.group_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Group % does not exist', NEW.group_id
                    USING ERRCODE = '23503';
            END IF;

            IF group_tenant IS DISTINCT FROM map_tenant THEN
                RAISE EXCEPTION 'Grant group tenant does not match map tenant'
                    USING ERRCODE = '42501';
            END IF;

            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := map_tenant;
            ELSIF NEW.tenant_id IS DISTINCT FROM map_tenant THEN
                RAISE EXCEPTION 'Grant group tenant does not match map tenant'
                    USING ERRCODE = '42501';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER {_GRANT_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF map_id, group_id, tenant_id "
        f"ON catalog.{_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {_GRANT_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    # Without grants a restricted map reaches its owner and admins, the
    # audience private has.
    op.execute(
        "UPDATE catalog.maps SET visibility = 'private' WHERE visibility = 'restricted'"
    )
    op.execute(f"ALTER TABLE catalog.maps DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute(
        f"ALTER TABLE catalog.maps ADD CONSTRAINT {_CHECK} "
        "CHECK (visibility IN ('private', 'public', 'internal'))"
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_GRANT_TRIGGER} ON catalog.{_TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {_GRANT_FUNCTION}()")
    op.drop_index("ix_map_group_grants_granted_by", table_name=_TABLE, schema="catalog")
    op.drop_index("ix_map_group_grants_group_id", table_name=_TABLE, schema="catalog")
    op.drop_table(_TABLE, schema="catalog")
