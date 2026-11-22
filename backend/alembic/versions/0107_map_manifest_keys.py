"""Maps and map layers gain a nullable manifest key.

A map's key is unique across the server and a layer's key is unique within
its map. Existing rows keep none.

Revision ID: 0107_map_manifest_keys
Revises: 0106_map_bookmarks
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0107_map_manifest_keys"
down_revision: Union[str, None] = "0106_map_bookmarks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    """Add the two key columns and their partial unique indexes."""
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.maps ADD COLUMN IF NOT EXISTS manifest_key varchar(128)"
    )
    op.execute(
        "ALTER TABLE catalog.map_layers "
        "ADD COLUMN IF NOT EXISTS manifest_key varchar(128)"
    )
    # Every existing row is NULL, so the partial indexes start empty.
    op.create_index(
        "uq_maps_manifest_key",
        "maps",
        ["manifest_key"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("manifest_key IS NOT NULL"),
    )
    op.create_index(
        "uq_map_layers_map_manifest_key",
        "map_layers",
        ["map_id", "manifest_key"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("manifest_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the keys and their indexes."""
    op.execute(_LOCK_TIMEOUT)
    op.drop_index(
        "uq_map_layers_map_manifest_key", table_name="map_layers", schema="catalog"
    )
    op.drop_index("uq_maps_manifest_key", table_name="maps", schema="catalog")
    op.drop_column("map_layers", "manifest_key", schema="catalog")
    op.drop_column("maps", "manifest_key", schema="catalog")
