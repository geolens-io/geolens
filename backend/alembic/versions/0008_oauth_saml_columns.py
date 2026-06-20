"""Add the 4 OAuth-provider SAML columns to the OSS schema (community OAuth-create fix).

Background
----------
``OAuthProvider`` (``backend/app/modules/auth/oauth/models.py``) is a single
union model serving both OSS and enterprise: it declares the four SAML columns
``idp_entity_id``, ``idp_sso_url``, ``idp_certificate``, ``sp_entity_id`` with
``deferred=True`` so they stay out of the default ``SELECT``. The OSS baseline
(``0001_baseline.py``) intentionally omitted those columns; only the enterprise
overlay migration ``e002_add_saml_columns`` created them.

The bug
-------
``deferred=True`` keeps the columns out of *list/get* SELECTs, but it does NOT
keep them out of:
  1. the **INSERT** emitted by ``create_provider`` (a fresh ORM flush writes
     every set attribute, and the service sets all four — to ``NULL`` for
     non-SAML providers), and
  2. the **create-response serialization** — ``OAuthProviderResponse`` includes
     the four SAML fields, so reading them off the just-inserted row triggers a
     deferred load.
On an OSS deployment (no ``e002``) both paths hit columns that don't exist, so
``POST /api/settings/oauth-providers/`` — e.g. configuring Google/OIDC sign-in —
fails with ``UndefinedColumnError`` and a 500. OAuth provider creation is
therefore broken on every community deployment.

The fix
-------
Bring the OSS schema in line with the union model by adding the four nullable
SAML columns. ``ADD COLUMN IF NOT EXISTS`` makes this:
  - effective on OSS (columns are created), and
  - a **no-op on enterprise** (``e002`` already created them) regardless of the
    order in which the two migrations apply.
Only the *columns* are added here — the ``'saml'`` ``provider_type`` CHECK
constraint stays enterprise-only (``e002``), so community deployments still
cannot create SAML providers (also guarded by ``is_enterprise()`` in the
service layer). The columns simply sit ``NULL`` for OSS OAuth/OIDC providers.

``env.py``'s ``include_object`` continues to exclude these four columns from
``alembic check`` on both the model and reflected sides, so the drift gate stays
green and unchanged.

Revision ID: 0008_oauth_saml_columns
Revises:     0007_tenant_data_schemas
Create Date: 2026-06-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008_oauth_saml_columns"
down_revision: Union[str, None] = "0007_tenant_data_schemas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure the four nullable SAML columns exist on catalog.oauth_providers.

    Idempotent (``IF NOT EXISTS``) so it is a no-op on enterprise deployments
    where ``e002_add_saml_columns`` already created them. Types mirror the
    union model: ``idp_certificate`` is TEXT (Fernet ciphertext); the other
    three are VARCHAR(512).
    """
    op.execute(
        """
        ALTER TABLE catalog.oauth_providers
            ADD COLUMN IF NOT EXISTS idp_entity_id   VARCHAR(512),
            ADD COLUMN IF NOT EXISTS idp_sso_url     VARCHAR(512),
            ADD COLUMN IF NOT EXISTS idp_certificate TEXT,
            ADD COLUMN IF NOT EXISTS sp_entity_id    VARCHAR(512)
        """
    )


def downgrade() -> None:
    """No-op: intentionally does NOT drop the four SAML columns.

    These columns are co-owned by the enterprise migration
    ``e002_add_saml_columns`` (also ``ADD COLUMN IF NOT EXISTS``). Dropping them
    on downgrade would:
      1. remove enterprise SAML configuration on any DB where both migrations
         applied (data loss), and
      2. break test isolation — the migration round-trip tests downgrade a
         shared per-worker test DB below 0008, and dropping the columns would
         strand concurrent OAuth tests that rely on them (UndefinedColumnError).

    Leaving the columns is harmless: they are nullable and unused by OSS
    OAuth/OIDC providers, and it matches the pre-0008 behaviour where the
    columns were added out-of-band (so a downgrade never removed them). A full
    ``downgrade base`` simply leaves four empty nullable columns behind —
    preferable to risking enterprise data or cross-test contamination.
    """
    pass
