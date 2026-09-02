"""Cluster-global ledger for ArcGIS sign-in attempt counting.

fix(#1758 codex r4). The sign-in endpoint limits attempts per target ArcGIS
account, because an Esri lockout belongs to the account rather than to the
GeoLens caller spending it. That count was read from ``catalog.audit_logs``,
which carries a ``tenant_isolation_audit_logs`` policy, so in ``multi_tenant``
each tenant could see only its own attempts and two tenants could jointly send
six failures against one account and lock it. The advisory lock did not close
the gap either: it serializes, it does not aggregate.

There is no sanctioned way to read one query cluster-wide. The policy is a
flat ``USING (tenant_id = current_setting('app.current_tenant')::uuid)``
(0022) with no escape clause, and ``core/db/rls.py`` refuses to serve in
multi_tenant when the runtime role can bypass RLS at all, which is the point
of the boundary. The two SECURITY DEFINER functions that do exist (0019) are
tenant schema provisioning, not row reads. So the count needs state that was
never tenant-scoped to begin with, and this is that state.

DELIBERATELY OUTSIDE THE RLS BOUNDARY. This table has no ``tenant_id``, no
policy, and no entry in ``RLS_TABLES``, and a future sweep that adds tenancy
to every catalog table must skip it: a per-tenant view of this ledger is
exactly the defect it exists to fix. What makes that safe is that it holds
nothing tenant-identifying and nothing secret. One row is a keyed digest and
a timestamp. No username, no password, no token, no portal URL, no user id,
no tenant id. The digest is HMAC-SHA256 over the portal host and the
casefolded username under a key derived from the instance JWT secret, so it
is not reversible to the account it stands for, and rows are swept fifteen
minutes after they are written.

Nothing here stores a credential, so the request-only rule is untouched.

Revision ID: 0056_arcgis_signin_attempts
Revises: 0055_backfill_pmtiles_distributions
Create Date: 2026-09-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0056_arcgis_signin_attempts"
down_revision: Union[str, None] = "0055_backfill_pmtiles_distributions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "arcgis_signin_attempts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_key", sa.String(length=64), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="catalog",
    )
    # Serves both readers: the windowed count for one account, and the sweep,
    # which scans by time alone and takes the leading column as a no-op.
    op.create_index(
        "ix_catalog_arcgis_signin_attempts_account_time",
        "arcgis_signin_attempts",
        ["account_key", "attempted_at"],
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_arcgis_signin_attempts_attempted_at",
        "arcgis_signin_attempts",
        ["attempted_at"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_arcgis_signin_attempts_attempted_at",
        table_name="arcgis_signin_attempts",
        schema="catalog",
    )
    op.drop_index(
        "ix_catalog_arcgis_signin_attempts_account_time",
        table_name="arcgis_signin_attempts",
        schema="catalog",
    )
    op.drop_table("arcgis_signin_attempts", schema="catalog")
