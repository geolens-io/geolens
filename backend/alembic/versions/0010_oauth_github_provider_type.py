"""Widen chk_oauth_providers_type CHECK to include 'github' (SSO-05, Phase 1237).

Background
----------
The OSS baseline (``0001_baseline.py:205``) created ``chk_oauth_providers_type``
as ``provider_type IN ('oidc', 'google', 'microsoft')``.  Enterprise migration
``e002_add_saml_columns`` (overlay repo) later widened it to include ``'saml'``.

This migration adds ``'github'`` so that an admin can create a GitHub OAuth2
provider via ``POST /settings/oauth-providers/`` with ``provider_type='github'``.
GitHub is plain OAuth2 (not OIDC — no discovery URL, no id_token); its fixed
endpoints are auto-populated by ``create_provider`` in the service layer.

Upgrade strategy
----------------
``DROP CONSTRAINT IF EXISTS`` then ``ADD CONSTRAINT`` recreating the literal as
``('oidc', 'google', 'microsoft', 'saml', 'github')``.  **'saml' is included**
so the constraint composes correctly whether or not the enterprise ``e002`` has
already run against this database — matching the model's ``__table_args__`` CHECK
literal for DB/model parity.  ``IF EXISTS`` makes the drop idempotent.

Downgrade strategy
------------------
Recreate the constraint WITHOUT ``'github'`` but KEEP ``'saml'``:
``('oidc', 'google', 'microsoft', 'saml')``.  Dropping ``'saml'`` on downgrade
would risk data loss on enterprise deployments and is explicitly forbidden by the
0008 co-owned-constraint lesson.  Before changing the constraint, lock the table
and refuse the downgrade while GitHub providers exist; provider credentials and
dependent identities require an explicit operator-approved migration or removal
plan.  The constraint replacement remains idempotent (``DROP ... IF EXISTS``).

Head-coupling note
------------------
Adding this migration advances the alembic head: ``0009_email_verification`` →
``0010_oauth_github_provider_type``.  After writing this file the head-coupled CI
tests (``test_tenant_rls_migration.py``, ``test_email_verification_migration.py``,
``test_ci_alembic_filter_paths.py``) must remain green.  The focused downgrade
test targets this migration's parent explicitly so newer heads cannot mask the
constraint transition.

Cross-repo compatibility contract
---------------------------------
Any overlay migration that recreates ``chk_oauth_providers_type`` must write the
same full provider union as this migration.  The current enterprise ``e002``
does so, which makes the final constraint independent of which branch writes it
last.  Overlay-owned CI can exercise the real package against this core through
``scripts/verify_overlay_migrations.py``; public core CI does not fetch private
overlay source.

Revision ID: 0010_oauth_github_provider_type
Revises:     0009_email_verification
Create Date: 2026-06-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_oauth_github_provider_type"
down_revision: Union[str, None] = "0009_email_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_no_github_providers() -> None:
    """Block rollback rather than deleting or coercing provider credentials."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            LOCK TABLE catalog.oauth_providers
            IN SHARE ROW EXCLUSIVE MODE
            """
        )
    )
    github_provider_count = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM catalog.oauth_providers
            WHERE provider_type = 'github'
            """
        )
    ).scalar_one()

    if github_provider_count:
        raise RuntimeError(
            "Cannot downgrade 0010_oauth_github_provider_type while "
            f"{github_provider_count} GitHub OAuth provider(s) exist. Back up "
            "and explicitly migrate or remove those providers and any dependent "
            "identities, or cancel the downgrade. GeoLens will not delete or "
            "coerce provider credentials automatically."
        )


def upgrade() -> None:
    """Widen chk_oauth_providers_type to include 'github' (and retain 'saml').

    Idempotent: DROP CONSTRAINT IF EXISTS before ADD CONSTRAINT so that
    re-running after a NO-OP downgrade does not fail with a duplicate-constraint
    error.  The 'saml' entry is included so the constraint composes whether or
    not the enterprise e002 migration has run.
    """
    op.execute(
        """
        ALTER TABLE catalog.oauth_providers
            DROP CONSTRAINT IF EXISTS chk_oauth_providers_type
        """
    )
    op.execute(
        """
        ALTER TABLE catalog.oauth_providers
            ADD CONSTRAINT chk_oauth_providers_type
            CHECK (provider_type IN ('oidc', 'google', 'microsoft', 'saml', 'github'))
        """
    )


def downgrade() -> None:
    """Remove 'github' from the constraint, retaining 'saml'.

    Co-owned-constraint caution (0008 lesson): do NOT drop 'saml' — it is
    co-owned by the enterprise overlay migration e002.  Dropping it on downgrade
    would break enterprise deployments where SAML providers already exist.

    Idempotent: DROP CONSTRAINT IF EXISTS before re-ADD.  A locked preflight
    blocks the operation before DDL when live GitHub providers would violate the
    restored constraint.
    """
    _assert_no_github_providers()

    op.execute(
        """
        ALTER TABLE catalog.oauth_providers
            DROP CONSTRAINT IF EXISTS chk_oauth_providers_type
        """
    )
    op.execute(
        """
        ALTER TABLE catalog.oauth_providers
            ADD CONSTRAINT chk_oauth_providers_type
            CHECK (provider_type IN ('oidc', 'google', 'microsoft', 'saml'))
        """
    )
