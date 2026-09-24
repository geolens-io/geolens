"""Allow the internal 'tileset' key in chk_dataset_assets_key.

A 3D Tiles dataset keeps one 'tileset' asset row. Its href points at the live
unpack attempt under ``tiles3d/<dataset_id>/``, and its size_bytes, the
unpacked total, is what the per-user storage quota counts.

Revision ID: 0066_tileset_asset_key
Revises: 0065_tiles3d_record_type
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0066_tileset_asset_key"
down_revision: Union[str, None] = "0065_tiles3d_record_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_CHECK = (
    "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata') "
    "OR key LIKE 'archived_original:%'"
)
_NEW_CHECK = (
    "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata', 'tileset') "
    "OR key LIKE 'archived_original:%'"
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


def downgrade() -> None:
    # Fails loudly while any tileset row exists: the row is the only pointer to
    # its tileset's live attempt, so it is not dropped to make room.
    _replace_check(_OLD_CHECK)
