"""Migrate Map.thumbnail from inline base64 data URI to storage-backed thumbnail_uri.

Renames the column from 'thumbnail' to 'thumbnail_uri'. Existing base64 data
is cleared (set to NULL) since it cannot be converted to a storage key without
the storage provider running. Maps will regenerate thumbnails on next save.

Revision ID: 0012_map_thumbnail_to_storage
Revises: 0011_model_review_fixes
Create Date: 2026-03-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_map_thumbnail_to_storage"
down_revision = "0011_model_review_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename column from 'thumbnail' to 'thumbnail_uri'
    op.alter_column(
        "maps",
        "thumbnail",
        new_column_name="thumbnail_uri",
        schema="catalog",
    )
    # Clear existing base64 data URIs — they are not valid storage keys.
    # Maps will regenerate thumbnails on the next save/load in the builder.
    op.execute(
        "UPDATE catalog.maps SET thumbnail_uri = NULL WHERE thumbnail_uri IS NOT NULL"
    )


def downgrade() -> None:
    op.alter_column(
        "maps",
        "thumbnail_uri",
        new_column_name="thumbnail",
        schema="catalog",
    )
