"""Drop the four emptied ``catalog.datasets.previous_version_*`` columns.

0088 moved each kept version onto its ``catalog.dataset_versions`` row and
left these columns in place, empty, for 1.26 processes still running during a
rolling upgrade to 1.27. No release since 1.27 reads or writes them.
Databases that ran the 1.27.0 form of 0088 already lack them, hence
``IF EXISTS``.

The downgrade adds them back empty, as 0088 left them.

Revision ID: 0101_drop_dataset_previous_version_columns
Revises: 0100_map_show_attribute_table
Create Date: 2026-10-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0101_drop_dataset_previous_version_columns"
down_revision: Union[str, None] = "0100_map_show_attribute_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.datasets "
        "DROP COLUMN IF EXISTS previous_version_number, "
        "DROP COLUMN IF EXISTS previous_version_retained_at, "
        "DROP COLUMN IF EXISTS previous_version_bytes, "
        "DROP COLUMN IF EXISTS previous_version_refreshed_at"
    )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.datasets "
        "ADD COLUMN IF NOT EXISTS previous_version_number integer, "
        "ADD COLUMN IF NOT EXISTS "
        "previous_version_retained_at timestamp with time zone, "
        "ADD COLUMN IF NOT EXISTS previous_version_bytes bigint, "
        "ADD COLUMN IF NOT EXISTS "
        "previous_version_refreshed_at timestamp with time zone"
    )
