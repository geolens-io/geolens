"""Backfill email_verified for GitHub-provisioned OAuth users.

fix(#623): the JIT provisioning path built ``User(...)`` without
``email_verified``, so every OAuth-provisioned account persisted the model
default (false) even though the claim guaranteed verification — 27 of 27 SSO
users on the public demo.

Backfill is deliberately narrow. Only GitHub-linked accounts are provably
verified: ``_fetch_github_claims`` raises unless the account has a
primary+verified email, so a GitHub-linked row with an email cannot have been
created from an unverified address. OIDC/Google/Microsoft rows are left alone —
their ``email_verified`` claim is per-provider and older rows predate the H-30
gate, so asserting verification for them would be a guess. Those converge on
next login instead (the returning-user refresh added alongside this migration).

Revision ID: 0028_oauth_email_verified_backfill
Revises: 0027_source_format_parquet
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0028_oauth_email_verified_backfill"
down_revision: Union[str, None] = "0027_source_format_parquet"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE catalog.users u
        SET email_verified = true
        WHERE u.auth_provider = 'oauth'
          AND u.email IS NOT NULL
          AND u.email_verified = false
          AND EXISTS (
              SELECT 1
              FROM catalog.oauth_accounts a
              JOIN catalog.oauth_providers p ON p.id = a.provider_id
              WHERE a.user_id = u.id
                AND p.provider_type = 'github'
          )
        """
    )


def downgrade() -> None:
    # Not reversible: the pre-migration false was indistinguishable from a
    # genuinely-unverified row, so there is nothing to restore it to. Leaving the
    # backfilled value is the honest no-op — it is what the provider asserted.
    pass
