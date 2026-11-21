"""Maps keep a nullable list of bookmarks.

Revision ID: 0106_map_bookmarks
Revises: 0105_dataset_version_geometry_columns
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0106_map_bookmarks"
down_revision: Union[str, None] = "0105_dataset_version_geometry_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    """Maps gain a nullable bookmarks column; existing rows keep none."""
    op.execute(_LOCK_TIMEOUT)
    op.execute("ALTER TABLE catalog.maps ADD COLUMN IF NOT EXISTS bookmarks jsonb")


def downgrade() -> None:
    """Maps drop their bookmarks."""
    op.execute(_LOCK_TIMEOUT)
    op.drop_column("maps", "bookmarks", schema="catalog")
