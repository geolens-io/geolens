"""add show_in_legend column to map_layers

Revision ID: 0006_add_show_in_legend
Revises: 0005_schema_fixes
Create Date: 2026-03-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_add_show_in_legend"
down_revision = "0005_schema_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "map_layers",
        sa.Column("show_in_legend", sa.Boolean(), server_default="true", nullable=False),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("map_layers", "show_in_legend", schema="catalog")
