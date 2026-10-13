"""Per-account sign-in throttle ledger and single-use device-trust tokens.

``login_attempts`` counts password sign-in attempts per account, and per
remembered browser for that account, over a sliding window.
``login_trust_tokens`` holds the digests of the links an operator mints on
the host to remember a browser during a throttle, bound to the account's
user id so deleting the account deletes them. Both sit outside the RLS
boundary, like ``arcgis_signin_attempts`` (0056): every key is a keyed
digest that already includes the tenant, and no row holds a username,
tenant id or secret.

Revision ID: 0082_login_throttle
Revises: 0081_admin_entered_email_verified
Create Date: 2026-10-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0082_login_throttle"
down_revision: Union[str, None] = "0081_admin_entered_email_verified"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("account_key", sa.String(length=64), nullable=False),
        sa.Column("device_key", sa.String(length=64), nullable=True),
        sa.Column("failed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tripped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_login_attempts_bucket_time",
        "login_attempts",
        ["account_key", "device_key", "attempted_at"],
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_login_attempts_attempted_at",
        "login_attempts",
        ["attempted_at"],
        schema="catalog",
    )
    op.create_table(
        "login_trust_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("account_key", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("binding", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_login_trust_tokens_expires_at",
        "login_trust_tokens",
        ["expires_at"],
        schema="catalog",
    )
    op.create_index(
        "ix_login_trust_tokens_user_id",
        "login_trust_tokens",
        ["user_id"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_login_trust_tokens_user_id",
        table_name="login_trust_tokens",
        schema="catalog",
    )
    op.drop_index(
        "ix_catalog_login_trust_tokens_expires_at",
        table_name="login_trust_tokens",
        schema="catalog",
    )
    op.drop_table("login_trust_tokens", schema="catalog")
    op.drop_index(
        "ix_catalog_login_attempts_attempted_at",
        table_name="login_attempts",
        schema="catalog",
    )
    op.drop_index(
        "ix_catalog_login_attempts_bucket_time",
        table_name="login_attempts",
        schema="catalog",
    )
    op.drop_table("login_attempts", schema="catalog")
