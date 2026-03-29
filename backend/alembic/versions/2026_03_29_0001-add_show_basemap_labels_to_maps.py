"""add_show_basemap_labels_to_maps

Revision ID: a1b2c3d4e5f6
Revises: f994a5f8866e
Create Date: 2026-03-29

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f994a5f8866e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column(
            "show_basemap_labels", sa.Boolean(), server_default="true", nullable=False
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("maps", "show_basemap_labels", schema="catalog")
