"""Add persisted map terrain configuration."""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0005_map_terrain_config"
down_revision: Union[str, None] = "0004_style_config_paint_cleanup"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column(
            "terrain_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("maps", "terrain_config", schema="catalog")
