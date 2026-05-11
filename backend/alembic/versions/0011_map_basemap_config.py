"""Add persisted map basemap appearance configuration."""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0017_map_basemap_config"
down_revision: Union[str, None] = "0016_drop_redundant_data_gid_indexes"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column(
            "basemap_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("maps", "basemap_config", schema="catalog")
