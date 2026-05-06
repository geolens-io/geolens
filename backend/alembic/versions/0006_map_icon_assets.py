"""Add map icon assets for sprite-backed symbols."""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0006_map_icon_assets"
down_revision: Union[str, None] = "0005_map_terrain_config"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.create_table(
        "map_icon_assets",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "media_type IN ('image/svg+xml', 'image/png')",
            name="chk_map_icon_assets_media_type",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["catalog.users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("slug", name="uq_map_icon_assets_slug"),
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_map_icon_assets_created_by",
        "map_icon_assets",
        ["created_by"],
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_map_icon_assets_slug",
        "map_icon_assets",
        ["slug"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_map_icon_assets_slug",
        table_name="map_icon_assets",
        schema="catalog",
    )
    op.drop_index(
        "ix_catalog_map_icon_assets_created_by",
        table_name="map_icon_assets",
        schema="catalog",
    )
    op.drop_table("map_icon_assets", schema="catalog")
