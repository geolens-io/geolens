"""Add notes column to maps.

Revision ID: h5i6j7k8l9m0
Revises: g4h5i6j7k8l9
Create Date: 2026-04-18 20:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h5i6j7k8l9m0"
down_revision = "g4h5i6j7k8l9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "maps",
        sa.Column("notes", sa.Text(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("maps", "notes", schema="catalog")
