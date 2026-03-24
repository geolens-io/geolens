"""add performance indexes for visibility, status, and sort columns

Revision ID: 0004_performance_indexes
Revises: 0003_dataset_relationships
Create Date: 2026-03-24
"""

from alembic import op

revision = "0004_performance_indexes"
down_revision = "0003_dataset_relationships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Phase 1: Critical — frequently filtered columns with no index
    op.create_index(
        "idx_records_visibility",
        "records",
        ["visibility"],
        schema="catalog",
    )
    op.create_index(
        "idx_records_record_type",
        "records",
        ["record_type"],
        schema="catalog",
    )
    op.create_index(
        "idx_records_record_status",
        "records",
        ["record_status"],
        schema="catalog",
    )
    op.create_index(
        "idx_ingest_jobs_status",
        "ingest_jobs",
        ["status"],
        schema="catalog",
    )
    op.create_index(
        "idx_maps_visibility",
        "maps",
        ["visibility"],
        schema="catalog",
    )

    # Phase 2: Sort performance and FK lookups
    op.create_index(
        "idx_maps_created_at_desc",
        "maps",
        ["created_at"],
        schema="catalog",
        postgresql_using="btree",
    )
    op.create_index(
        "idx_map_share_tokens_created_at_desc",
        "map_share_tokens",
        ["created_at"],
        schema="catalog",
        postgresql_using="btree",
    )
    op.create_index(
        "idx_dataset_relationships_source",
        "dataset_relationships",
        ["source_dataset_id"],
        schema="catalog",
    )
    op.create_index(
        "idx_dataset_relationships_target",
        "dataset_relationships",
        ["target_dataset_id"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index("idx_dataset_relationships_target", table_name="dataset_relationships", schema="catalog")
    op.drop_index("idx_dataset_relationships_source", table_name="dataset_relationships", schema="catalog")
    op.drop_index("idx_map_share_tokens_created_at_desc", table_name="map_share_tokens", schema="catalog")
    op.drop_index("idx_maps_created_at_desc", table_name="maps", schema="catalog")
    op.drop_index("idx_maps_visibility", table_name="maps", schema="catalog")
    op.drop_index("idx_ingest_jobs_status", table_name="ingest_jobs", schema="catalog")
    op.drop_index("idx_records_record_status", table_name="records", schema="catalog")
    op.drop_index("idx_records_record_type", table_name="records", schema="catalog")
    op.drop_index("idx_records_visibility", table_name="records", schema="catalog")
