"""Add language column to records table.

Revision ID: d1e2f3a4b5c6
Revises: c5d6e7f8a9b0
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "records",
        sa.Column("language", sa.String(10), nullable=True, server_default="en"),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("records", "language", schema="catalog")
