"""Dataset group grants inside the tenant boundary.

Owners now write ``dataset_group_grants`` through the share route, so a grant
joins the stamped, fail-closed tenant boundary like ``group_members``. It
gains ``tenant_id``, taken from its dataset, and a validator refuses a grant
whose group belongs to another tenant, including for privileged maintenance
SQL, which bypasses RLS and the foreign keys' visibility. The policy stays
dormant until ``apply_tenancy_rls()`` enables it in multi-tenant mode.

Revision ID: 0092_dataset_group_grant_tenant
Revises: 0091_dataset_group_grants
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0092_dataset_group_grant_tenant"
down_revision: Union[str, None] = "0091_dataset_group_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "dataset_group_grants"
_POLICY = f"tenant_isolation_{_TABLE}"
_STAMP_TRIGGER = "trg_stamp_current_tenant_on_insert"
_STAMP_FUNCTION = "catalog.stamp_current_tenant_on_insert"
# PostgreSQL fires same-event triggers in name order, so the validator sees
# the tenant the stamp trigger set.
_GRANT_TRIGGER = "trg_validate_dataset_group_grant_tenant"
_GRANT_FUNCTION = "catalog.enforce_dataset_group_grant_tenant"
_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(f"ALTER TABLE catalog.{_TABLE} ADD COLUMN IF NOT EXISTS tenant_id UUID")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM catalog.{_TABLE} AS grant_row
                JOIN catalog.groups AS grp ON grp.id = grant_row.group_id
                JOIN catalog.datasets AS ds ON ds.id = grant_row.dataset_id
                WHERE ds.tenant_id IS DISTINCT FROM grp.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'cannot tenantize dataset_group_grants with groups from another tenant'
                    USING ERRCODE = '42501';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        f"""
        UPDATE catalog.{_TABLE} AS grant_row
        SET tenant_id = ds.tenant_id
        FROM catalog.datasets AS ds
        WHERE ds.id = grant_row.dataset_id
          AND grant_row.tenant_id IS DISTINCT FROM ds.tenant_id
        """
    )

    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON catalog.{_TABLE}")
    op.execute(
        f"CREATE POLICY {_POLICY} ON catalog.{_TABLE} "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_STAMP_TRIGGER} ON catalog.{_TABLE}")
    op.execute(
        f"CREATE TRIGGER {_STAMP_TRIGGER} BEFORE INSERT ON catalog.{_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {_STAMP_FUNCTION}()"
    )

    # SECURITY INVOKER: under hosted RLS another tenant's dataset or group is
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
            dataset_tenant uuid;
            group_tenant uuid;
        BEGIN
            SELECT tenant_id INTO dataset_tenant
            FROM catalog.datasets
            WHERE id = NEW.dataset_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Dataset % does not exist', NEW.dataset_id
                    USING ERRCODE = '23503';
            END IF;

            SELECT tenant_id INTO group_tenant
            FROM catalog.groups
            WHERE id = NEW.group_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Group % does not exist', NEW.group_id
                    USING ERRCODE = '23503';
            END IF;

            IF group_tenant IS DISTINCT FROM dataset_tenant THEN
                RAISE EXCEPTION 'Grant group tenant does not match dataset tenant'
                    USING ERRCODE = '42501';
            END IF;

            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := dataset_tenant;
            ELSIF NEW.tenant_id IS DISTINCT FROM dataset_tenant THEN
                RAISE EXCEPTION 'Grant group tenant does not match dataset tenant'
                    USING ERRCODE = '42501';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_GRANT_TRIGGER} ON catalog.{_TABLE}")
    op.execute(
        f"CREATE TRIGGER {_GRANT_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF dataset_id, group_id, tenant_id "
        f"ON catalog.{_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {_GRANT_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(f"DROP TRIGGER IF EXISTS {_GRANT_TRIGGER} ON catalog.{_TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {_GRANT_FUNCTION}()")
    op.execute(f"DROP TRIGGER IF EXISTS {_STAMP_TRIGGER} ON catalog.{_TABLE}")
    op.execute(f"ALTER TABLE catalog.{_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catalog.{_TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON catalog.{_TABLE}")
    op.execute(f"ALTER TABLE catalog.{_TABLE} DROP COLUMN IF EXISTS tenant_id")
