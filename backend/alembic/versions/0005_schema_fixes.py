"""schema fixes: composite indexes, timestamp timezone, server defaults

Revision ID: 0005_schema_fixes
Revises: 0004_performance_indexes
Create Date: 2026-03-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_schema_fixes"
down_revision = "0004_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite index for the primary search access path:
    # visibility + record_status + created_by are filtered together on every query
    op.create_index(
        "idx_records_visibility_status_creator",
        "records",
        ["visibility", "record_status", "created_by"],
        schema="catalog",
    )

    # Composite index for RBAC visibility subquery (dataset_grants JOIN user_roles)
    op.create_index(
        "idx_dataset_grants_role_dataset",
        "dataset_grants",
        ["role_id", "dataset_id"],
        schema="catalog",
    )

    # Fix record_embeddings timestamps: add timezone
    op.alter_column(
        "record_embeddings",
        "created_at",
        type_=sa.DateTime(timezone=True),
        schema="catalog",
    )
    op.alter_column(
        "record_embeddings",
        "updated_at",
        type_=sa.DateTime(timezone=True),
        schema="catalog",
    )

    # Add server_default to ingest_jobs.status (currently only has app default)
    op.alter_column(
        "ingest_jobs",
        "status",
        server_default="pending",
        schema="catalog",
    )


def downgrade() -> None:
    op.alter_column(
        "ingest_jobs",
        "status",
        server_default=None,
        schema="catalog",
    )
    op.alter_column(
        "record_embeddings",
        "updated_at",
        type_=sa.DateTime(timezone=False),
        schema="catalog",
    )
    op.alter_column(
        "record_embeddings",
        "created_at",
        type_=sa.DateTime(timezone=False),
        schema="catalog",
    )
    op.drop_index("idx_dataset_grants_role_dataset", table_name="dataset_grants", schema="catalog")
    op.drop_index("idx_records_visibility_status_creator", table_name="records", schema="catalog")
