"""Add 3D geometry columns to catalog.datasets.

Adds four nullable columns to the datasets table to store PostGIS-derived
3D geometry metadata: is_3d, n_dims, z_min, z_max.

These columns are populated during ingest by calling detect_3d_metadata()
which queries ST_NDims, ST_Is3D, ST_ZMin, ST_ZMax on the geom column.

Revision ID: a1b2c3d4e5f7
Revises: f3a4b5c6d7e8
Create Date: 2026-04-12 15:00:00
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("is_3d", sa.Boolean(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("n_dims", sa.SmallInteger(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("z_min", sa.Float(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("z_max", sa.Float(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("datasets", "z_max", schema="catalog")
    op.drop_column("datasets", "z_min", schema="catalog")
    op.drop_column("datasets", "n_dims", schema="catalog")
    op.drop_column("datasets", "is_3d", schema="catalog")
