"""API-key hardening: optional expiry and owner key_epoch snapshot.

fix(#821): API keys had no expiry and no staleness check, so a key lived
forever unless manually revoked and a security event on the owner (role
change, password change) left previously minted keys working.

- ``api_keys.expires_at`` (timestamptz, nullable): NULL keeps the legacy
  forever-key behavior; resolution rejects expired keys exactly like invalid
  ones.
- ``users.key_epoch`` (int, NOT NULL, default 1): API-key revocation
  primitive, deliberately separate from ``token_version``. It is bumped only
  on security events (password change, role change, SAML-to-local
  conversion) — NOT on logout, which bumps ``token_version`` for JWT/session
  hygiene but must not kill long-lived API keys.
- ``api_keys.key_epoch`` (int, NOT NULL): snapshot of the owner's key_epoch
  at mint time, checked against the owner's current value at resolution.
  Existing keys are backfilled with each owner's CURRENT key_epoch so
  security events after this upgrade invalidate keys minted before it.

Revision ID: 0029_api_key_hardening
Revises: 0028_oauth_email_verified_backfill
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_api_key_hardening"
down_revision: Union[str, None] = "0028_oauth_email_verified_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("key_epoch", sa.Integer(), server_default="1", nullable=False),
        schema="catalog",
    )
    op.add_column(
        "api_keys",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "api_keys",
        sa.Column("key_epoch", sa.Integer(), nullable=True),
        schema="catalog",
    )
    # Every key has an owner (user_id is NOT NULL with ON DELETE CASCADE), so
    # this backfill covers all rows and the NOT NULL flip below cannot fail.
    # Owners were just stamped with key_epoch=1 by the server default above,
    # but joining keeps the backfill correct even if that default changes.
    op.execute(
        """
        UPDATE catalog.api_keys ak
        SET key_epoch = u.key_epoch
        FROM catalog.users u
        WHERE ak.user_id = u.id
        """
    )
    op.alter_column("api_keys", "key_epoch", nullable=False, schema="catalog")


def downgrade() -> None:
    op.drop_column("api_keys", "key_epoch", schema="catalog")
    op.drop_column("api_keys", "expires_at", schema="catalog")
    op.drop_column("users", "key_epoch", schema="catalog")
