"""Create fail-closed RLS policies on the 6 tenant-shared tables (ISO-02, Phase 1208-02).

Defines ``CREATE POLICY tenant_isolation_<table>`` with a USING clause of
``tenant_id = current_setting('app.current_tenant')::uuid`` and an identical
WITH CHECK clause on each of the 6 tenant-shared control-plane tables.

Key design constraints
----------------------
- **NO ENABLE/FORCE RLS here.** The migration is mode-independent — it runs
  identically in both ``single_tenant`` and ``multi_tenant`` deployments, so
  the schema stays drift-gate-consistent regardless of tenancy mode.  Policy
  enablement is runtime-only via ``apply_tenancy_rls()`` (Phase 1208-02 Plan).
- **NO null-escape clause.** The ``OR current_setting('app.current_tenant','t')
  IS NULL`` escape is intentionally absent — it would make the policy fail-open
  and is rejected by the ISO-02 decision (see 1208-CONTEXT.md).  An unset GUC
  fails closed (error or 0 rows) as required.
- **Safe rollback.** ``downgrade()`` unforces and disables runtime-activated RLS
  before dropping all 6 policies in inverse order.  This prevents policy-free
  tables from remaining in a deny-all state after rollback.

The 6 tables (all in ``catalog`` schema) received a nullable ``tenant_id`` UUID
column in ``0005_dormant_tenancy``.

Revision ID: 0006_tenant_rls
Revises:     0005_dormant_tenancy
Create Date: 2026-06-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006_tenant_rls"
down_revision: Union[str, None] = "0005_dormant_tenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The 6 tenant-shared control-plane tables (upgrade order).
_TABLES = (
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
)


def upgrade() -> None:
    """Create fail-closed RLS policies on the 6 tenant-shared tables.

    Creates one policy per table named ``tenant_isolation_<table>``.  Both the
    USING clause (read filter) and the WITH CHECK clause (write guard) are set
    to ``tenant_id = current_setting('app.current_tenant')::uuid``.

    RLS is NOT enabled here — policies exist but are inactive until
    ``apply_tenancy_rls()`` is called at runtime (multi_tenant mode only).
    """
    for table in _TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON catalog.{table} "
            f"USING (tenant_id = current_setting('app.current_tenant')::uuid) "
            f"WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
        )


def downgrade() -> None:
    """Disable runtime RLS state, then drop the policies in inverse order."""
    for table in reversed(_TABLES):
        op.execute(f"ALTER TABLE catalog.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catalog.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON catalog.{table}")
