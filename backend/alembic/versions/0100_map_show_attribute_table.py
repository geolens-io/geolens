"""Maps gain a setting that lets readers open a layer's attribute table.

Revision ID: 0100_map_show_attribute_table
Revises: 0099_story_group_grants
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0100_map_show_attribute_table"
down_revision: Union[str, None] = "0099_story_group_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    """Maps gain show_attribute_table, on for every map; the previous release
    never reads it, and the constant default keeps the ALTER a catalog-only change."""
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.maps ADD COLUMN IF NOT EXISTS show_attribute_table"
        " boolean NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    """Maps drop the reader attribute table setting."""
    op.execute(_LOCK_TIMEOUT)
    op.drop_column("maps", "show_attribute_table", schema="catalog")
