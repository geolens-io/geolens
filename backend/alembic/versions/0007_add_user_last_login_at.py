"""add last_login_at column to users

Revision ID: 0007_add_user_last_login_at
Revises: 0006_add_show_in_legend
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_add_user_last_login_at"
down_revision = "0006_add_show_in_legend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_at", schema="catalog")
