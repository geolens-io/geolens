"""Add email_verified column + email_verification_tokens table (Phase 1231).

Background
----------
Phase 1231 adds email-verified self-serve signup. This migration lays the
schema foundation:

1. ``catalog.users.email_verified`` — boolean, NOT NULL, server_default false.
   Flipped to True by ``redeem_verification_token()`` when the user clicks the
   verification link in their email. New users default to unverified.

2. ``catalog.email_verification_tokens`` — single-use, expiring verification-
   token store mirroring the RefreshToken pattern.  Only the sha256 hex digest
   of the raw token is stored (plaintext never persisted), with an ``expires_at``
   deadline and a ``consumed_at`` single-use marker.

Downgrade is a NO-OP (``pass``) per the ``0008_oauth_saml_columns`` precedent
(MIG-04 enterprise-heads + ``test_tenant_rls_migration`` relative offsets).

Revision ID: 0009_email_verification
Revises:     0008_oauth_saml_columns
Create Date: 2026-06-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009_email_verification"
down_revision: Union[str, None] = "0008_oauth_saml_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add email_verified to users + create email_verification_tokens table.

    Uses IF NOT EXISTS / CREATE TABLE IF NOT EXISTS so that a re-upgrade after
    the NO-OP downgrade does not fail with DuplicateColumnError — mirroring the
    idempotent ``ADD COLUMN IF NOT EXISTS`` pattern used in 0008.
    """
    # 1. Add email_verified column to catalog.users (idempotent).
    op.execute(
        """
        ALTER TABLE catalog.users
            ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false
        """
    )

    # 2. Create catalog.email_verification_tokens (idempotent).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog.email_verification_tokens (
            id          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            user_id     UUID        NOT NULL REFERENCES catalog.users(id) ON DELETE CASCADE,
            token_hash  VARCHAR(128) NOT NULL UNIQUE,
            expires_at  TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # Indexes: CREATE INDEX IF NOT EXISTS mirrors the RefreshToken convention.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_catalog_email_verification_tokens_expires_at
            ON catalog.email_verification_tokens (expires_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_user_id
            ON catalog.email_verification_tokens (user_id)
        """
    )


def downgrade() -> None:
    """No-op: intentionally does NOT drop email_verified or the token table.

    Dropping on downgrade would:
      1. destroy verification state for any users who have already verified
         (data loss), and
      2. break test isolation — the migration round-trip tests downgrade a
         shared per-worker test DB below 0009, and dropping the table/column
         would strand concurrent email-verification tests
         (UndefinedColumnError / relation-does-not-exist).

    This mirrors the ``0008_oauth_saml_columns`` NO-OP downgrade precedent
    (MIG-04 enterprise-heads + ``test_tenant_rls_migration`` relative offsets).
    Leaving the column/table is harmless: they are additive and backward-compatible
    with all code running against 0008.
    """
    pass
