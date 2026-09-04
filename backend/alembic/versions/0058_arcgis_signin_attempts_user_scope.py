"""Carry the per-caller ArcGIS sign-in budget on the cluster-global ledger.

fix(#1775). ``POST /api/services/arcgis/signin/`` now reserves a counted
attempt in its own short transaction BEFORE the credential POST and writes the
audit row afterwards, so that a request cancelled mid-POST is already counted:
ArcGIS may have counted that password, and GeoLens must not be the side that
forgot it.

That reordering moves the per-caller budget's source. It was counted from
``catalog.audit_logs`` filtered on ``user_id`` and the ``token_service_host``
detail, and a cancelled request writes no audit row at all, so exactly the
attempts this issue exists to preserve would have gone uncounted. The budget
therefore reads the ledger, and the ledger needs a column to key it on.

``user_scope`` is the same kind of value as ``account_key``: an HMAC-SHA256
digest under a key derived from the instance JWT secret, here over the caller's
user id and the canonical token-service scope. It is NOT a plaintext user id.
Migration 0056's rule that this table holds nothing tenant-identifying and
nothing secret is what makes it safe to keep outside the RLS boundary, and a
digest keeps that rule intact.

Nullable, and not backfilled. A row written before this migration stands for an
attempt whose caller cannot be recovered, and charging it to an arbitrary
caller would be worse than not charging it at all. Every row is swept fifteen
minutes after it is written, so the gap closes itself within one window.

Revision ID: 0058_arcgis_signin_user_scope
Revises: 0057_security_revocation_generation
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058_arcgis_signin_user_scope"
down_revision: Union[str, None] = "0057_security_revocation_generation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "arcgis_signin_attempts",
        sa.Column("user_scope", sa.String(length=64), nullable=True),
        schema="catalog",
    )
    # The same shape as the account index: the windowed count for one caller.
    op.create_index(
        "ix_catalog_arcgis_signin_attempts_user_time",
        "arcgis_signin_attempts",
        ["user_scope", "attempted_at"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_arcgis_signin_attempts_user_time",
        table_name="arcgis_signin_attempts",
        schema="catalog",
    )
    op.drop_column("arcgis_signin_attempts", "user_scope", schema="catalog")
