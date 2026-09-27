"""Allow the ``retained_cog`` key on catalog.dataset_assets.

A replaced raster that a VRT mosaic still reads keeps its superseded COG, which
the mosaic names by key. Quota sums ``dataset_assets`` rows, and the replacement
moves the ``data`` row to the new COG, so the kept object needs a row of its own
to stay counted until it is reclaimed. The key is ``retained_cog:<attempt_id>``,
one row per replacement that kept a COG.

Revision ID: 0075_dataset_assets_retained_cog
Revises: 0074_pointcloud_attempt_id
Create Date: 2026-09-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0075_dataset_assets_retained_cog"
down_revision: Union[str, None] = "0074_pointcloud_attempt_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
_OLD_CHECK = (
    "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata', 'tileset', "
    "'pointcloud') OR key LIKE 'archived_original:%'"
)
_NEW_CHECK = f"{_OLD_CHECK} OR key LIKE 'retained_cog:%'"


def _replace_check(check: str) -> None:
    op.execute(_LOCK_TIMEOUT)
    op.drop_constraint(
        "chk_dataset_assets_key", "dataset_assets", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_dataset_assets_key", "dataset_assets", check, schema="catalog"
    )


def upgrade() -> None:
    _replace_check(_NEW_CHECK)


def downgrade() -> None:
    # Fails loudly while any retained_cog row exists: the row is the only
    # pointer to its kept COG, so it is not dropped to make room.
    _replace_check(_OLD_CHECK)
