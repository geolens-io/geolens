"""Retain the columns each version's geometry was built from.

Revision ID: 0105_dataset_version_geometry_columns
Revises: 0104_map_author_api_keys
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0105_dataset_version_geometry_columns"
down_revision: Union[str, None] = "0104_map_author_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    """Version history gains a nullable record of its geometry columns."""
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.dataset_versions "
        "ADD COLUMN IF NOT EXISTS geometry_columns jsonb"
    )


def downgrade() -> None:
    """Version history drops its record of geometry columns."""
    op.execute(_LOCK_TIMEOUT)
    op.drop_column("dataset_versions", "geometry_columns", schema="catalog")
