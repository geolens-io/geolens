"""Add the content types and required extensions a 3D Tiles dataset keeps.

The upload finds them by reading every file of the tileset: the tile formats
it holds and the extensionsRequired of its tileset JSON and glTF content.
They say which clients can load the tileset. Null for every other record
type, and for a tileset published before this revision.

Revision ID: 0068_tileset_contents
Revises: 0067_tileset_facts
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0068_tileset_contents"
down_revision: Union[str, None] = "0067_tileset_facts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("tileset_content_types", postgresql.ARRAY(sa.Text()), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column(
            "tileset_extensions_required", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("datasets", "tileset_extensions_required", schema="catalog")
    op.drop_column("datasets", "tileset_content_types", schema="catalog")
