"""Add is_dem column to raster_assets for DEM terrain identification.

Adds a boolean column that flags raster assets as Digital Elevation Models.
Auto-set during ingest via single-band float heuristic; manually toggleable
by dataset owner or admin.

Revision ID: b2c3d4e5f6a7
Revises: 989ae68d7859
Create Date: 2026-04-12 14:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "989ae68d7859"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raster_assets",
        sa.Column(
            "is_dem",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("raster_assets", "is_dem", schema="catalog")
