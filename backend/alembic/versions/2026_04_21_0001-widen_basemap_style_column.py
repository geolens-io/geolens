"""Widen basemap_style column from varchar(30) to varchar(2000).

Supports custom basemap URLs which can be much longer than 30 characters.

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-04-21 20:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "s5t6u7v8w9x0"
down_revision = "r4s5t6u7v8w9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "maps",
        "basemap_style",
        type_=sa.String(2000),
        existing_type=sa.String(30),
        schema="catalog",
    )


def downgrade() -> None:
    op.alter_column(
        "maps",
        "basemap_style",
        type_=sa.String(30),
        existing_type=sa.String(2000),
        schema="catalog",
    )
