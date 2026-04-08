"""Strip dead SAML code from oauth_providers and users CHECK constraints.

The OAuth provider system shipped with `provider_type='saml'` accepted by the
schema, models, and service layer — but no SAML login router was ever wired up.
An admin could create a SAML provider through the API and have it appear on the
login page, but clicking the button did nothing because the callback handler
was missing.

This migration removes the dead SAML code path:

- Drops the four SAML-specific columns from `catalog.oauth_providers`
  (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`).
- Tightens the `chk_oauth_providers_type` CHECK constraint to allow only
  ('oidc', 'google', 'microsoft').
- Tightens the `chk_users_auth_provider` CHECK constraint to allow only
  ('local', 'oidc', 'oauth').

Any existing rows with `provider_type='saml'` or `auth_provider='saml'` are
deleted/migrated before tightening the constraints to avoid blocking the
migration on legacy data. In practice no rows should exist because the SAML
flow never functioned end-to-end.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-08
"""

from typing import Union

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Remove any legacy SAML provider rows. The dead code path could only
    # produce records with provider_type='saml' if an admin manually used the
    # API; the rows would have been non-functional placeholders.
    op.execute(
        "DELETE FROM catalog.oauth_accounts WHERE provider_id IN "
        "(SELECT id FROM catalog.oauth_providers WHERE provider_type = 'saml')"
    )
    op.execute("DELETE FROM catalog.oauth_providers WHERE provider_type = 'saml'")

    # 2. Migrate any users that somehow have auth_provider='saml' to 'oauth'
    # so the new constraint passes. Such users could not actually log in.
    op.execute(
        "UPDATE catalog.users SET auth_provider = 'oauth' WHERE auth_provider = 'saml'"
    )

    # 3. Drop SAML-specific columns from oauth_providers.
    op.drop_column("oauth_providers", "idp_entity_id", schema="catalog")
    op.drop_column("oauth_providers", "idp_sso_url", schema="catalog")
    op.drop_column("oauth_providers", "idp_certificate", schema="catalog")
    op.drop_column("oauth_providers", "sp_entity_id", schema="catalog")

    # 4. Tighten CHECK constraints. PostgreSQL requires drop + recreate.
    op.drop_constraint(
        "chk_oauth_providers_type",
        "oauth_providers",
        type_="check",
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_oauth_providers_type",
        "oauth_providers",
        "provider_type IN ('oidc', 'google', 'microsoft')",
        schema="catalog",
    )

    op.drop_constraint(
        "chk_users_auth_provider",
        "users",
        type_="check",
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_users_auth_provider",
        "users",
        "auth_provider IN ('local', 'oidc', 'oauth')",
        schema="catalog",
    )


def downgrade() -> None:
    # Re-add SAML support to constraints (data restoration is not possible).
    op.drop_constraint(
        "chk_users_auth_provider",
        "users",
        type_="check",
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_users_auth_provider",
        "users",
        "auth_provider IN ('local', 'oidc', 'saml', 'oauth')",
        schema="catalog",
    )

    op.drop_constraint(
        "chk_oauth_providers_type",
        "oauth_providers",
        type_="check",
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_oauth_providers_type",
        "oauth_providers",
        "provider_type IN ('oidc', 'google', 'microsoft', 'saml')",
        schema="catalog",
    )

    # Re-add SAML columns as nullable so existing rows still validate.
    from sqlalchemy import Column, String, Text

    op.add_column(
        "oauth_providers",
        Column("idp_entity_id", String(512), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "oauth_providers",
        Column("idp_sso_url", String(512), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "oauth_providers",
        Column("idp_certificate", Text, nullable=True),
        schema="catalog",
    )
    op.add_column(
        "oauth_providers",
        Column("sp_entity_id", String(512), nullable=True),
        schema="catalog",
    )
