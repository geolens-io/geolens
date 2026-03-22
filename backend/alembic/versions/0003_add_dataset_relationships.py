"""add dataset_relationships table

Revision ID: 0003_dataset_relationships
Revises: 0002_add_table_type
Create Date: 2026-03-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_dataset_relationships"
down_revision = "0002_add_table_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_relationships",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_dataset_id",
            sa.UUID(),
            sa.ForeignKey("catalog.records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_dataset_id",
            sa.UUID(),
            sa.ForeignKey("catalog.records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_column", sa.String(100), nullable=False),
        sa.Column(
            "target_column", sa.String(100), nullable=False, server_default="gid"
        ),
        sa.Column(
            "relationship_type",
            sa.String(20),
            nullable=False,
            server_default="foreign_key",
        ),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "source_dataset_id",
            "target_dataset_id",
            "source_column",
            name="uq_dataset_relationship",
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_table("dataset_relationships", schema="catalog")
