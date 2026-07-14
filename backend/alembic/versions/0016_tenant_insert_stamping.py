"""Server-stamp tenant IDs on inserts into tenant-shared tables.

The trigger installed by this migration is deliberately mode-independent.  In
Community and other single-tenant deployments ``app.current_tenant`` is not
set, so the function returns the row unchanged.  In a tenant-scoped database
transaction it stamps an omitted ``tenant_id`` from the transaction-local GUC
and rejects a caller-supplied tenant that does not match that GUC.

Keeping this invariant in PostgreSQL closes write paths that bypass the ORM or
forget to populate ``tenant_id``.  RLS remains the read/write visibility
boundary; this trigger is the complementary server-side insert invariant.

Revision ID: 0016_tenant_insert_stamping
Revises: 0015_add_ingest_job_heartbeat
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016_tenant_insert_stamping"
down_revision: Union[str, None] = "0016_admin_identity_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Archival copy of the exact table boundary established by 0005/0006.  Alembic
# migrations must remain self-contained, so do not import the runtime constant.
_TABLES = (
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
)

_FUNCTION_NAME = "catalog.stamp_current_tenant_on_insert"
_TRIGGER_NAME = "trg_stamp_current_tenant_on_insert"


def upgrade() -> None:
    """Install the dormant tenant-stamping function and six insert triggers."""
    op.execute(
        f"""
        CREATE FUNCTION {_FUNCTION_NAME}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        DECLARE
            session_tenant_text text;
            session_tenant uuid;
        BEGIN
            session_tenant_text := NULLIF(
                current_setting('app.current_tenant', true),
                ''
            );

            -- No tenant GUC is the intentional single-tenant/migrator path.
            IF session_tenant_text IS NULL THEN
                RETURN NEW;
            END IF;

            -- An invalid non-empty GUC must fail closed at the UUID cast.
            session_tenant := session_tenant_text::uuid;

            IF NEW.tenant_id IS NOT NULL
               AND NEW.tenant_id IS DISTINCT FROM session_tenant THEN
                RAISE EXCEPTION
                    'tenant_id does not match the active tenant for %.%',
                    TG_TABLE_SCHEMA,
                    TG_TABLE_NAME
                    USING ERRCODE = '42501',
                          HINT = 'omit tenant_id or use the active tenant';
            END IF;

            NEW.tenant_id := session_tenant;
            RETURN NEW;
        END;
        $$
        """
    )

    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {_TRIGGER_NAME} "
            f"BEFORE INSERT ON catalog.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_FUNCTION_NAME}()"
        )


def downgrade() -> None:
    """Drop the six triggers and then their shared trigger function."""
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON catalog.{table}")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}()")
