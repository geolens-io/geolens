"""Allow the ``vrt_overview`` key on catalog.dataset_assets.

A VRT mosaic over members without overviews stores a half-resolution overview
COG beside the VRT. It is a materialized raster, so it gets a ``dataset_assets``
row of its own that the per-user storage sum counts.

The downgrade restores the old list as ``NOT VALID``: existing rows are kept
and not checked, and only new writes are held to the old list.

Revision ID: 0102_dataset_assets_vrt_overview
Revises: 0101_drop_dataset_previous_version_columns
Create Date: 2026-11-04
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0102_dataset_assets_vrt_overview"
down_revision: Union[str, None] = "0101_drop_dataset_previous_version_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
_OLD_CHECK = (
    "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata', 'tileset', "
    "'pointcloud') OR key LIKE 'archived_original:%' "
    "OR key LIKE 'retained_cog:%'"
)
_NEW_CHECK = (
    "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata', 'tileset', "
    "'pointcloud', 'vrt_overview') OR key LIKE 'archived_original:%' "
    "OR key LIKE 'retained_cog:%'"
)


def _replace_check(check: str, *, validate: bool) -> None:
    op.execute(_LOCK_TIMEOUT)
    op.drop_constraint(
        "chk_dataset_assets_key", "dataset_assets", schema="catalog", type_="check"
    )
    op.execute(
        "ALTER TABLE catalog.dataset_assets ADD CONSTRAINT chk_dataset_assets_key "
        f"CHECK ({check})" + ("" if validate else " NOT VALID")
    )


def upgrade() -> None:
    _replace_check(_NEW_CHECK, validate=True)


def downgrade() -> None:
    _replace_check(_OLD_CHECK, validate=False)
