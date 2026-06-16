"""Add shard_id routing column to catalog.tenants + ensure geolens_reader floor (DP-01/DP-05, Phase 1209-01).

Design invariants
-----------------
- **shard_id column**: trivial one-shard routing map for Phase 1214's promote/rebalance.
  Nullable TEXT with server_default ``'shard-0'`` — existing rows get the default,
  new tenants inherit it automatically.
- **geolens_reader floor**: ensures the global ``geolens_reader`` NOLOGIN role exists
  in fresh single_tenant deployments that never ran ``apply_tenant_data_schema()``.
  The ``DO $$ IF NOT EXISTS $$`` block is idempotent — harmless if the role already
  exists (it was created by ``init-db.sh`` on Docker-based installs).
- **Per-tenant schemas + roles are NOT created here**: they are dynamic (provisioned
  at tenant-creation time by ``apply_tenant_data_schema()`` in ``backend/app/core/db/tenant_schema.py``).
  Alembic cannot know which tenants will exist — runtime provisioning is the correct
  approach for dynamic per-tenant DDL.
- **Mode-independent**: this migration runs identically in both ``single_tenant`` and
  ``multi_tenant`` — schema stays drift-gate-consistent regardless of tenancy mode.
  Policy/schema EXISTENCE is migration-managed; ACTIVATION is runtime-only.

Revision ID: 0007_tenant_data_schemas
Revises:     0006_tenant_rls
Create Date: 2026-06-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_tenant_data_schemas"
down_revision: Union[str, None] = "0006_tenant_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add shard_id routing column to catalog.tenants + ensure geolens_reader exists.

    1. Adds nullable ``shard_id`` TEXT column to ``catalog.tenants`` with server_default
       ``'shard-0'`` (trivial one-shard routing map; Phase 1214 populate real values).
    2. Ensures the global ``geolens_reader`` NOLOGIN role exists (idempotent floor for
       fresh single_tenant deployments).

    Per-tenant ``data_t_{tid}`` schemas and ``geolens_reader_t_{tid}`` roles are
    provisioned at runtime by ``apply_tenant_data_schema()`` — NOT by Alembic —
    because tenants are created dynamically after deployment.
    """
    # 1. Add shard_id routing column.
    op.add_column(
        "tenants",
        sa.Column(
            "shard_id",
            sa.Text(),
            nullable=True,
            server_default="shard-0",
            comment="Shard routing key for Phase-1214 promote/rebalance (trivial 'shard-0' at one shard)",
        ),
        schema="catalog",
    )

    # 2. Ensure the global geolens_reader role exists (idempotent floor).
    #    init-db.sh creates it on a fresh Docker volume; this guard covers
    #    deployments that run alembic without Docker init (e.g. CI, cloud).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader') THEN
                CREATE ROLE geolens_reader NOLOGIN;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    """Remove shard_id column from catalog.tenants.

    Does NOT drop geolens_reader — it pre-existed this migration (created by
    init-db.sh and/or earlier tenant setup) and is not owned by 0007.
    """
    op.drop_column("tenants", "shard_id", schema="catalog")
