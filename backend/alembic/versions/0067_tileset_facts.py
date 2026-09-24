"""Add the three tileset facts a 3D Tiles dataset keeps on its dataset row.

The upload reads them from the tileset's own tileset.json: ``asset.version``,
the root tile's ``geometricError`` and which bounding volume the root declares.
The dataset page shows them, and the volume kind says why a box or sphere
tileset has no extent. Null for every other record type.

Revision ID: 0067_tileset_facts
Revises: 0066_tileset_asset_key
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0067_tileset_facts"
down_revision: Union[str, None] = "0066_tileset_asset_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("tileset_version", sa.String(length=8), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("tileset_geometric_error", sa.Float(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("tileset_bounding_volume", sa.String(length=10), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("datasets", "tileset_bounding_volume", schema="catalog")
    op.drop_column("datasets", "tileset_geometric_error", schema="catalog")
    op.drop_column("datasets", "tileset_version", schema="catalog")
