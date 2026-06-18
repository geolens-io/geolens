"""Add dormant tenant substrate: tenant_id columns + tenancy tables + partial-unique indexes.

Adds the inert multi-tenant substrate to the core schema (TSEAM-01, TSEAM-02,
Phase 1207).  All changes are **dormant** — tenant_id defaults to NULL,
no FK enforcement, no RLS, no behavior change for single_tenant (Community /
Enterprise) deployments.

What this migration adds
------------------------
1. Nullable ``tenant_id UUID`` column to every tenant-shared control-plane
   table: ``users``, ``records``, ``datasets``, ``maps``, ``collections``,
   ``embed_tokens``.

2. New tables in the ``catalog`` schema:
   - ``organizations`` — top-level billing/ownership entity.
   - ``tenants`` — logical tenant (subdomain-shaped slug) within an org.
   - ``org_memberships`` — user ↔ org membership join table (composite PK,
     no FK constraints until Phase 1208).

3. TSEAM-02 two-partial-index uniqueness pattern on ``users``:
   Drops the existing global UNIQUE constraints (``users_username_key``,
   ``users_email_key``) and replaces them with four partial unique indexes:
   - ``uq_users_username_global``  UNIQUE(username) WHERE tenant_id IS NULL
   - ``uq_users_username_tenant``  UNIQUE(tenant_id, username) WHERE tenant_id IS NOT NULL
   - ``uq_users_email_global``     UNIQUE(email) WHERE tenant_id IS NULL
   - ``uq_users_email_tenant``     UNIQUE(tenant_id, email) WHERE tenant_id IS NOT NULL

   Rationale: Postgres treats NULLs as DISTINCT in a unique index, so a naive
   composite UNIQUE(tenant_id, username) would allow duplicate usernames when
   tenant_id IS NULL — breaking single_tenant global uniqueness.  The partial
   indexes are the correct solution.

Downgrade reverses every operation in the exact inverse order.

Revision ID: 0005_dormant_tenancy
Revises:     0004_add_maps_legend_title
Create Date: 2026-06-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_dormant_tenancy"
down_revision: Union[str, None] = "0004_add_maps_legend_title"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add nullable tenant_id to the six shared control-plane tables.
    # ------------------------------------------------------------------
    for table in (
        "users",
        "records",
        "datasets",
        "maps",
        "collections",
        "embed_tokens",
    ):
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
            schema="catalog",
        )

    # ------------------------------------------------------------------
    # 2. Create the tenancy tables.
    # ------------------------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="catalog",
    )

    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(63), nullable=False),
        # Dormant link to organizations — no FK constraint until Phase 1208.
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="catalog",
    )
    # Non-unique index on slug (unique-per-org enforcement is Phase 1208).
    op.create_index(
        "ix_tenants_slug",
        "tenants",
        ["slug"],
        unique=False,
        schema="catalog",
    )

    op.create_table(
        "org_memberships",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Nullable until roles are wired (Phase 1208).
        sa.Column("role", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "organization_id"),
        schema="catalog",
    )

    # ------------------------------------------------------------------
    # 3. TSEAM-02: Replace global UNIQUE constraints on users with the
    #    two-partial-index pattern (per field).
    # ------------------------------------------------------------------
    # Drop the existing global unique constraints that were created in
    # 0001_baseline as sa.UniqueConstraint("username") / ("email").
    # Postgres generates names "users_username_key" and "users_email_key".
    op.drop_constraint("users_username_key", "users", schema="catalog", type_="unique")
    op.drop_constraint("users_email_key", "users", schema="catalog", type_="unique")

    # username: global (tenant_id IS NULL) — preserves single_tenant uniqueness.
    op.create_index(
        "uq_users_username_global",
        "users",
        ["username"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    # username: per-tenant (tenant_id IS NOT NULL) — multi_tenant uniqueness.
    op.create_index(
        "uq_users_username_tenant",
        "users",
        ["tenant_id", "username"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    # email: global.
    op.create_index(
        "uq_users_email_global",
        "users",
        ["email"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    # email: per-tenant.
    op.create_index(
        "uq_users_email_tenant",
        "users",
        ["tenant_id", "email"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse in exact inverse order of upgrade().
    # ------------------------------------------------------------------

    # 3. Restore the global unique constraints and drop the partial indexes.
    op.drop_index("uq_users_email_tenant", table_name="users", schema="catalog")
    op.drop_index("uq_users_email_global", table_name="users", schema="catalog")
    op.drop_index("uq_users_username_tenant", table_name="users", schema="catalog")
    op.drop_index("uq_users_username_global", table_name="users", schema="catalog")

    op.create_unique_constraint("users_email_key", "users", ["email"], schema="catalog")
    op.create_unique_constraint(
        "users_username_key", "users", ["username"], schema="catalog"
    )

    # 2. Drop the tenancy tables.
    op.drop_table("org_memberships", schema="catalog")
    op.drop_index("ix_tenants_slug", table_name="tenants", schema="catalog")
    op.drop_table("tenants", schema="catalog")
    op.drop_table("organizations", schema="catalog")

    # 1. Drop the tenant_id columns from the six shared tables.
    for table in (
        "embed_tokens",
        "collections",
        "maps",
        "datasets",
        "records",
        "users",
    ):
        op.drop_column(table, "tenant_id", schema="catalog")
