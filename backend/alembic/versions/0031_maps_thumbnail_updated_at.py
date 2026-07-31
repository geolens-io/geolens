"""Give the map thumbnail its own timestamp, separate from the map's.

fix(#1005): ``catalog.maps.updated_at`` was doing double duty as the thumbnail
cache version. ``MapCard``/``MapCardGrid`` pass it to ``useMapThumbnail`` as the
``?v=`` version and part of the query key, so a re-captured thumbnail only shows
after an edit because ``updated_at`` moved. But the same upload endpoints serve
the lazy backfill that fires when an owner first opens a thumbnail-less map in
the builder, editing nothing -- and that write bumped ``updated_at`` too, which
reordered the "Last updated" gallery for what was a read.

The backend cannot tell the two flows apart: one ``captureThumbnail`` call
drives both, and it uploads two images (the 400x250 thumbnail and the 1200x630
OG card), so each backfill bumped ``updated_at`` twice.

``thumbnail_updated_at`` splits the two meanings. It is nullable rather than
backfilled from ``updated_at``: the frontend falls back to ``updated_at`` when
it is null, so existing maps keep exactly the cache version they have today,
and a backfill would only invent a timestamp that is already available.

Revision ID: 0031_maps_thumbnail_updated_at
Revises: 0030_records_spatial_extent_type
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_maps_thumbnail_updated_at"
down_revision: Union[str, None] = "0030_records_spatial_extent_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column("thumbnail_updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("maps", "thumbnail_updated_at", schema="catalog")
