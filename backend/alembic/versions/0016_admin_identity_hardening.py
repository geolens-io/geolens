"""Add API-key fingerprints and enforce consistent user lifecycle state.

Revision ID: 0016_admin_identity_hardening
Revises: 0015_add_ingest_job_heartbeat
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_admin_identity_hardening"
down_revision: Union[str, None] = "0015_add_ingest_job_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("fingerprint", sa.String(length=20), nullable=True),
        schema="catalog",
    )

    # Normalize legacy rows before installing the invariant. Historically an
    # admin deactivation wrote is_active=false while leaving status='active'.
    op.execute(
        "UPDATE catalog.users "
        "SET status = 'deactivated' "
        "WHERE status = 'active' AND is_active = false"
    )
    op.execute(
        "UPDATE catalog.users "
        "SET is_active = false "
        "WHERE status <> 'active' AND is_active = true"
    )
    op.create_check_constraint(
        "chk_users_status_active_consistency",
        "users",
        "is_active = (status = 'active')",
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_users_status_active_consistency",
        "users",
        schema="catalog",
        type_="check",
    )
    # Restore the lifecycle representation understood by the pre-0016 service.
    # That version models every disabled account as status='active' plus
    # is_active=false; leaving the explicit states behind would make its
    # deactivated filter miss these users and its is_active=true reactivation
    # leave them unable to authenticate.
    op.execute(
        "UPDATE catalog.users "
        "SET status = 'active', is_active = false "
        "WHERE status IN ('deactivated', 'suspended')"
    )
    op.drop_column("api_keys", "fingerprint", schema="catalog")
