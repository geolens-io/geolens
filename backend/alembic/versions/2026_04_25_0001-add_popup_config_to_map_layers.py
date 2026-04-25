"""Add popup_config column to map_layers.

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-04-25 20:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "t6u7v8w9x0y1"
down_revision = "s5t6u7v8w9x0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "map_layers",
        sa.Column(
            "popup_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("map_layers", "popup_config", schema="catalog")
