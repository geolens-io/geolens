"""Reset stale upload_allowed_extensions DB override so env default takes effect.

The DB row was saved before raster support (v10.0) was added and is missing
.tif, .tiff, .xlsx, .xls.  Deleting it lets PersistentConfig fall through to
the env default: .zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-03-31
"""

from typing import Union

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM catalog.app_settings WHERE key = 'upload_allowed_extensions'"
    )


def downgrade() -> None:
    # Intentionally empty — the deleted row contained a stale value that
    # pre-dated raster support.  There is nothing meaningful to restore.
    pass
