"""Record the live upload attempt of a COPC point cloud on its dataset.

A point cloud's file is served at a URL that names its upload attempt. The
record, the catalog feeds and the dataset response load the dataset row but
not its 'pointcloud' asset row, so the attempt id goes on the dataset beside
the point cloud's other facts. The upgrade copies it from each point cloud's
asset row, where that row names exactly one of the dataset's attempt objects.

Revision ID: 0074_pointcloud_attempt_id
Revises: 0073_raster_crs_facts
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0074_pointcloud_attempt_id"
down_revision: Union[str, None] = "0073_raster_crs_facts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
_UUID = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def upgrade() -> None:
    # ADD COLUMN locks datasets. Fail fast on a busy table rather than queue
    # ahead of API traffic.
    op.execute(_LOCK_TIMEOUT)
    op.add_column(
        "datasets",
        sa.Column(
            "pointcloud_attempt_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        schema="catalog",
        if_not_exists=True,
    )
    # Committed first, so readers never queue behind the ADD COLUMN's lock
    # while the backfill waits on a row. IS NULL keeps what a concurrent
    # publish wrote and lets a failed backfill be retried.
    with op.get_context().autocommit_block():
        # SET LOCAL ended with that commit. A session setting bounds the wait,
        # and RESET keeps it out of the migrations after this one.
        op.execute("SET lock_timeout = '5s'")
        try:
            _backfill()
        finally:
            op.execute("RESET lock_timeout")


def _backfill() -> None:
    op.execute(
        sa.text(
            """
            UPDATE catalog.datasets AS d
            SET pointcloud_attempt_id = CAST(split_part(a.href, '/', 3) AS uuid)
            FROM catalog.dataset_assets AS a
            WHERE a.dataset_id = d.id
              AND a.key = 'pointcloud'
              AND d.pointcloud_attempt_id IS NULL
              AND split_part(a.href, '/', 3) ~ :uuid
              AND a.href = 'pointclouds/' || d.id::text || '/'
                  || split_part(a.href, '/', 3) || '/data.copc.laz'
            """
        ).bindparams(uuid=_UUID)
    )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.drop_column("datasets", "pointcloud_attempt_id", schema="catalog")
