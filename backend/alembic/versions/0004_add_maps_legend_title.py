"""Add catalog.maps.legend_title column.

Additive, nullable text column for the custom map-level legend title
(ENH-06, Phase 1201). Null means "no custom title" — the legend renders
without a heading override. The existing `plugins` column cannot hold this
value (it is list[str] of enabled plugin IDs) and the basemap/terrain JSONB
blobs are extra="forbid"-validated, so a dedicated nullable column is the
correct home.

Revision ID: 0004_add_maps_legend_title
Revises: 0003_normalize_dem_hillshade_style
Create Date: 2026-06-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_maps_legend_title"
down_revision: Union[str, None] = "0003_normalize_dem_hillshade_style"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column("legend_title", sa.Text(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("maps", "legend_title", schema="catalog")
