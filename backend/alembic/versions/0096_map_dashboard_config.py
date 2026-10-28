"""Maps gain a nullable dashboard configuration.

Revision ID: 0096_map_dashboard_config
Revises: 0095_stories
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0096_map_dashboard_config"
down_revision: Union[str, None] = "0095_stories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    """Maps gain a nullable dashboard_config; the previous release never reads it."""
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.maps ADD COLUMN IF NOT EXISTS dashboard_config jsonb"
    )


def downgrade() -> None:
    """Maps drop their dashboard configuration."""
    op.execute(_LOCK_TIMEOUT)
    op.drop_column("maps", "dashboard_config", schema="catalog")
