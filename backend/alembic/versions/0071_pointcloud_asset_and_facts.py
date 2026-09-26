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


def _assert_no_pointclouds() -> None:
    """Block the downgrade rather than drop a point cloud's facts or file pointer."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            LOCK TABLE catalog.records, catalog.datasets, catalog.dataset_assets
            IN SHARE ROW EXCLUSIVE MODE
            """
        )
    )
    pointcloud_count = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM catalog.datasets d
            LEFT JOIN catalog.records r ON r.id = d.record_id
            WHERE r.record_type = 'pointcloud_dataset'
               OR d.pointcloud_point_count IS NOT NULL
               OR d.pointcloud_point_format IS NOT NULL
               OR d.pointcloud_vertical_crs IS NOT NULL
               OR EXISTS (
                   SELECT 1 FROM catalog.dataset_assets a
                   WHERE a.dataset_id = d.id AND a.key = 'pointcloud'
               )
            """
        )
    ).scalar_one()

    if pointcloud_count:
        raise RuntimeError(
            "Cannot downgrade 0071_pointcloud_asset_and_facts while "
            f"{pointcloud_count} point cloud dataset(s) exist. Delete them, or "
            "cancel the downgrade. GeoLens will not drop a point cloud's facts "
            "or the pointer to its file automatically."
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
    _assert_no_pointclouds()
    _replace_check(_OLD_CHECK)
    op.drop_column("datasets", "pointcloud_vertical_crs", schema="catalog")
    op.drop_column("datasets", "pointcloud_point_format", schema="catalog")
    op.drop_column("datasets", "pointcloud_point_count", schema="catalog")
