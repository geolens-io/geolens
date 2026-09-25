"""Allow the internal 'pointcloud' asset key and add a point cloud's facts.

A COPC point cloud keeps one 'pointcloud' asset row. Its href points at the
live upload attempt's file under ``pointclouds/<dataset_id>/``, and its
size_bytes is what the per-user storage quota counts. The dataset row keeps
the file's point count, point data record format and vertical CRS name, read
from its header at upload. The columns are null for every other record type.

Revision ID: 0071_pointcloud_asset_and_facts
Revises: 0070_pointcloud_record_type
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0071_pointcloud_asset_and_facts"
down_revision: Union[str, None] = "0070_pointcloud_record_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_CHECK = (
    "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata', 'tileset') "
    "OR key LIKE 'archived_original:%'"
)
_NEW_CHECK = (
    "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata', 'tileset', "
    "'pointcloud') OR key LIKE 'archived_original:%'"
)


def _replace_check(check: str) -> None:
    op.drop_constraint(
        "chk_dataset_assets_key", "dataset_assets", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_dataset_assets_key", "dataset_assets", check, schema="catalog"
    )


def upgrade() -> None:
    _replace_check(_NEW_CHECK)
    op.add_column(
        "datasets",
        sa.Column("pointcloud_point_count", sa.BigInteger(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("pointcloud_point_format", sa.SmallInteger(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("pointcloud_vertical_crs", sa.String(length=255), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    # Fails loudly while any point cloud row exists: the row is the only
    # pointer to its point cloud's live file, so it is not dropped to make room.
    _replace_check(_OLD_CHECK)
    op.drop_column("datasets", "pointcloud_vertical_crs", schema="catalog")
    op.drop_column("datasets", "pointcloud_point_format", schema="catalog")
    op.drop_column("datasets", "pointcloud_point_count", schema="catalog")
