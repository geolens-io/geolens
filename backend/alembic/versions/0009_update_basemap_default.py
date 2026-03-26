"""update basemap_style server_default from positron to openfreemap-positron

Revision ID: 0009_update_basemap_default
Revises: 0008_normalize_outline_paint
Create Date: 2026-03-26
"""

from alembic import op

revision = "0009_update_basemap_default"
down_revision = "0008_normalize_outline_paint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "maps",
        "basemap_style",
        server_default="openfreemap-positron",
    )


def downgrade() -> None:
    op.alter_column(
        "maps",
        "basemap_style",
        server_default="positron",
    )
