"""add_widgets_to_maps

Revision ID: f994a5f8866e
Revises: 0003_prc
Create Date: 2026-03-28 17:29:04.347525

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f994a5f8866e"
down_revision: Union[str, None] = "0003_prc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column("widgets", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("maps", "widgets", schema="catalog")
