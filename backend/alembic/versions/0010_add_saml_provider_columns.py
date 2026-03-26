"""Add SAML-specific columns to oauth_providers table.

Revision ID: 0010_add_saml_provider_columns
Revises: 0009_update_basemap_default
Create Date: 2026-03-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_add_saml_provider_columns"
down_revision = "0009_update_basemap_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oauth_providers",
        sa.Column("idp_entity_id", sa.String(512), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "oauth_providers",
        sa.Column("idp_sso_url", sa.String(512), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "oauth_providers",
        sa.Column("idp_certificate", sa.Text, nullable=True),
        schema="catalog",
    )
    op.add_column(
        "oauth_providers",
        sa.Column("sp_entity_id", sa.String(512), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("oauth_providers", "sp_entity_id", schema="catalog")
    op.drop_column("oauth_providers", "idp_certificate", schema="catalog")
    op.drop_column("oauth_providers", "idp_sso_url", schema="catalog")
    op.drop_column("oauth_providers", "idp_entity_id", schema="catalog")
