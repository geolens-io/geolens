"""Retain each version's column metadata for restores.

Revision ID: 0093_dataset_version_columns
Revises: 0092_dataset_group_grant_tenant
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0093_dataset_version_columns"
down_revision: Union[str, None] = "0092_dataset_group_grant_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    """Version history gains a nullable column metadata snapshot."""
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.dataset_versions "
        "ADD COLUMN IF NOT EXISTS column_info jsonb"
    )


def downgrade() -> None:
    """Version history drops its column metadata snapshot."""
    op.execute(_LOCK_TIMEOUT)
    op.drop_column("dataset_versions", "column_info", schema="catalog")
